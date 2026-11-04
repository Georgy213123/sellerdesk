"""Раннер прогона: аренда с heartbeat, чекпоинт после каждого шага, бюджет и лимит шагов.

Захват прогона — условный UPDATE (как у задач синхронизации): `queued` или `running` с истёкшей
арендой. Зависший прогон подбирает следующий запуск и продолжает с чекпоинта.
Каждый шаг фиксируется одной транзакцией: результат шага, чекпоинт, расход токенов, журнал и
продление аренды. Запись защищена значением heartbeat: если за время шага прогон подобрал другой
процесс, наша запись не пройдёт и шаг откатится целиком.

Бюджет защищён резервом. Перед вызовом LLM в чекпоинт коммитится `pending` — консервативная цена
вызова. Ответ заменяет резерв фактическим расходом. Если процесс умер между вызовом и записью,
следующий запуск спишет резерв: оплаченный, но потерянный ответ не остаётся неучтённым.
Временная ошибка провайдера не убивает прогон: счётчик `failures` растёт, аренда отдаётся,
следующий запуск продолжает с чекпоинта; после `agent_max_attempts` подряд прогон становится failed.
"""

import copy
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.agent.steps import estimate_reserve, execute_step, initial_checkpoint, needs_llm
from app.config import Settings
from app.llm.insights import InsightsProvider, InsightsUnavailable
from app.models import AgentEvent, AgentEventKind, AgentRun, AgentRunStatus

log = logging.getLogger(__name__)

ACTIVE = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING)
_ENQUEUE_ATTEMPTS = 5


def enqueue_run(session: Session, kind: str, settings: Settings) -> tuple[AgentRun, bool]:
    """Ставит прогон. Если активный уже есть — возвращает его: единственность держит частичный индекс."""
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "kind": kind,
        "status": AgentRunStatus.QUEUED,
        "period_from": now - timedelta(days=settings.agent_period_days),
        "period_to": now,
        "checkpoint": initial_checkpoint(),
        "token_budget": settings.agent_token_budget,
        "max_steps": settings.agent_max_steps,
    }
    # Активный прогон может завершиться между конфликтом вставки и выборкой: тогда ставим заново.
    for _ in range(_ENQUEUE_ATTEMPTS):
        new_id = session.execute(
            insert(AgentRun).values(**values).on_conflict_do_nothing().returning(AgentRun.id)
        ).scalar_one_or_none()
        if new_id is not None:
            session.commit()
            return session.get_one(AgentRun, new_id), True
        active = session.execute(
            select(AgentRun).where(AgentRun.kind == kind, AgentRun.status.in_(ACTIVE))
        ).scalar_one_or_none()
        session.commit()
        if active is not None:
            return active, False
    raise RuntimeError("не удалось поставить прогон агента: активные прогоны завершаются слишком часто")


def is_abandoned(run: AgentRun, settings: Settings) -> bool:
    """Прогон без живого владельца: аренда истекла (или он так и не стартовал дольше аренды)."""
    now = datetime.now(UTC)
    if run.status == AgentRunStatus.RUNNING:
        return run.lease_until is None or run.lease_until < now
    return run.status == AgentRunStatus.QUEUED and run.created_at + timedelta(seconds=settings.agent_lease_s) < now


def _event(session: Session, run_id: int, step: int, kind: AgentEventKind, message: str, tokens: int = 0) -> None:
    session.add(AgentEvent(run_id=run_id, step=step, kind=kind, message=message, tokens=tokens))


