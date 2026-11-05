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
    agent_runs ||--o{ agent_events : ""
    agent_runs ||--o{ agent_proposals : ""
    operators |o--o{ agent_proposals : "decided_by"
    agent_runs {
        string kind
        string status
        timestamptz period_from
        timestamptz period_to
        jsonb checkpoint
        int tokens_used
        int token_budget
        int steps_done
        int max_steps
        timestamptz lease_until
        timestamptz heartbeat_at
    }
    agent_events {
        int run_id
        int step
        string kind
        text message
        int tokens
    }
    agent_proposals {
        int run_id
        string theme_key
        string kind
        text body
        jsonb evidence
        string status
        int decided_by
    }
    sync_jobs {
        string status
        timestamptz created_at
        text error
    }
```

Ещё таблица без связей: `reply_templates`. `operators` связана только с решениями по предложениям агента.

- `chats`, `feedback`: (marketplace, external_id) — уникальная пара, ключ upsert синхронизации.
- `chats.status` — `new` → `in_progress` → `answered`.
- `messages.external_id` — у нашего ответа пишется после отправки, синхронизация не делает копию.
- `messages.idempotency_key` — уникален в чате, повтор возвращает то же сообщение.
- `feedback.answer_text` — ставится условным UPDATE `WHERE answer_text IS NULL`.
- `sync_jobs.status` — одна активная задача, частичный уникальный индекс.
- `agent_runs.status` — `queued` → `running` → `succeeded` / `failed` / `budget_exhausted`; один активный прогон на вид (`kind`), частичный уникальный индекс.
- `agent_runs.checkpoint` — стадия, курсор и резерв токенов; `lease_until` и `heartbeat_at` — аренда, по ней брошенный прогон подбирает следующий запуск.
- `agent_events.kind` — `step_started`, `step_done`, `llm_call`, `budget_stop`, `stage_cut`, `error`, `resumed`.
- `agent_proposals`: (run_id, theme_key, kind) — уникальная тройка, повтор шага не дублирует предложение; `kind` — `reply_template` или `card_edit`, `status` — `pending` → `approved` / `rejected`.

Время везде `timestamptz`, API отдаёт UTC.
