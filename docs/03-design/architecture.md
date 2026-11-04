# Архитектура (C4)

## Контекст

```mermaid
flowchart LR
    op["Оператор"] -- браузер --> sd["SellerDesk"]
    sd -- "чаты, отзывы, ответы" --> mp["Wildberries, Ozon, Яндекс Маркет"]
    sd -- черновик --> llm["LLM-провайдер"]
```

В демо площадки и LLM — заглушки внутри API.

## Контейнеры

```mermaid
flowchart LR
    fe["Frontend<br/>React + TypeScript"] -- "REST, JWT" --> api["API<br/>FastAPI"]
    api --> db[("PostgreSQL")]
    api -- ставит задачу --> job["Фоновая синхронизация"]
    job -- upsert --> db
    job -- выгрузка --> mp["Площадки"]
    api -- ответ --> mp
    api -- черновик --> llm["LLM"]
```

Интерфейс читает только БД, задержка площадки на него не влияет.

Решения: [ADR-0001 стек](adr/0001-stack.md) · [ADR-0002 синхронизация](adr/0002-marketplace-sync.md) ·
[ADR-0003 идемпотентность](adr/0003-idempotent-replies.md)