def _claim(session: Session, run: AgentRun, settings: Settings) -> datetime | None:
    """Берёт прогон под аренду. Возвращает метку heartbeat (она же «токен» владельца) или None."""
    now = datetime.now(UTC)
    resumed = run.started_at is not None  # до UPDATE: он синхронизирует поля объекта в сессии
    claimed = session.execute(
        update(AgentRun)
        .where(
            AgentRun.id == run.id,
            or_(
                AgentRun.status == AgentRunStatus.QUEUED,
                and_(AgentRun.status == AgentRunStatus.RUNNING, AgentRun.lease_until < now),
            ),
        )
        .values(
            status=AgentRunStatus.RUNNING,
            started_at=now if run.started_at is None else run.started_at,
            heartbeat_at=now,
            lease_until=now + timedelta(seconds=settings.agent_lease_s),
        )
        .returning(AgentRun.id)
    ).scalar_one_or_none()
    if claimed is None:
        session.rollback()
        return None
    if resumed:
        _event(session, run.id, run.steps_done, AgentEventKind.RESUMED, f"продолжаю с шага {run.steps_done + 1}")
    session.commit()
    return now


def _finish(session: Session, run_id: int, owner: datetime, status: AgentRunStatus, error: str | None = None) -> bool:
    finished = session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == AgentRunStatus.RUNNING, AgentRun.heartbeat_at == owner)
        .values(status=status, finished_at=datetime.now(UTC), lease_until=None, error=error)
        .returning(AgentRun.id)
    ).scalar_one_or_none()
    return finished is not None


def _close(
    session: Session, run: AgentRun, owner: datetime, status: AgentRunStatus, error: str | None = None
) -> AgentRunStatus | None:
    if not _finish(session, run.id, owner, status, error):
        session.rollback()
        return None
    session.commit()
    return status


def _save(
    session: Session, run_id: int, owner: datetime, settings: Settings, release: bool = False, **values: Any
) -> datetime | None:
    """Фиксирует транзакцию, если прогон всё ещё наш. Возвращает новую метку heartbeat или None.

    `release=True` отдаёт аренду сразу: следующий запуск подберёт прогон без ожидания.
    """
    now = datetime.now(UTC)
    lease = now if release else now + timedelta(seconds=settings.agent_lease_s)
    saved = session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == AgentRunStatus.RUNNING, AgentRun.heartbeat_at == owner)
        .values(heartbeat_at=now, lease_until=lease, **values)
        .returning(AgentRun.id)
    ).scalar_one_or_none()
    if saved is None:
        session.rollback()
        log.warning("прогон %s подобран другим процессом, запись отброшена", run_id)
        return None
    session.commit()
    return now


def _stop_reason(run: AgentRun) -> str | None:
    if run.steps_done >= run.max_steps:
        return f"лимит шагов: {run.max_steps}"
    if needs_llm(run.checkpoint) and run.tokens_used >= run.token_budget:
        return f"бюджет токенов: {run.tokens_used} из {run.token_budget}"
    return None


def _charge_pending(session: Session, run: AgentRun, owner: datetime, settings: Settings) -> datetime | None:
    """Прошлый владелец умер между вызовом LLM и записью ответа: расход неизвестен, списываем резерв."""
    pending = run.checkpoint["pending"]
    checkpoint = {k: v for k, v in run.checkpoint.items() if k != "pending"}
    message = f"попытка шага {pending['step']} не завершена, списан резерв"
    _event(session, run.id, run.steps_done, AgentEventKind.LLM_CALL, message, pending["tokens"])
    return _save(
        session, run.id, owner, settings, checkpoint=checkpoint, tokens_used=run.tokens_used + pending["tokens"]
    )


def _reserve(
    session: Session, run: AgentRun, owner: datetime, provider: InsightsProvider, settings: Settings, step: int
) -> datetime | None:
    pending = {"step": step, "tokens": estimate_reserve(session, run, provider)}
    reserved = _save(session, run.id, owner, settings, checkpoint={**run.checkpoint, "pending": pending})
    if reserved is not None:
        session.refresh(run)
    return reserved


