# 05. Тестирование

```
        e2e Playwright: 7 сценариев × 2 вьюпорта
     интеграция pytest + PostgreSQL: 101
  unit: pytest 95, Vitest 30
```

- **unit, бэкенд:** подстановка шаблонов, время в UTC, заглушки, провайдер Claude API на фейковом клиенте (без сети), JWT, сверка `openapi.yaml` с кодом.
- **интеграция:** то, что держится на PostgreSQL — `ON CONFLICT`, индексы, гонки транзакций, миграции. Моками БД это не поймать.
- **unit, фронт:** форма ответа и ключ, поздний черновик, «Обновить», текст отзыва без HTML.
- **e2e:** истории в браузере, XSS, 390 px без горизонтальной прокрутки.

## Трассировка

| История | Тесты |
|---|---|
| US-01 Лента | `test_us01_*`, `test_bug02_*`, `test_nfr01_*`, Vitest CR-10, e2e US-01…US-03 |
| US-02 Ответ | `test_bug01_*`, `test_cr01/03/05_*`, `ReplyComposer.test.tsx`, Vitest CR-13, e2e US-01…US-03 |
| US-03 Черновик | `test_us03_ai_draft_is_saved_not_sent`, Vitest CR-02, BUG-11 |
| US-04 Отзывы | `test_feedback_api.py`, `UserText.test.tsx`, e2e US-04, BUG-04 |
| US-05 Шаблоны | `test_templating.py`, `test_templates_api.py`, `test_cr11_*`, Vitest CR-04, e2e US-05 |
| US-06 Обновить | `test_sync.py`, `test_cr06/07_*`, `test_r2_*`, Vitest CR-08, CR-09, e2e US-06 |
| US-07 Агент (FR-12, FR-13) | `test_agent.py`, `test_agent_insights.py`, `test_pii.py`, `test_compose.py`, `agent-page.test.tsx`, e2e агента |
| FR-09, NFR-04, NFR-05 | `test_security.py`, e2e NFR-04, `test_openapi_*`, `test_models_match_*` |

## Прогон 2026-11-04 (v0.5.0)

macOS, Python 3.12, Node 24, PostgreSQL 16, Playwright 1.64.

| Набор | Результат | Время |
|---|---|---|
| pytest (`make test-backend`) | 196 passed | 24,2 с |
| Vitest | 30 passed | ~2 с |
| Playwright | 14 passed | 22,8 с |

Покрытие бэкенда 94 %; ниже всего `app/cli.py` (56 %) и каркасы адаптеров (71 %).
Тесты багов и находок ревью падали до исправления.
