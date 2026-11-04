"""Защита рабочей базы: команды и тесты, которые делают DROP SCHEMA, работают только с одноразовой базой."""

from sqlalchemy.engine import make_url


class NotATestDatabaseError(RuntimeError):
    pass


def require_disposable_database(url: str, suffixes: tuple[str, ...] = ("_test",)) -> str:
    name = make_url(url).database or ""
    if not name.endswith(suffixes):
        allowed = " или ".join(suffixes)
        raise NotATestDatabaseError(
            f"Отказ: база «{name}» не одноразовая. Схема пересоздаётся, имя базы должно оканчиваться на {allowed}."
        )
    return url