def _transient_failure(
    session: Session, run: AgentRun, owner: datetime, settings: Settings, step: int, exc: Exception
) -> AgentRunStatus | None:
    """Ошибка провайдера: прогон остаётся в прежнем чекпоинте. Резерв снимаем: ответа не было."""
    run = session.get_one(AgentRun, run.id, populate_existing=True)
    checkpoint = {k: v for k, v in run.checkpoint.items() if k != "pending"}
    checkpoint["failures"] = checkpoint.get("failures", 0) + 1
    _event(session, run.id, step, AgentEventKind.ERROR, str(exc)[:500])
    owner_ = _save(session, run.id, owner, settings, release=True, checkpoint=checkpoint)
    if owner_ is None:
        return None
    if checkpoint["failures"] >= settings.agent_max_attempts:
        return _close(session, run, owner_, AgentRunStatus.FAILED, str(exc)[:500])
    return AgentRunStatus.RUNNING


def run_agent(
    factory: sessionmaker[Session],
    kind: str,
    provider: InsightsProvider,
    settings: Settings,
    run_id: int | None = None,
) -> AgentRunStatus | None:
    """Выполняет прогон и возвращает его статус на выходе из этого запуска.

    Без `run_id` берёт активный прогон вида `kind` или ставит новый (CLI, таймер). С `run_id`
    только захватывает этот прогон и никогда не создаёт другой (фоновая задача API).
    None — прогон не наш: агент выключен, прогон уже закончен или им владеет другой процесс.
    RUNNING — временная ошибка провайдера: прогон ждёт следующего запуска.

    Бюджет проверяется перед шагом, а перед вызовом LLM коммитится резерв; поэтому превышение
    бюджета ограничено одним резервом. `budget_exhausted` — не ошибка: сделанное сохранено.
    """
    if not settings.agent_enabled:
        log.info("агент выключен (AGENT_ENABLED=false)")
        return None
    with factory() as session:
        if run_id is None:
            run, _ = enqueue_run(session, kind, settings)
        else:
            found = session.get(AgentRun, run_id)
            if found is None or found.status not in ACTIVE:
                log.info("прогон %s уже не активен", run_id)
                return None
            run = found
        owner = _claim(session, run, settings)
        if owner is None:
            log.info("прогон %s ведёт другой процесс", run.id)
            return None

        while True:
            run = session.get_one(AgentRun, run.id, populate_existing=True)
            if run.checkpoint.get("pending"):
                charged = _charge_pending(session, run, owner, settings)
                if charged is None:
                    return None
                owner = charged
                continue
            if run.checkpoint["stage"] == "done":
                return _close(session, run, owner, AgentRunStatus.SUCCEEDED)
            if reason := _stop_reason(run):
                _event(session, run.id, run.steps_done, AgentEventKind.BUDGET_STOP, reason)
                return _close(session, run, owner, AgentRunStatus.BUDGET_EXHAUSTED)

            step = run.steps_done + 1
            _event(session, run.id, step, AgentEventKind.STEP_STARTED, f"стадия {run.checkpoint['stage']}")
            session.commit()
            try:
                if needs_llm(run.checkpoint):
                    reserved = _reserve(session, run, owner, provider, settings, step)
                    if reserved is None:
                        return None
                    owner = reserved
                result = execute_step(session, run, provider, settings)
                if result.llm_call:
                    _event(session, run.id, step, AgentEventKind.LLM_CALL, result.llm_call, result.tokens)
                _event(session, run.id, step, AgentEventKind.STEP_DONE, result.message, result.tokens)
                checkpoint = copy.deepcopy(result.checkpoint)
                checkpoint.pop("pending", None)
                checkpoint["failures"] = 0
                saved = _save(
                    session,
                    run.id,
                    owner,
                    settings,
                    checkpoint=checkpoint,
                    steps_done=step,
                    tokens_used=run.tokens_used + result.tokens,
                )
                if saved is None:
                    return None
                owner = saved
            except InsightsUnavailable as exc:
                session.rollback()
                log.warning("прогон %s: шаг %s, провайдер недоступен: %s", run.id, step, exc)
                return _transient_failure(session, run, owner, settings, step, exc)
            except Exception as exc:
                session.rollback()
                log.exception("прогон %s: шаг %s упал", run.id, step)
                _event(session, run.id, step, AgentEventKind.ERROR, str(exc)[:500])
                return _close(session, run, owner, AgentRunStatus.FAILED, str(exc)[:500])
