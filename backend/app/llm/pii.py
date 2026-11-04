"""Маскирование персональных данных до отправки текста модели."""

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Любая последовательность цифр с пробелами, точками, дефисами и скобками; телефоном считается от 10 цифр.
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\s().\-]{8,}\d(?![\w])")
_PHONE_DIGITS = 10
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")


def _mask_phone(match: re.Match[str]) -> str:
    found = match.group()
    is_phone = sum(c.isdigit() for c in found) >= _PHONE_DIGITS and not _ISO_DATE.match(found)
    return "[телефон]" if is_phone else found


def mask_pii(text: str) -> str:
    """Заменяет e-mail, телефоны и длинные номера (заказы) до отправки модели."""
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub(_mask_phone, text)
    return _LONG_NUMBER.sub("[номер]", text)
