"""Агент-маркетолог: прогон с чекпоинтами, бюджет, возобновление, согласование предложений."""

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app import cli
from app.agent import enqueue_run, run_agent
from app.agent.proposals import decide
from app.agent.steps import _strip_unknown_variables, execute_step
from app.config import Settings, get_settings
from app.db import get_engine, get_sessionmaker
from app.llm.insights import Case, InsightsUnavailable, ProposalDraft, StubInsightsProvider, Theme, ThemeBrief
from app.models import (
    AgentEvent,
    AgentEventKind,
    AgentKind,
    AgentProposal,
    AgentRun,
    AgentRunStatus,
    Feedback,
    Operator,
    ProposalKind,
    ProposalStatus,
    ReplyTemplate,
)
from app.templating import template_variables

KIND = AgentKind.WEEKLY_INSIGHTS


class ProcessKilled(BaseException):
    """Имитация обрыва процесса: не Exception, поэтому runner не успевает записать `failed`."""


class SpyInsights:
    """Заглушка, которая запоминает всё, что ушло «в модель», и умеет оборвать прогон или сломаться."""

    name = "spy"
    max_output_tokens = StubInsightsProvider.max_output_tokens

    def __init__(
        self,
        crash_on_propose: int | None = None,
        crash_after_classify: bool = False,
        classify_error: Exception | None = None,
        propose_error: Exception | None = None,
        propose_error_on: int = 0,
    ) -> None:
        self._inner = StubInsightsProvider()
        self._crash_on_propose = crash_on_propose
        self._crash_after_classify = crash_after_classify
        self._classify_error = classify_error
        self._propose_error = propose_error
        self._propose_error_on = propose_error_on
        self.classify_calls: list[list[Case]] = []
        self.known_calls: list[list[tuple[str, str]]] = []
        self.propose_calls: list[ThemeBrief] = []

    def classify(self, batch: Sequence[Case], known: Sequence[tuple[str, str]] = ()) -> tuple[list[Theme], int]:
        self.classify_calls.append(list(batch))
        self.known_calls.append(list(known))
        if self._classify_error:
            raise self._classify_error
        result = self._inner.classify(batch, known)
        if self._crash_after_classify:
            raise ProcessKilled  # ответ получен (и оплачен), но процесс умер до записи
        return result

    def propose(self, theme: ThemeBrief) -> tuple[ProposalDraft, int]:
        if self._crash_on_propose == len(self.propose_calls):
            raise ProcessKilled
        if self._propose_error and self._propose_error_on == len(self.propose_calls):
            error, self._propose_error = self._propose_error, None  # временная ошибка: повтор пройдёт
            raise error
        self.propose_calls.append(theme)
        return self._inner.propose(theme)

    @property
    def sent_to_model(self) -> str:
        return repr((self.classify_calls, self.propose_calls))


def _settings(**kw: object) -> Settings:
    # Мок-данные датированы октябрём 2026: окно берём с запасом, чтобы тест не зависел от даты запуска.
    return Settings(**{"agent_period_days": 3650, "agent_min_cases": 1, **kw})  # type: ignore[arg-type]


def _run(
    provider: object, run_id: int | None = None, sleep: Callable[[float], None] = lambda _: None, **kw: object
) -> AgentRunStatus | None:
    return run_agent(get_sessionmaker(), KIND, provider, _settings(**kw), run_id=run_id, sleep=sleep)  # type: ignore[arg-type]


def _expire_lease(session: Session, run_id: int) -> None:
    session.execute(update(AgentRun).where(AgentRun.id == run_id).values(lease_until=datetime.now(UTC) - timedelta(1)))
    session.commit()


def _events(session: Session, run_id: int, kind: AgentEventKind | None = None) -> list[AgentEvent]:
    query = select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.id)
    if kind:
        query = query.where(AgentEvent.kind == kind)
    return list(session.execute(query).scalars())


def _last_run(session: Session) -> AgentRun:
    return session.execute(select(AgentRun).order_by(AgentRun.id.desc()).limit(1)).scalar_one()


