"""Маскирование персональных данных до отправки текста модели."""

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Любая последовательность цифр с пробелами, точками, дефисами и скобками; телефоном считается от 10 цифр.
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\s().\-]{8,}\d(?![\w])")
_PHONE_DIGITS = 10
# Дата в начале совпадения (разделители у даты и телефона общие) не делает телефон «не телефоном».
_LEADING_DATE = re.compile(r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{2,4})\s*")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")


def _mask_phone(match: re.Match[str]) -> str:
    found, head = match.group(), ""
    while date := _LEADING_DATE.match(found):
        head, found = head + date.group(), found[date.end() :]
    is_phone = sum(c.isdigit() for c in found) >= _PHONE_DIGITS
    return head + ("[телефон]" if is_phone else found)


def mask_pii(text: str) -> str:
    """Заменяет e-mail, телефоны и длинные номера (заказы) до отправки модели."""
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub(_mask_phone, text)
    return _LONG_NUMBER.sub("[номер]", text)
