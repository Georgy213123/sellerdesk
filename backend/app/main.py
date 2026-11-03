from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="SellerDesk API",
        version="0.3.2",
        description=(
            "Рабочее место оператора продавца на маркетплейсах: единая лента чатов, отзывы и вопросы, "
            "AI-черновики и шаблоны ответов. Демо: площадки и LLM — заглушки."
        ),
    )
    origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.include_router(router)
    return app


app = create_app()
