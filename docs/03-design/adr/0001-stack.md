# ADR-0001. Стек: FastAPI + PostgreSQL + React

Статус: принято, 2026-10-20.

**Контекст.** Нужны REST API, БД с надёжными уникальными ограничениями и веб-интерфейс для
телефона. Код пишут агенты, стек должен ловить ошибки до запуска.

**Варианты.** FastAPI + PostgreSQL + React; Django REST Framework; NestJS + Prisma.

**Решение.** FastAPI + PostgreSQL, React + TypeScript strict. OpenAPI выгружается из кода и
сверяется тестом, mypy strict ловит ошибки сгенерированного кода. `ON CONFLICT` и `timestamptz`
нужны прямо в логике.

**Последствия.** Админку, как в Django, придётся писать самому. Сессии SQLAlchemy синхронные:
для демо хватает, при росте синхронизацию выносить в воркер.
