from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MarketplaceCode = Literal["wildberries", "ozon", "yandex_market"]
ChatStatusCode = Literal["new", "in_progress", "answered"]


class ErrorOut(BaseModel):
    detail: str


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login: str
    display_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    operator: OperatorOut


class ChatListItem(BaseModel):
    id: int
    marketplace: MarketplaceCode
    buyer_name: str | None
    product_title: str | None
    order_number: str | None
    status: ChatStatusCode
    last_message_at: datetime
    last_message_preview: str


class ChatList(BaseModel):
    items: list[ChatListItem]
    total: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    author: Literal["buyer", "operator"]
    text: str
    created_at: datetime


class ChatOut(BaseModel):
    id: int
    marketplace: MarketplaceCode
    external_id: str
    buyer_name: str | None
    product_sku: str | None
    product_title: str | None
    order_number: str | None
    status: ChatStatusCode
    last_message_at: datetime
    draft_text: str | None
    draft_note: str | None
    messages: list[MessageOut]


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ReplyOut(BaseModel):
    message: MessageOut
    duplicate: bool = Field(description="true — запрос с этим Idempotency-Key уже был, повторно не отправлено")


class DraftOut(BaseModel):
    text: str
    provider: str
    note: str = "Черновик не отправлен. Проверьте и отправьте сами."


class TemplateReplyIn(BaseModel):
    template_id: int


class TemplateReplyOut(BaseModel):
    sent: bool
    text: str
    missing: list[str]
    note: str | None


class FeedbackOut(BaseModel):
    id: int
    marketplace: MarketplaceCode
    kind: Literal["review", "question"]
    product_title: str | None
    buyer_name: str | None
    rating: int | None
    text: str
    created_at: datetime
    answer_text: str | None
    answered_at: datetime | None
    draft_text: str | None
    draft_note: str | None


class FeedbackList(BaseModel):
    items: list[FeedbackOut]
    total: int


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1, max_length=2000)


class TemplateOut(BaseModel):
    id: int
    name: str
    body: str
    variables: list[str]


class SyncJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: Literal["queued", "running", "done", "failed"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    chats_upserted: int
    messages_inserted: int
    feedback_upserted: int
    error: str | None


class HealthOut(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
