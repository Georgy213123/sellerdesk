"""Шаги прогона: collect → classify → propose → report.

Шаг не коммитит сам: runner сохраняет его результат, чекпоинт и журнал одной транзакцией,
поэтому прогон, упавший посередине, продолжается с первого несохранённого шага без дублей.
Состояние между шагами — только в чекпоинте (JSONB), в памяти процесса ничего не остаётся.
"""

import copy
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm.insights import Case, InsightsProvider, ThemeBrief
from app.llm.pii import mask_pii
from app.models import (
    AgentProposal,
    AgentRun,
    Author,
    Feedback,
    Message,
    ProposalKind,
)
from app.templating import KNOWN_VARIABLES, VAR_RE

Checkpoint = dict[str, Any]

MAX_EVIDENCE_IDS = 50
MAX_EXAMPLES = 5
PROMPT_OVERHEAD_TOKENS = 400  # системный промпт и схема инструмента


def initial_checkpoint() -> Checkpoint:
    # cursor — номер следующей пачки (classify) или темы (propose); batches и top появляются по ходу.
    return {"stage": "collect", "cursor": 0, "batches": [], "themes": {}, "top": []}


@dataclass(frozen=True)
class StepResult:
    checkpoint: Checkpoint
    message: str
    tokens: int = 0
    llm_call: str | None = None  # что спрашивали у модели; None — шаг без LLM


def needs_llm(checkpoint: Checkpoint) -> bool:
    return checkpoint["stage"] in ("classify", "propose")


def estimate_reserve(session: Session, run: AgentRun, provider: InsightsProvider) -> int:
    """Консервативная цена вызова до его начала: потолок ответа плюс вход (два символа на токен)."""
    cp = run.checkpoint
    if cp["stage"] == "classify":
        texts = [c.text for c in _load_cases(session, cp["batches"][cp["cursor"]])]
        texts += [title for _, title in known_themes(cp)]
    else:
        texts = [c.text for c in _load_cases(session, cp["themes"][cp["top"][cp["cursor"]]]["refs"][:MAX_EXAMPLES])]
    return provider.max_output_tokens + PROMPT_OVERHEAD_TOKENS + sum(len(t) for t in texts) // 2


def execute_step(session: Session, run: AgentRun, provider: InsightsProvider, settings: Settings) -> StepResult:
    cp = copy.deepcopy(run.checkpoint)
    match cp["stage"]:
        case "collect":
            result = _collect(session, run, cp, settings)
        case "classify":
            result = _classify(session, cp, provider)
        case "propose":
            result = _propose(session, run, cp, provider)
        case "report":
            result = _report(session, run, cp)
        case stage:
            raise ValueError(f"нет шага для стадии {stage}")
    _settle(result.checkpoint, settings)
    return result


def known_themes(cp: Checkpoint) -> list[tuple[str, str]]:
    """Темы прошлых пачек: модель переиспользует их ключи, и одна тема не дробится по пачкам."""
    return [(key, theme["title"]) for key, theme in cp["themes"].items()]


def cut_classify(cp: Checkpoint, settings: Settings) -> Checkpoint:
    """Досрочно заканчивает classify: оставшиеся пачки пропускаются, дальше propose по накопленным темам."""
    cut = copy.deepcopy(cp)
    cut["cursor"] = len(cut["batches"])
    _settle(cut, settings)
    return cut


def _settle(cp: Checkpoint, settings: Settings) -> None:
    """Переводит прогон на ближайшую стадию, где есть работа: пустые стадии шагов не тратят."""
    if cp["stage"] == "classify" and cp["cursor"] >= len(cp["batches"]):
        ranked = sorted(cp["themes"].items(), key=lambda kv: (-len(kv[1]["refs"]), kv[0]))
        eligible = [key for key, theme in ranked if len(theme["refs"]) >= settings.agent_min_cases]
        cp.update(stage="propose", cursor=0, top=eligible[: settings.agent_top_themes])
    if cp["stage"] == "propose" and cp["cursor"] >= len(cp["top"]):
        cp["stage"] = "report"


