"""Защита рабочей базы: интеграционные тесты делают DROP SCHEMA, поэтому работают только с базой `*_test`."""

from app.db_guard import NotATestDatabaseError, require_disposable_database

__all__ = ["NotATestDatabaseError", "require_test_database"]


def require_test_database(url: str) -> str:
    return require_disposable_database(url, ("_test",))
