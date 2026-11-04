"""Решения оператора по предложениям агента.

Одобренный «шаблон» создаёт шаблон ответа (внутреннее действие, покупателю ничего не уходит).
Одобренная «правка карточки» только помечается одобренной: адаптера записи в площадку в демо
нет, оператор вносит правку сам. Агент и этот модуль наружу не пишут.
"""

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AgentProposal, ProposalKind, ProposalStatus, ReplyTemplate


class ProposalError(Exception):
    """Базовая ошибка решения. Текст — причина для оператора."""


class ProposalNotFound(ProposalError):
    pass


class AlreadyDecided(ProposalError):
    pass


class TemplateNameTaken(ProposalError):
    pass


def decide(session: Session, proposal_id: int, operator_id: int, approve: bool) -> AgentProposal:
    """Решение принимается один раз: условный UPDATE `pending → approved|rejected`."""
    new_status = ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED
    decided = session.execute(
        update(AgentProposal)
        .where(AgentProposal.id == proposal_id, AgentProposal.status == ProposalStatus.PENDING)
        .values(status=new_status, decided_by=operator_id, decided_at=func.now())
        .returning(AgentProposal.id)
    ).scalar_one_or_none()
    if decided is None:
        session.rollback()
        if session.get(AgentProposal, proposal_id) is None:
            raise ProposalNotFound("предложение не найдено")
        raise AlreadyDecided("по предложению уже есть решение")

    proposal = session.get_one(AgentProposal, proposal_id, populate_existing=True)
    if approve and proposal.kind == ProposalKind.REPLY_TEMPLATE:
        try:
            _ensure_template(session, proposal)
        except ProposalError:
            session.rollback()  # решение откатывается вместе с шаблоном: предложение остаётся на согласовании
            raise
    session.commit()
    return proposal


def _ensure_template(session: Session, proposal: AgentProposal) -> None:
    """Вставка атомарна: параллельное одобрение такого же шаблона не даёт ложного конфликта."""
    inserted = session.execute(
        insert(ReplyTemplate)
        .values(name=proposal.title, body=proposal.body)
        .on_conflict_do_nothing(index_elements=["name"])
        .returning(ReplyTemplate.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return
    # Шаблон с таким названием уже есть. Тот же текст — копия не нужна, другой текст — конфликт.
    body = session.execute(select(ReplyTemplate.body).where(ReplyTemplate.name == proposal.title)).scalar_one()
    if body != proposal.body:
        raise TemplateNameTaken("шаблон с таким названием уже есть")
