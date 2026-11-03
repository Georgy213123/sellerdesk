# 05. Тестирование

## Пирамида

```
            e2e (Playwright)            6 сценариев × 2 вьюпорта
        ─────────────────────────
     интеграционные (pytest + PostgreSQL)     47
   ─────────────────────────────────────
 unit (pytest без БД, Vitest + Testing Library)   33 + 14
```

Почему так:

- **Unit** — логика, где ошибка стоит дороже всего и проверяется без инфраструктуры:
  подстановка шаблонов, разбор времени площадок, заглушки, поведение формы ответа, вывод
  текста покупателя. Быстрые, их больше всего.
- **Интеграционные** — всё, что держится на PostgreSQL: `ON CONFLICT`, уникальные индексы,
  `timestamptz`, гонка двух транзакций, условный UPDATE. Моками БД эти баги не поймать, поэтому
  тесты идут на настоящей базе по `DATABASE_URL`, схема создаётся миграциями.
- **e2e** — сквозные сценарии из историй и то, что видно только в браузере: XSS, отсутствие
  горизонтальной прокрутки на 390 px, работа фильтров и статусов вместе.

## Что проверяет каждый слой

| Слой | Файлы | Что проверяет |
|---|---|---|
| unit, бэкенд | `backend/tests/unit/` | шаблоны (`test_templating.py`), время в UTC (`test_timestamps.py`), заглушка площадки, заглушка LLM, пароли и JWT, сверка `openapi.yaml` с кодом |
| интеграция | `backend/tests/integration/` | регрессии по ревью Codex (`test_review_findings.py`: потерянное подтверждение, перезапуск, гонка очереди, зависшая задача, контракт 400/422/200), синхронизация и идемпотентный upsert, очередь задач, лента и фильтры, ответ с ключом идемпотентности и гонка, черновики, шаблоны, отзывы, справочник шаблонов, сверка миграций с моделями, NFR-01 |
| unit, фронт | `frontend/src/__tests__/` | форма ответа (два submit до перерисовки, ключ при повторе и правке), карточка чата (поздний черновик, обновление после синхронизации, ключ шаблона, «Показать ещё»), кнопка «Обновить» при активной задаче, вывод текста отзыва без HTML, форматирование времени |
| e2e | `e2e/tests/` | US-01…US-06 и BUG-04 в браузере, вьюпорты 1440×900 и 390×844 |
| статика | `make lint` | ruff, mypy strict, eslint (в том числе запрет `dangerouslySetInnerHTML`), tsc strict, prettier |

## Матрица трассировки

| История | Требования | Тесты |
|---|---|---|
| US-01 Лента | FR-03, FR-04, NFR-01, NFR-07 | CR-10, `test_us01_feed_lists_all_marketplaces_newest_first`, `test_us01_filter_by_marketplace_and_status`, `test_bug02_*`, `test_nfr01_*`, `test_timestamps.py`; e2e «US-01…US-03» |
| US-02 Ответ в чате | FR-05, NFR-02 | `test_us02_chat_card`, `test_us02_reply_marks_answered_and_reaches_marketplace`, `test_reply_requires_idempotency_key`, `test_bug01_*`, `test_cr01_*`, `test_cr03_*`, `test_cr05_*`, `ReplyComposer.test.tsx`, CR-02, CR-05, CR-13; e2e «US-01…US-03» |
| US-03 AI-черновик | FR-07 | `test_us03_ai_draft_is_saved_not_sent`, `test_llm_stub.py`; e2e «US-01…US-03» |
| US-04 Отзывы | FR-06, NFR-03 | `test_feedback_api.py`, `UserText.test.tsx`; e2e «US-04», «BUG-04» |
| US-05 Шаблоны | FR-08, FR-11 | `test_templating.py`, `test_cr11_*`, CR-04, `test_us05_*`, `test_template_reply_without_buyer_name_becomes_draft`, `test_templates_api.py`; e2e «US-05» |
| US-06 Обновить | FR-02, FR-10 | `test_sync.py`, `test_cr06_*`, `test_cr07_*`, `test_cr12_*`, `test_r2_01_*`, `test_r2_02_*`, `test_r2_03_*`, CR-08, CR-09; e2e «US-06» |
| US-07 Вход | FR-09 | `test_requires_login`, `test_wrong_password`, `test_me`, `test_security.py`; вход в каждом e2e |
| — | FR-01, NFR-05 | `test_mock_marketplace.py`; весь набор идёт без сети и ключей |
| — | NFR-04 | e2e «NFR-04: лента читается без горизонтального скролла» на 390×844 |
| — | NFR-06, NFR-08 | `test_openapi_file_matches_code`, `test_models_match_migrations` |

## Как запустить

```bash
make test            # unit + интеграция бэкенда (нужен PostgreSQL по DATABASE_URL) + unit фронта
make e2e             # Playwright сам поднимет API и фронт с чистой демо-базой
```

Интеграционные тесты пересоздают схему и чистят таблицы. По умолчанию они идут в отдельную базу
`sellerdesk_test`; если `DATABASE_URL` задан в окружении (CI), используется он.

## Отчёт последнего прогона

Прогон 2026-11-03 после второго круга ревью Codex (v0.3.2), macOS, Python 3.12.15, Node 24.13.1, PostgreSQL 16.14, Chromium из Playwright 1.64.1.

| Набор | Тестов | Результат | Время |
|---|---|---|---|
| pytest, unit | 33 | 33 passed | — |
| pytest, интеграция | 47 | 47 passed | — |
| pytest, всего (`make test-backend`) | 80 | 80 passed | 11,3 с |
| Vitest (`make test-frontend`) | 14 в 4 файлах | 14 passed | ~4 с |
| Playwright (`make e2e`) | 12 (6 × 2 вьюпорта) | 12 passed | 18,0 с |

Покрытие бэкенда (`pytest --cov=app`): **93 %** строк (1019, из них 72 непокрытых). Меньше всего
покрыты `app/cli.py` (57 %, служебные команды запускаются руками и в e2e) и
`app/marketplaces/real.py` (71 %, каркасы без реализации).

Регрессионные тесты багов проверены откатом: при возврате кода до исправления каждый из
BUG-01…BUG-05 даёт красный тест. Тесты на находки ревью (CR-01…CR-13, BUG-06…BUG-10) написаны
до исправлений и падали на исходном коде; то же для второго круга (R2-01…R2-04), а тест
гонки CR-06 прогнан 20 раз с исправлением и 5 раз с откатом (см. [04-ai-development.md](04-ai-development.md),
[06-bugs.md](06-bugs.md)).
