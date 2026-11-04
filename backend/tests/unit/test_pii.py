"""Маскирование ПД до отправки модели."""

import pytest

from app.llm.pii import mask_pii


@pytest.mark.parametrize(
    "phone",
    [
        "+7.900.111.22.33",
        "+375 (29) 123-45-67",
        "8 (900) 111 22 33",
        "+7-900-111-22-33",
        "8.900.111.22.33",
        "+7 900 111 22 33",
        "89001112233",
    ],
)
def test_phone_in_any_format_is_masked(phone):
    assert mask_pii(f"звоните {phone} срочно") == "звоните [телефон] срочно"


@pytest.mark.parametrize(
    "text",
    ["Куплено 2026-10-30 18:00", "Оценка 5 из 5", "Артикул NS-101, 12 Вт, 36 Вт", "Размер 120 x 45 см", "в 3 раза"],
)
def test_ordinary_numbers_are_kept(text):
    assert mask_pii(text) == text
