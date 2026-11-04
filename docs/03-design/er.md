# Модель данных

```mermaid
erDiagram
    products ||--o{ chats : ""
    products ||--o{ feedback : ""
    chats ||--|{ messages : ""
    chats {
        string marketplace
        string external_id
        string status
        timestamptz last_message_at
        text draft_text
    }
    messages {
        int chat_id
        string external_id
        string idempotency_key
        text text
    }
    feedback {
        string marketplace
        string external_id
        string kind
        int rating
        text answer_text
    }
    sync_jobs {
        string status
        timestamptz created_at
        text error
    }
```

Ещё две таблицы без связей: `operators` и `reply_templates`.

- `chats`, `feedback`: (marketplace, external_id) — уникальная пара, ключ upsert синхронизации.
- `chats.status` — `new` → `in_progress` → `answered`.
- `messages.external_id` — у нашего ответа пишется после отправки, синхронизация не делает копию.
- `messages.idempotency_key` — уникален в чате, повтор возвращает то же сообщение.
- `feedback.answer_text` — ставится условным UPDATE `WHERE answer_text IS NULL`.
- `sync_jobs.status` — одна активная задача, частичный уникальный индекс.

Время везде `timestamptz`, API отдаёт UTC.