def _collect(session: Session, run: AgentRun, cp: Checkpoint, settings: Settings) -> StepResult:
    """Выбирает обращения за период из своей БД (не из площадки) и режет на пачки по ссылкам."""
    feedback = session.execute(
        select(Feedback.id, Feedback.created_at).where(
            Feedback.created_at >= run.period_from, Feedback.created_at < run.period_to
        )
    ).all()
    messages = session.execute(
        select(Message.id, Message.created_at).where(
            Message.author == Author.BUYER, Message.created_at >= run.period_from, Message.created_at < run.period_to
        )
    ).all()
    items = [(at, f"feedback:{i}") for i, at in feedback] + [(at, f"message:{i}") for i, at in messages]
    refs = [ref for _, ref in sorted(items)]
    size = settings.agent_batch_size
    cp["batches"] = [refs[i : i + size] for i in range(0, len(refs), size)]
    cp["stage"] = "classify"
    return StepResult(cp, f"обращений за период: {len(refs)}, пачек: {len(cp['batches'])}")


def _load_cases(session: Session, refs: list[str]) -> list[Case]:
    """Тексты уходят в модель только через mask_pii. Имя покупателя не читается вовсе."""
    ids: dict[str, list[int]] = {"feedback": [], "message": []}
    for ref in refs:
        table, _, raw = ref.partition(":")
        ids[table].append(int(raw))
    cases: dict[str, Case] = {}
    for fb in session.execute(select(Feedback).where(Feedback.id.in_(ids["feedback"]))).scalars():
        cases[f"feedback:{fb.id}"] = Case(f"feedback:{fb.id}", fb.kind, fb.rating, mask_pii(fb.text))
    for msg in session.execute(select(Message).where(Message.id.in_(ids["message"]))).scalars():
        cases[f"message:{msg.id}"] = Case(f"message:{msg.id}", "chat", None, mask_pii(msg.text))
    return [cases[r] for r in refs if r in cases]


def theme_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")[:64]


def _classify(session: Session, cp: Checkpoint, provider: InsightsProvider) -> StepResult:
    refs = cp["batches"][cp["cursor"]]
    themes, tokens = provider.classify(_load_cases(session, refs), known_themes(cp))
    for theme in themes:
        key = theme_key(theme.key)
        if not key:
            continue
        saved = cp["themes"].setdefault(key, {"title": theme.title[:128], "refs": []})
        # Ссылки, которых не было в пачке, модель могла выдумать: их отбрасываем.
        saved["refs"] += [r for r in dict.fromkeys(theme.refs) if r in refs and r not in saved["refs"]]
    cp["cursor"] += 1
    found = len(themes)
    return StepResult(cp, f"пачка {cp['cursor']} из {len(cp['batches'])}: тем {found}", tokens, "classify")


def _strip_unknown_variables(body: str) -> str:
    """Шаблон с чужой переменной не уйдёт покупателю (см. templating), поэтому убираем её сразу."""
    return VAR_RE.sub(lambda m: m.group(0) if m.group(1).lower() in KNOWN_VARIABLES else "", body)


def _propose(session: Session, run: AgentRun, cp: Checkpoint, provider: InsightsProvider) -> StepResult:
    key = cp["top"][cp["cursor"]]
    theme = cp["themes"][key]
    refs: list[str] = theme["refs"]
    examples = [c.text for c in _load_cases(session, refs[:MAX_EXAMPLES])]
    draft, tokens = provider.propose(ThemeBrief(key, theme["title"], len(refs), examples))
    if draft.kind not in {k.value for k in ProposalKind}:
        raise ValueError(f"неизвестный вид предложения: {draft.kind}")
    body = draft.body[:2000]
    if draft.kind == ProposalKind.REPLY_TEMPLATE:
        body = _strip_unknown_variables(body)
    evidence = {
        "cases": len(refs),
        "feedback_ids": [int(r.split(":")[1]) for r in refs if r.startswith("feedback:")][:MAX_EVIDENCE_IDS],
        "message_ids": [int(r.split(":")[1]) for r in refs if r.startswith("message:")][:MAX_EVIDENCE_IDS],
    }
    session.execute(
        insert(AgentProposal)
        .values(run_id=run.id, theme_key=key, kind=draft.kind, title=draft.title[:128], body=body, evidence=evidence)
        .on_conflict_do_nothing(constraint="uq_agent_proposals_run_theme_kind")
    )
    cp["cursor"] += 1
    return StepResult(cp, f"предложение по теме «{theme['title']}»: {draft.kind}", tokens, f"propose {key}")


def _report(session: Session, run: AgentRun, cp: Checkpoint) -> StepResult:
    proposals = session.execute(
        select(func.count()).select_from(AgentProposal).where(AgentProposal.run_id == run.id)
    ).scalar_one()
    cases = sum(len(b) for b in cp["batches"])
    cp["stage"] = "done"
    summary = f"сводка: обращений {cases}, тем {len(cp['themes'])}, предложений {proposals}"
    return StepResult(cp, summary)