@pytest.fixture
def agent_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Настройки приложения для тестов через API: широкое окно разбора."""
    monkeypatch.setenv("AGENT_PERIOD_DAYS", "3650")
    monkeypatch.setenv("AGENT_MIN_CASES", "1")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# --- прогон -------------------------------------------------------------------------------------
def test_full_run_on_stub(synced):
    spy = SpyInsights()
    assert _run(spy) == AgentRunStatus.SUCCEEDED

    run = _last_run(synced)
    assert run.status == AgentRunStatus.SUCCEEDED
    assert run.finished_at is not None
    assert run.lease_until is None
    proposals = synced.execute(select(AgentProposal)).scalars().all()
    assert proposals
    assert {p.status for p in proposals} == {ProposalStatus.PENDING}
    assert all(
        p.evidence["cases"] == len(p.evidence["feedback_ids"]) + len(p.evidence["message_ids"]) for p in proposals
    )

    done = _events(synced, run.id, AgentEventKind.STEP_DONE)
    assert run.steps_done == len(done)
    assert [e.step for e in done] == list(range(1, len(done) + 1))
    assert "сводка" in done[-1].message
    llm_tokens = sum(e.tokens for e in _events(synced, run.id, AgentEventKind.LLM_CALL))
    assert run.tokens_used == llm_tokens > 0
    assert len(_events(synced, run.id, AgentEventKind.STEP_STARTED)) == len(done)


def test_run_reads_only_own_database(synced, mocks):
    """Агент не ходит на площадки: «площадки» не вызываются ни разу за прогон."""
    for client in mocks.values():
        client.fetch_chats = client.fetch_feedback = lambda: pytest.fail("агент обратился к площадке")
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED


def test_empty_period_finishes_without_llm(synced):
    spy = SpyInsights()
    assert _run(spy, agent_period_days=1) == AgentRunStatus.SUCCEEDED
    assert not spy.classify_calls
    assert not synced.execute(select(AgentProposal)).scalars().all()


def test_resume_after_crash_has_no_duplicates_and_skips_done_batches(synced):
    first = SpyInsights(crash_on_propose=1)  # на втором propose процесс «умирает»
    with pytest.raises(ProcessKilled):
        _run(first)
    run = _last_run(synced)
    assert run.status == AgentRunStatus.RUNNING
    assert synced.execute(select(func.count()).select_from(AgentProposal)).scalar_one() == 1
    batches = len(first.classify_calls)
    assert batches > 0

    # Пока аренда жива, чужой запуск прогон не трогает.
    bystander = SpyInsights()
    assert _run(bystander) is None
    assert not bystander.classify_calls

    synced.execute(update(AgentRun).where(AgentRun.id == run.id).values(lease_until=datetime.now(UTC) - timedelta(1)))
    synced.commit()

    second = SpyInsights()
    assert _run(second) == AgentRunStatus.SUCCEEDED
    synced.expire_all()
    resumed = synced.get_one(AgentRun, run.id)
    assert resumed.status == AgentRunStatus.SUCCEEDED
    assert _last_run(synced).id == run.id  # новый прогон не заводился
    assert len(_events(synced, run.id, AgentEventKind.RESUMED)) == 1
    assert not second.classify_calls  # классификация уже сохранённых пачек не повторяется
    keys = [(p.theme_key, p.kind) for p in synced.execute(select(AgentProposal)).scalars()]
    assert len(keys) == len(set(keys)) == len(first.propose_calls) + len(second.propose_calls) >= 2


def test_step_is_dropped_if_run_was_taken_over(synced):
    """Прогон подобрал другой процесс, пока шаг шёл: наш результат не записывается."""

    class Taken(SpyInsights):
        def classify(self, batch: Sequence[Case], known: Sequence[tuple[str, str]] = ()) -> tuple[list[Theme], int]:
            with get_sessionmaker()() as other:
                other.execute(update(AgentRun).values(heartbeat_at=datetime.now(UTC) + timedelta(seconds=5)))
                other.commit()
            return super().classify(batch, known)

    assert _run(Taken()) is None
    run = _last_run(synced)
    assert run.status == AgentRunStatus.RUNNING
    assert run.steps_done == 1  # только collect
    assert run.checkpoint["cursor"] == 0
    assert run.tokens_used == 0


def test_unexpected_exception_fails_run_at_once_and_next_launch_starts_new_run(synced):
    assert _run(SpyInsights(classify_error=ValueError("баг"))) == AgentRunStatus.FAILED
    failed = _last_run(synced)
    assert failed.status == AgentRunStatus.FAILED
    assert failed.error == "баг"
    assert _events(synced, failed.id, AgentEventKind.ERROR)

    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    assert _last_run(synced).id > failed.id


def test_transient_error_is_retried_with_pause_inside_one_launch(synced):
    sleeps: list[float] = []
    spy = SpyInsights(propose_error=InsightsUnavailable("лимит"), propose_error_on=1)
    assert _run(spy, sleep=sleeps.append, agent_retry_pause_s=7) == AgentRunStatus.SUCCEEDED
    run = _last_run(synced)
    assert sleeps == [7]
    assert run.status == AgentRunStatus.SUCCEEDED
    assert run.checkpoint["failures"] == 0  # успешный шаг сбросил счётчик
    assert "лимит" in _events(synced, run.id, AgentEventKind.ERROR)[0].message
    assert len(spy.classify_calls) > 0
    keys = [(p.theme_key, p.kind) for p in synced.execute(select(AgentProposal)).scalars()]
    assert len(keys) == len(set(keys)) == len(spy.propose_calls)


def test_transient_errors_fail_run_after_max_attempts(synced):
    sleeps: list[float] = []
    broken = SpyInsights(classify_error=InsightsUnavailable("нет связи"))
    assert _run(broken, sleep=sleeps.append, agent_max_attempts=3) == AgentRunStatus.FAILED
    run = _last_run(synced)
    assert len(sleeps) == 2  # пауза между попытками, после последней не ждём
    assert run.error == "нет связи"
    assert len(_events(synced, run.id, AgentEventKind.ERROR)) == 3
    assert len(broken.classify_calls) == 3
    assert enqueue_run(synced, KIND, _settings())[1] is True  # упавший прогон не держит очередь


def test_refused_call_is_charged_by_reported_tokens(synced):
    spy = SpyInsights(classify_error=InsightsUnavailable("модель отказалась", tokens=700))
    assert _run(spy, agent_max_attempts=1) == AgentRunStatus.FAILED
    run = _last_run(synced)
    assert run.tokens_used == 700
    assert "pending" not in run.checkpoint


def test_stale_abandoned_run_is_closed_and_new_one_started(synced):
    old, _ = enqueue_run(synced, KIND, _settings())
    long_ago = datetime.now(UTC) - timedelta(days=10)
    synced.execute(
        update(AgentRun)
        .where(AgentRun.id == old.id)
        .values(
            status=AgentRunStatus.RUNNING,
            started_at=long_ago,
            heartbeat_at=long_ago,
            lease_until=long_ago,
            period_to=long_ago,
            period_from=long_ago - timedelta(days=7),
        )
    )
    synced.commit()

    assert _run(SpyInsights(), agent_period_days=7) == AgentRunStatus.SUCCEEDED
    synced.expire_all()
    closed = synced.get_one(AgentRun, old.id)
    assert closed.status == AgentRunStatus.FAILED
    assert "устарел" in (closed.error or "")
    newest = _last_run(synced)
    assert newest.id > old.id
    assert newest.period_to > datetime.now(UTC) - timedelta(minutes=5)


def test_fresh_abandoned_run_is_resumed_not_replaced(synced):
    run, _ = enqueue_run(synced, KIND, _settings())
    _expire_lease(synced, run.id)
    synced.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=AgentRunStatus.RUNNING))
    synced.commit()
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    assert _last_run(synced).id == run.id


def test_second_batch_receives_themes_found_in_first(synced):
    spy = SpyInsights()
    assert _run(spy, agent_batch_size=8) == AgentRunStatus.SUCCEEDED
    assert len(spy.classify_calls) >= 2
    assert spy.known_calls[0] == []
    first_keys = {key for key, _ in spy.known_calls[1]}
    assert first_keys
    assert all(title for _, title in spy.known_calls[1])


def test_classify_stage_gets_only_its_share_of_budget(synced):
    spy = SpyInsights()
    status = _run(spy, agent_batch_size=5, agent_classify_budget_share=0.0001)
    assert status == AgentRunStatus.SUCCEEDED
    assert len(spy.classify_calls) == 1  # доля исчерпана после первой пачки
    run = _last_run(synced)
    assert _events(synced, run.id, AgentEventKind.STAGE_CUT)
    assert synced.execute(select(func.count()).select_from(AgentProposal)).scalar_one() >= 1


def test_stale_process_does_not_write_step_started_into_journal(synced):
    class Taken(SpyInsights):
        def classify(self, batch: Sequence[Case], known: Sequence[tuple[str, str]] = ()) -> tuple[list[Theme], int]:
            with get_sessionmaker()() as other:
                other.execute(update(AgentRun).values(heartbeat_at=datetime.now(UTC) + timedelta(seconds=5)))
                other.commit()
            return super().classify(batch, known)

    assert _run(Taken()) is None
    run = _last_run(synced)
    started = _events(synced, run.id, AgentEventKind.STEP_STARTED)
    assert len(started) == run.steps_done == 1  # шага 2 в журнале нет: его владелец потерян


def test_reservation_is_committed_before_llm_call_and_replaced_by_actual(synced):
    seen: list[dict[str, int] | None] = []

    class Peek(SpyInsights):
        def classify(self, batch: Sequence[Case], known: Sequence[tuple[str, str]] = ()) -> tuple[list[Theme], int]:
            with get_sessionmaker()() as other:
                seen.append(other.execute(select(AgentRun.checkpoint)).scalar_one().get("pending"))
            return super().classify(batch, known)

    assert _run(Peek()) == AgentRunStatus.SUCCEEDED
    assert seen
    assert all(p and p["tokens"] >= Peek.max_output_tokens for p in seen)
    run = _last_run(synced)
    assert "pending" not in run.checkpoint
    assert run.tokens_used == sum(e.tokens for e in _events(synced, run.id, AgentEventKind.LLM_CALL))


def test_lost_response_is_charged_by_reservation_and_budget_ends_run(synced):
    budget = 2500
    spies: list[SpyInsights] = []
    status = None
    for _ in range(10):
        spies.append(SpyInsights(crash_after_classify=True))
        try:
            status = _run(spies[-1], agent_token_budget=budget)
        except ProcessKilled:
            _expire_lease(synced, _last_run(synced).id)
            continue
        break
    assert status == AgentRunStatus.BUDGET_EXHAUSTED
    # Каждая потерянная попытка стоит не меньше своего резерва, поэтому их число ограничено бюджетом.
    assert sum(len(s.classify_calls) for s in spies) <= budget // SpyInsights.max_output_tokens + 1


# --- перехват прогона ------------------------------------------------------------------------
def test_run_with_id_only_claims_that_run_and_never_creates_another(synced, session):
    run, _ = enqueue_run(session, KIND, _settings())
    session.execute(update(AgentRun).where(AgentRun.id == run.id).values(status=AgentRunStatus.SUCCEEDED))
    session.commit()

    spy = SpyInsights()
    assert _run(spy, run_id=run.id) is None
    assert synced.execute(select(func.count()).select_from(AgentRun)).scalar_one() == 1
    assert not spy.classify_calls


def test_repeated_propose_step_does_not_duplicate_proposal(synced):
    """Процесс умер после INSERT предложения, до записи чекпоинта: шаг выполнится заново."""
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    run = _last_run(synced)
    total = synced.execute(select(func.count()).select_from(AgentProposal)).scalar_one()
    assert total >= 2
    run.checkpoint = {**run.checkpoint, "stage": "propose", "cursor": 0}  # чекпоинт «не продвинулся»

    for _ in range(2):
        execute_step(synced, run, SpyInsights(), _settings())
        synced.commit()

    assert synced.execute(select(func.count()).select_from(AgentProposal)).scalar_one() == total


def test_propose_strips_unknown_template_variables(synced):
    class Sloppy(SpyInsights):
        def propose(self, theme: ThemeBrief) -> tuple[ProposalDraft, int]:
            body = "Здравствуйте, {{buyer_name}}! {{ Secret_Var }} Заказ {{order_number}}."
            return ProposalDraft(ProposalKind.REPLY_TEMPLATE, "Шаблон", body), 10

    assert _run(Sloppy()) == AgentRunStatus.SUCCEEDED
    for proposal in synced.execute(select(AgentProposal)).scalars():
        assert set(template_variables(proposal.body)) <= {"buyer_name", "order_number"}
        assert "secret_var" not in proposal.body.lower()
        assert "{{buyer_name}}" in proposal.body


def test_strip_unknown_variables_keeps_known_ones():
    body = "{{buyer_name}} {{ PRODUCT }} {{bad}} {{ other_one }}"
    assert _strip_unknown_variables(body) == "{{buyer_name}} {{ PRODUCT }}  "


@pytest.mark.parametrize(
    ("prefix", "phone"),
    [
        ("", "+7.900.111.22.33"),
        ("", "+375 (29) 123-45-67"),
        ("", "8 (900) 111 22 33"),
        ("", "8.900.111.22.33"),
        ("2026-10-30 ", "8 (900) 111 22 33"),
        ("30.10.2026 ", "8 900 111 22 33"),
    ],
)
def test_phone_in_any_format_does_not_reach_provider(synced, prefix, phone):
    synced.add(
        Feedback(
            marketplace="ozon",
            external_id="ph-1",
            kind="review",
            rating=1,
            text=f"Разбита лампа, звоните {prefix}{phone}",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    synced.commit()
    spy = SpyInsights()
    assert _run(spy) == AgentRunStatus.SUCCEEDED
    assert phone not in spy.sent_to_model
    assert "[телефон]" in spy.sent_to_model


# --- API ------------------------------------------------------------------------------------------
def test_api_start_run_lists_and_details(client: TestClient, auth, synced, agent_env):
    r = client.post("/api/agent/runs", headers=auth)
    assert r.status_code == 202
    run_id = r.json()["id"]

    listed = client.get("/api/agent/runs", headers=auth).json()
    assert [x["id"] for x in listed] == [run_id]
    detail = client.get(f"/api/agent/runs/{run_id}", headers=auth).json()
    assert detail["status"] == "succeeded"
    assert detail["steps_done"] == detail["events"][-1]["step"]
    assert {e["kind"] for e in detail["events"]} >= {"step_started", "step_done", "llm_call"}
    assert client.get("/api/agent/runs/9999", headers=auth).status_code == 404

    pending = client.get("/api/agent/proposals", params={"status": "pending"}, headers=auth).json()
    assert pending
    assert client.get("/api/agent/proposals", params={"status": "bogus"}, headers=auth).status_code == 422


def test_api_second_start_while_active_is_409(client: TestClient, auth, session, agent_env):
    enqueue_run(session, KIND, get_settings())
    r = client.post("/api/agent/runs", headers=auth)
    assert r.status_code == 409


def _take_over_ready(session: Session, run_id: int, lease_delta: timedelta) -> None:
    now = datetime.now(UTC)
    session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(status=AgentRunStatus.RUNNING, started_at=now, heartbeat_at=now, lease_until=now + lease_delta)
    )
    session.commit()


def test_api_start_resumes_run_with_expired_lease(client: TestClient, auth, synced, agent_env):
    run, _ = enqueue_run(synced, KIND, get_settings())
    _take_over_ready(synced, run.id, timedelta(minutes=-1))

    r = client.post("/api/agent/runs", headers=auth)
    assert r.status_code == 202
    assert r.json()["id"] == run.id
    detail = client.get(f"/api/agent/runs/{run.id}", headers=auth).json()
    assert detail["status"] == "succeeded"
    assert "resumed" in {e["kind"] for e in detail["events"]}


def test_api_marks_abandoned_run(client: TestClient, auth, synced, agent_env):
    run, _ = enqueue_run(synced, KIND, get_settings())
    _take_over_ready(synced, run.id, timedelta(minutes=5))
    assert client.get(f"/api/agent/runs/{run.id}", headers=auth).json()["abandoned"] is False
    _take_over_ready(synced, run.id, timedelta(minutes=-5))
    assert client.get("/api/agent/runs", headers=auth).json()[0]["abandoned"] is True
    assert client.get(f"/api/agent/runs/{run.id}", headers=auth).json()["abandoned"] is True


def test_api_start_with_live_owner_is_409(client: TestClient, auth, synced, agent_env):
    run, _ = enqueue_run(synced, KIND, get_settings())
    _take_over_ready(synced, run.id, timedelta(minutes=5))
    assert client.post("/api/agent/runs", headers=auth).status_code == 409


def test_api_background_task_is_bound_to_created_run(client: TestClient, auth, monkeypatch, agent_env):
    calls: list[int | None] = []
    monkeypatch.setattr("app.api.agent.run_agent", lambda *a, run_id=None, **k: calls.append(run_id))
    r = client.post("/api/agent/runs", headers=auth)
    assert r.status_code == 202
    assert calls == [r.json()["id"]]


def test_api_start_when_disabled_is_503(client: TestClient, auth, monkeypatch, agent_env):
    monkeypatch.setenv("AGENT_ENABLED", "false")
    get_settings.cache_clear()
    assert client.post("/api/agent/runs", headers=auth).status_code == 503


def test_api_requires_login(client: TestClient):
    assert client.get("/api/agent/runs").status_code == 401
    assert client.post("/api/agent/proposals/1/approve").status_code == 401


def _proposal(session: Session, kind: ProposalKind) -> AgentProposal:
    return session.execute(
        select(AgentProposal).where(AgentProposal.kind == kind).order_by(AgentProposal.id).limit(1)
    ).scalar_one()


def test_approve_template_creates_template_and_repeat_is_409(client: TestClient, auth, synced):
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    proposal = _proposal(synced, ProposalKind.REPLY_TEMPLATE)
    before = len(client.get("/api/templates", headers=auth).json())

    r = client.post(f"/api/agent/proposals/{proposal.id}/approve", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by"] is not None
    templates = client.get("/api/templates", headers=auth).json()
    assert len(templates) == before + 1
    assert templates[-1]["name"] == proposal.title
    assert templates[-1]["body"] == proposal.body

    assert client.post(f"/api/agent/proposals/{proposal.id}/approve", headers=auth).status_code == 409
    assert client.post(f"/api/agent/proposals/{proposal.id}/reject", headers=auth).status_code == 409
    assert len(client.get("/api/templates", headers=auth).json()) == before + 1


def test_reject_creates_nothing(client: TestClient, auth, synced):
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    proposal = _proposal(synced, ProposalKind.REPLY_TEMPLATE)
    before = synced.execute(select(func.count()).select_from(ReplyTemplate)).scalar_one()

    r = client.post(f"/api/agent/proposals/{proposal.id}/reject", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert synced.execute(select(func.count()).select_from(ReplyTemplate)).scalar_one() == before
    assert client.post(f"/api/agent/proposals/{proposal.id}/approve", headers=auth).status_code == 409


def test_approve_card_edit_only_marks_approved(client: TestClient, auth, synced):
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    proposal = _proposal(synced, ProposalKind.CARD_EDIT)
    before = synced.execute(select(func.count()).select_from(ReplyTemplate)).scalar_one()

    assert client.post(f"/api/agent/proposals/{proposal.id}/approve", headers=auth).status_code == 200
    assert synced.execute(select(func.count()).select_from(ReplyTemplate)).scalar_one() == before


def test_approve_unknown_proposal_is_404(client: TestClient, auth):
    assert client.post("/api/agent/proposals/9999/approve", headers=auth).status_code == 404


def test_template_name_clash_keeps_proposal_pending(client: TestClient, auth, synced):
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    proposal = _proposal(synced, ProposalKind.REPLY_TEMPLATE)
    synced.add(ReplyTemplate(name=proposal.title, body="Другой текст"))
    synced.commit()

    r = client.post(f"/api/agent/proposals/{proposal.id}/approve", headers=auth)
    assert r.status_code == 409
    synced.expire_all()
    assert synced.get_one(AgentProposal, proposal.id).status == ProposalStatus.PENDING


def test_same_template_is_not_duplicated(client: TestClient, auth, synced):
    assert _run(SpyInsights()) == AgentRunStatus.SUCCEEDED
    proposal = _proposal(synced, ProposalKind.REPLY_TEMPLATE)
    synced.add(ReplyTemplate(name=proposal.title, body=proposal.body))
    synced.commit()
    before = synced.execute(select(func.count()).select_from(ReplyTemplate)).scalar_one()

    assert client.post(f"/api/agent/proposals/{proposal.id}/approve", headers=auth).status_code == 200
    assert synced.execute(select(func.count()).select_from(ReplyTemplate)).scalar_one() == before


# --- CLI ----------------------------------------------------------------------------------------------
def test_cli_exit_codes(synced, monkeypatch, agent_env):
    assert cli.main(["agent", "run"]) == 0
    synced.execute(text("DELETE FROM agent_runs"))
    synced.commit()

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "1")
    get_settings.cache_clear()
    assert cli.main(["agent", "run"]) == 2
    synced.execute(text("DELETE FROM agent_runs"))
    synced.commit()

    class Broken(SpyInsights):
        def classify(self, batch: Sequence[Case], known: Sequence[tuple[str, str]] = ()) -> tuple[list[Theme], int]:
            raise InsightsUnavailable("нет связи")

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "60000")
    monkeypatch.setenv("AGENT_RETRY_PAUSE_S", "0")
    get_settings.cache_clear()
    monkeypatch.setattr(cli, "get_insights_provider", lambda settings: Broken())
    assert cli.main(["agent", "run"]) == 1


def test_cli_agent_needs_action():
    with pytest.raises(SystemExit):
        cli.main(["agent"])


# --- параллельное одобрение ---------------------------------------------------------------------
class _SlowCommit(Session):
    """Сессия, которая перед фиксацией ждёт сигнала: так вторая транзакция успевает начаться."""

    inserted = threading.Event()
    release = threading.Event()

    def commit(self) -> None:
        self.inserted.set()
        self.release.wait(5)
        super().commit()


def test_concurrent_approval_of_same_template_is_not_a_conflict(synced):
    run = _last_run_or_new(synced)
    proposals = [
        AgentProposal(
            run_id=run.id,
            theme_key=key,
            kind=ProposalKind.REPLY_TEMPLATE,
            title="Одинаковый шаблон",
            body="Здравствуйте, {{buyer_name}}!",
            evidence={"cases": 1, "feedback_ids": [], "message_ids": []},
        )
        for key in ("one", "two")
    ]
    synced.add_all(proposals)
    synced.commit()
    ids = [p.id for p in proposals]
    operator_id = synced.execute(select(Operator.id)).scalar_one()
    _SlowCommit.inserted.clear()
    _SlowCommit.release.clear()
    results: dict[int, object] = {}

    def approve(index: int, session_cls: type[Session]) -> None:
        with session_cls(bind=get_engine()) as s:
            try:
                results[index] = decide(s, ids[index], operator_id, approve=True).status
            except Exception as exc:
                results[index] = exc

    first = threading.Thread(target=approve, args=(0, _SlowCommit))
    first.start()
    assert _SlowCommit.inserted.wait(5)  # первая транзакция вставила шаблон и ещё не зафиксировала
    second = threading.Thread(target=approve, args=(1, Session))
    second.start()
    time.sleep(0.5)
    _SlowCommit.release.set()
    first.join(10)
    second.join(10)

    assert results == {0: ProposalStatus.APPROVED, 1: ProposalStatus.APPROVED}
    names = synced.execute(select(ReplyTemplate.name).where(ReplyTemplate.name == "Одинаковый шаблон")).all()
    assert len(names) == 1


def _last_run_or_new(session: Session) -> AgentRun:
    return enqueue_run(session, KIND, _settings())[0]
