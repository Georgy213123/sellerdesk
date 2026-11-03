# Модель данных

```mermaid
erDiagram
    operators {
        int id PK
        string login UK
        string display_name
        string password_hash
    }
    products {
        string sku PK
        string title
        string category
    }
    chats {
        int id PK
        string marketplace "UK вместе с external_id"
        string external_id
        string buyer_name "nullable"
        string product_sku FK
        string order_number "nullable"
        string status "new | in_progress | answered"
        timestamptz last_message_at
        text draft_text "nullable"
        text draft_note "nullable"
        timestamptz synced_at
    }
    messages {
        int id PK
        int chat_id FK
        string external_id "UK с chat_id, nullable"
        string author "buyer | operator"
        text text
        timestamptz created_at
        string idempotency_key "UK с chat_id, nullable"
    }
    feedback {
        int id PK
        string marketplace "UK вместе с external_id"
        string external_id
        string kind "review | question"
        string product_sku FK
        string buyer_name "nullable"
        int rating "1..5, null у вопроса"
        text text
        timestamptz created_at
        text answer_text "nullable"
        timestamptz answered_at "nullable"
        text draft_text "nullable"
        text draft_note "nullable"
    }
    reply_templates {
        int id PK
        string name UK
        text body
    }
    sync_jobs {
        int id PK
        string status "queued | running | done | failed"
        timestamptz created_at
        timestamptz started_at
        timestamptz finished_at
        int chats_upserted
        int messages_inserted
        int feedback_upserted
        text error
    }

    products ||--o{ chats : "о товаре"
    products ||--o{ feedback : "о товаре"
    chats ||--|{ messages : "переписка"
```

## Словарь данных

| Таблица.поле | Смысл | Правило |
|---|---|---|
| `chats.marketplace` + `external_id` | чат на площадке | уникальная пара — ключ upsert синхронизации |
| `chats.status` | состояние в работе оператора | `new` → `in_progress` (черновик или шаблон с пропуском) → `answered` (ответ ушёл); новое сообщение покупателя после ответа возвращает `new` |
| `chats.last_message_at` | время последнего сообщения | `timestamptz`, UTC; по нему сортируется лента |
| `chats.draft_text`, `draft_note` | черновик и причина, почему он не отправлен | очищаются после отправки |
| `messages.external_id` | id сообщения на площадке | уникален в чате; у нашего ответа заполняется после отправки, поэтому следующая синхронизация не создаёт копию |
| `messages.idempotency_key` | ключ намерения ответить | уникален в чате; повтор запроса с ключом возвращает то же сообщение |
| `feedback.kind` | отзыв или вопрос | у вопроса `rating` пуст (CHECK 1..5) |
| `feedback.answer_text` | ответ продавца | ставится условным UPDATE `WHERE answer_text IS NULL`; при синхронизации не затирается |
| `reply_templates.body` | текст с `{{переменными}}` | переменные регистронезависимы; неизвестные отклоняются при создании |
| `sync_jobs.status` | состояние фоновой задачи | одновременно активна одна |

Все отметки времени — `timestamptz`; соединение с БД работает в зоне UTC, API отдаёт время
со смещением `+00:00`. Схема создаётся миграциями Alembic (`backend/migrations`), тест
`test_models_match_migrations` сверяет их с моделями.
