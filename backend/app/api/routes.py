"""HTTP-слой. Логика — в сервисах (sync, replies), здесь только разбор запроса и коды ответа."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import replies
from app.api.deps import OperatorDep, SessionDep
from app.db import get_sessionmaker
from app.llm import get_llm_provider
from app.marketplaces import get_client, get_clients
from app.models import Chat, Feedback, Message, Operator, ReplyTemplate, SyncJob
from app.schemas import (
    ChatList,
    ChatListItem,
    ChatOut,
    ChatStatusCode,
    DraftOut,
    ErrorOut,
    FeedbackList,
    FeedbackOut,
    HealthOut,
    LoginIn,
    MarketplaceCode,
    MessageOut,
    OperatorOut,
    ReplyIn,
    ReplyOut,
    SyncJobOut,
    TemplateIn,
    TemplateOut,
    TemplateReplyIn,
    TemplateReplyOut,
    TokenOut,
)
from app.security import create_token, verify_password
from app.sync import enqueue_sync, run_sync_job
from app.templating import KNOWN_VARIABLES, template_variables

router = APIRouter(prefix="/api")

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorOut}}
IdemKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        description="Один ключ на одно намерение ответить. Повтор с тем же ключом не отправит второй ответ.",
    ),
]


# --- служебное ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthOut, tags=["service"])
def health(session: SessionDep) -> HealthOut:
    session.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="ok")


@router.post("/auth/login", response_model=TokenOut, responses={401: {"model": ErrorOut}}, tags=["auth"])
def login(body: LoginIn, session: SessionDep) -> TokenOut:
    operator = session.execute(select(Operator).where(Operator.login == body.login)).scalar_one_or_none()
    if operator is None or not verify_password(body.password, operator.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "неверный логин или пароль")
    return TokenOut(access_token=create_token(operator.id), operator=OperatorOut.model_validate(operator))


@router.get("/auth/me", response_model=OperatorOut, tags=["auth"])
def me(operator: OperatorDep) -> OperatorOut:
    return OperatorOut.model_validate(operator)


# --- чаты ------------------------------------------------------------------------------------
def _chat_out(chat: Chat) -> ChatOut:
    return ChatOut(
        id=chat.id,
        marketplace=chat.marketplace,
        external_id=chat.external_id,
        buyer_name=chat.buyer_name,
        product_sku=chat.product_sku,
        product_title=chat.product.title if chat.product else None,
        order_number=chat.order_number,
        status=chat.status,
        last_message_at=chat.last_message_at,
        draft_text=chat.draft_text,
        draft_note=chat.draft_note,
        messages=[MessageOut.model_validate(m) for m in chat.messages],
    )


@router.get("/chats", response_model=ChatList, tags=["chats"])
def list_chats(
    session: SessionDep,
    _: OperatorDep,
    marketplace: MarketplaceCode | None = None,
    chat_status: Annotated[ChatStatusCode | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatList:
    """Единая лента чатов всех площадок, свежие сверху. Сортировка по UTC-времени (BUG-02)."""
    where = []
    if marketplace:
        where.append(Chat.marketplace == marketplace)
    if chat_status:
        where.append(Chat.status == chat_status)

    last_text = (
        select(Message.text)
        .where(Message.chat_id == Chat.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .correlate(Chat)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Chat, last_text)
        .where(*where)
        .order_by(Chat.last_message_at.desc(), Chat.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.execute(select(func.count()).select_from(Chat).where(*where)).scalar_one()
    return ChatList(
        items=[
            ChatListItem(
                id=c.id,
                marketplace=c.marketplace,
                buyer_name=c.buyer_name,
                product_title=c.product.title if c.product else None,
                order_number=c.order_number,
                status=c.status,
                last_message_at=c.last_message_at,
                last_message_preview=(t or "")[:140],
            )
            for c, t in rows
        ],
        total=total,
    )


def _get_chat(session: SessionDep, chat_id: int) -> Chat:
    chat = session.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "чат не найден")
    return chat


@router.get("/chats/{chat_id}", response_model=ChatOut, responses=NOT_FOUND, tags=["chats"])
def get_chat(chat_id: int, session: SessionDep, _: OperatorDep) -> ChatOut:
    return _chat_out(_get_chat(session, chat_id))


@router.post(
    "/chats/{chat_id}/reply",
    response_model=ReplyOut,
    responses={**NOT_FOUND, 409: {"model": ErrorOut}, 502: {"model": ErrorOut}},
    tags=["chats"],
)
def reply_to_chat(
    chat_id: int, body: ReplyIn, idempotency_key: IdemKey, session: SessionDep, _: OperatorDep
) -> ReplyOut:
    chat = _get_chat(session, chat_id)
    try:
        result = replies.send_chat_reply(session, get_client(chat.marketplace), chat_id, body.text, idempotency_key)
    except replies.ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except replies.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return ReplyOut(message=MessageOut.model_validate(result.message), duplicate=result.duplicate)


@router.post("/chats/{chat_id}/ai-draft", response_model=DraftOut, responses=NOT_FOUND, tags=["chats"])
def chat_ai_draft(chat_id: int, session: SessionDep, _: OperatorDep) -> DraftOut:
    """Черновик от LLM-провайдера. Сохраняется в карточке, покупателю не уходит."""
    text_, provider = replies.ai_draft_chat(session, get_llm_provider(), _get_chat(session, chat_id))
    return DraftOut(text=text_, provider=provider)


def _get_template(session: SessionDep, template_id: int) -> ReplyTemplate:
    tpl = session.get(ReplyTemplate, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "шаблон не найден")
    return tpl


@router.post(
    "/chats/{chat_id}/template-reply",
    response_model=TemplateReplyOut,
    responses={**NOT_FOUND, 409: {"model": ErrorOut}, 502: {"model": ErrorOut}},
    tags=["chats"],
)
def chat_template_reply(
    chat_id: int,
    body: TemplateReplyIn,
    idempotency_key: IdemKey,
    session: SessionDep,
    operator: OperatorDep,
) -> TemplateReplyOut:
    """Автоответ по шаблону. Если переменная не подставилась — не отправляет, а кладёт черновик с причиной."""
    chat = _get_chat(session, chat_id)
    tpl = _get_template(session, body.template_id)
    try:
        out = replies.template_reply_chat(
            session, get_client(chat.marketplace), chat, tpl.body, operator, idempotency_key
        )
    except replies.ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except replies.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return TemplateReplyOut(sent=out.sent, text=out.text, missing=out.missing, note=out.note)


# --- отзывы и вопросы --------------------------------------------------------------------------
def _feedback_out(fb: Feedback) -> FeedbackOut:
    return FeedbackOut(
        id=fb.id,
        marketplace=fb.marketplace,
        kind=fb.kind,
        product_title=fb.product.title if fb.product else None,
        buyer_name=fb.buyer_name,
        rating=fb.rating,
        text=fb.text,
        created_at=fb.created_at,
        answer_text=fb.answer_text,
        answered_at=fb.answered_at,
        draft_text=fb.draft_text,
        draft_note=fb.draft_note,
    )


def _get_feedback(session: SessionDep, feedback_id: int) -> Feedback:
    fb = session.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "отзыв не найден")
    return fb


@router.get("/feedback", response_model=FeedbackList, tags=["feedback"])
def list_feedback(
    session: SessionDep,
    _: OperatorDep,
    kind: Annotated[str | None, Query(pattern="^(review|question)$")] = None,
    marketplace: MarketplaceCode | None = None,
    rating: Annotated[int | None, Query(ge=1, le=5)] = None,
    answered: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeedbackList:
    where = []
    if kind:
        where.append(Feedback.kind == kind)
    if marketplace:
        where.append(Feedback.marketplace == marketplace)
    if rating is not None:
        where.append(Feedback.rating == rating)
    if answered is True:
        where.append(Feedback.answer_text.is_not(None))
    elif answered is False:
        where.append(Feedback.answer_text.is_(None))
    items = (
        session.execute(
            select(Feedback)
            .where(*where)
            .order_by(Feedback.created_at.desc(), Feedback.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    total = session.execute(select(func.count()).select_from(Feedback).where(*where)).scalar_one()
    return FeedbackList(items=[_feedback_out(f) for f in items], total=total)


@router.post(
    "/feedback/{feedback_id}/answer",
    response_model=FeedbackOut,
    responses={**NOT_FOUND, 409: {"model": ErrorOut}, 502: {"model": ErrorOut}},
    tags=["feedback"],
)
def answer_feedback(feedback_id: int, body: ReplyIn, session: SessionDep, _: OperatorDep) -> FeedbackOut:
    fb = _get_feedback(session, feedback_id)
    try:
        fb = replies.answer_feedback(session, get_client(fb.marketplace), feedback_id, body.text)
    except replies.ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except replies.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return _feedback_out(fb)


@router.post("/feedback/{feedback_id}/ai-draft", response_model=DraftOut, responses=NOT_FOUND, tags=["feedback"])
def feedback_ai_draft(feedback_id: int, session: SessionDep, _: OperatorDep) -> DraftOut:
    text_, provider = replies.ai_draft_feedback(session, get_llm_provider(), _get_feedback(session, feedback_id))
    return DraftOut(text=text_, provider=provider)


@router.post(
    "/feedback/{feedback_id}/template-reply",
    response_model=TemplateReplyOut,
    responses={**NOT_FOUND, 409: {"model": ErrorOut}, 502: {"model": ErrorOut}},
    tags=["feedback"],
)
def feedback_template_reply(
    feedback_id: int, body: TemplateReplyIn, session: SessionDep, operator: OperatorDep
) -> TemplateReplyOut:
    fb = _get_feedback(session, feedback_id)
    tpl = _get_template(session, body.template_id)
    try:
        out = replies.template_reply_feedback(session, get_client(fb.marketplace), fb, tpl.body, operator)
    except replies.ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except replies.MarketplaceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return TemplateReplyOut(sent=out.sent, text=out.text, missing=out.missing, note=out.note)


# --- шаблоны --------------------------------------------------------------------------------------
def _template_out(t: ReplyTemplate) -> TemplateOut:
    return TemplateOut(id=t.id, name=t.name, body=t.body, variables=template_variables(t.body))


@router.get("/templates", response_model=list[TemplateOut], tags=["templates"])
def list_templates(session: SessionDep, _: OperatorDep) -> list[TemplateOut]:
    rows = session.execute(select(ReplyTemplate).order_by(ReplyTemplate.id)).scalars().all()
    return [_template_out(t) for t in rows]


@router.post(
    "/templates",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorOut}, 409: {"model": ErrorOut}},
    tags=["templates"],
)
def create_template(body: TemplateIn, session: SessionDep, _: OperatorDep) -> TemplateOut:
    unknown = [v for v in template_variables(body.body) if v not in KNOWN_VARIABLES]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "неизвестные переменные: " + ", ".join(unknown) + ". Доступны: " + ", ".join(KNOWN_VARIABLES),
        )
    tpl = ReplyTemplate(name=body.name, body=body.body)
    session.add(tpl)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "шаблон с таким названием уже есть") from exc
    return _template_out(tpl)


# --- синхронизация --------------------------------------------------------------------------------------
@router.post(
    "/sync",
    response_model=SyncJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"model": SyncJobOut, "description": "Задача уже в очереди или идёт — возвращается она же"}},
    tags=["sync"],
)
def start_sync(session: SessionDep, _: OperatorDep, background: BackgroundTasks, response: Response) -> SyncJobOut:
    """Ставит задачу синхронизации и сразу отвечает. Площадку не ждём — интерфейс читает из БД."""
    job, created = enqueue_sync(session)
    if created:
        background.add_task(run_sync_job, get_sessionmaker(), job.id, list(get_clients().values()))
    else:
        response.status_code = status.HTTP_200_OK
    return SyncJobOut.model_validate(job)


@router.get("/sync/latest", response_model=SyncJobOut | None, tags=["sync"])
def latest_sync(session: SessionDep, _: OperatorDep) -> SyncJobOut | None:
    job = session.execute(select(SyncJob).order_by(SyncJob.id.desc()).limit(1)).scalar_one_or_none()
    return SyncJobOut.model_validate(job) if job else None


@router.get("/sync/{job_id}", response_model=SyncJobOut, responses=NOT_FOUND, tags=["sync"])
def get_sync(job_id: int, session: SessionDep, _: OperatorDep) -> SyncJobOut:
    job = session.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "задача не найдена")
    return SyncJobOut.model_validate(job)
