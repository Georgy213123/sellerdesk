"""HTTP-слой агента-маркетолога: прогоны и предложения на согласование."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import select

from app.agent import enqueue_run, run_agent
from app.agent.proposals import AlreadyDecided, ProposalNotFound, TemplateNameTaken, decide
from app.agent.runner import is_abandoned
from app.api.deps import OperatorDep, SessionDep
from app.config import get_settings
from app.db import get_sessionmaker
from app.llm.insights import get_insights_provider
from app.models import AgentKind, AgentProposal, AgentRun
from app.schemas import AgentRunDetailOut, AgentRunOut, ErrorOut, ProposalOut, ProposalStatusCode

router = APIRouter(prefix="/agent", tags=["agent"])

RUNS_LIMIT = 20
PROPOSALS_LIMIT = 100
CONFLICT: dict[int | str, dict[str, Any]] = {409: {"model": ErrorOut}}


@router.post(
    "/runs",
    response_model=AgentRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**CONFLICT, 503: {"model": ErrorOut}},
)
def start_run(session: SessionDep, _: OperatorDep, background: BackgroundTasks) -> AgentRunOut:
    """Ставит прогон и сразу отвечает. Разбор идёт в фоне, результат — в списке прогонов и предложений.

    Если активный прогон брошен (аренда истекла), возобновляет его и отвечает 202 с прежним id.
    """
    settings = get_settings()
    if not settings.agent_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "агент выключен")
    run, created = enqueue_run(session, AgentKind.WEEKLY_INSIGHTS, settings)
    # Активный прогон без живого владельца (аренда истекла) возобновляем; с живым — отказ.
    if not created and not is_abandoned(run, settings):
        raise HTTPException(status.HTTP_409_CONFLICT, "разбор уже идёт")
    background.add_task(
        run_agent,
        get_sessionmaker(),
        AgentKind.WEEKLY_INSIGHTS,
        get_insights_provider(settings),
        settings,
        run_id=run.id,
    )
    return AgentRunOut.model_validate(run)


@router.get("/runs", response_model=list[AgentRunOut])
def list_runs(session: SessionDep, _: OperatorDep) -> list[AgentRunOut]:
    rows = session.execute(select(AgentRun).order_by(AgentRun.id.desc()).limit(RUNS_LIMIT)).scalars().all()
    return [AgentRunOut.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=AgentRunDetailOut, responses={404: {"model": ErrorOut}})
def get_run(run_id: int, session: SessionDep, _: OperatorDep) -> AgentRunDetailOut:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "прогон не найден")
    return AgentRunDetailOut.model_validate(run)


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    session: SessionDep,
    _: OperatorDep,
    proposal_status: Annotated[ProposalStatusCode | None, Query(alias="status")] = None,
) -> list[ProposalOut]:
    query = select(AgentProposal).order_by(AgentProposal.id.desc()).limit(PROPOSALS_LIMIT)
    if proposal_status:
        query = query.where(AgentProposal.status == proposal_status)
    return [ProposalOut.model_validate(p) for p in session.execute(query).scalars()]


def _decide(session: SessionDep, proposal_id: int, operator_id: int, approve: bool) -> ProposalOut:
    try:
        return ProposalOut.model_validate(decide(session, proposal_id, operator_id, approve))
    except ProposalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (AlreadyDecided, TemplateNameTaken) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=ProposalOut,
    responses={**CONFLICT, 404: {"model": ErrorOut}},
)
def approve_proposal(proposal_id: int, session: SessionDep, operator: OperatorDep) -> ProposalOut:
    """Одобрить. Шаблон ответа будет создан; правка карточки только помечается одобренной."""
    return _decide(session, proposal_id, operator.id, approve=True)


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=ProposalOut,
    responses={**CONFLICT, 404: {"model": ErrorOut}},
)
def reject_proposal(proposal_id: int, session: SessionDep, operator: OperatorDep) -> ProposalOut:
    return _decide(session, proposal_id, operator.id, approve=False)
