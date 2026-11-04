"""Защита рабочей базы: интеграционные тесты делают DROP SCHEMA, поэтому работают только с базой `*_test`."""

from sqlalchemy.engine import make_url


class NotATestDatabaseError(RuntimeError):
    pass


def require_test_database(url: str) -> str:
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        raise NotATestDatabaseError(
            f"Отказ: база «{name}» не тестовая. Тесты пересоздают схему, имя базы должно оканчиваться на _test. "
            "Задайте TEST_DATABASE_URL."
        )
    return url
