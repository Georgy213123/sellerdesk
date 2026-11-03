"""FR-07 / US-05: шаблоны автоответов и правило «не подставилось — не отправляем»."""

from app.templating import render_template, template_variables

CTX = {"buyer_name": "Анна", "product": "Торшер «Дуга»", "order_number": None}


def test_all_variables_substituted():
    r = render_template("{{buyer_name}}, спасибо за покупку {{product}}", CTX)
    assert r.ok
    assert r.text == "Анна, спасибо за покупку Торшер «Дуга»"


def test_missing_value_is_reported_and_left_in_text():
    r = render_template("Заказ {{order_number}} в пути", CTX)
    assert not r.ok
    assert r.missing == ["order_number"]
    assert "{{order_number}}" in r.text


def test_unknown_variable_is_missing():
    r = render_template("Привет, {{nickname}}", CTX)
    assert r.missing == ["nickname"]


def test_bug05_variable_in_other_case_is_substituted():
    """BUG-05: `{{Buyer_Name}}` раньше не считался переменной и уходил покупателю буквально."""
    r = render_template("{{Buyer_Name}}, {{ PRODUCT }} уже в пути", CTX)
    assert r.ok, r.missing
    assert r.text == "Анна, Торшер «Дуга» уже в пути"


def test_bug05_missing_variable_in_other_case_blocks_sending():
    r = render_template("Заказ {{Order_Number}} передан", CTX)
    assert not r.ok
    assert r.missing == ["order_number"]


def test_broken_markup_blocks_sending():
    r = render_template("Здравствуйте, {{buyer name}}!", CTX)
    assert not r.ok
    assert r.missing == ["<некорректная разметка>"]


def test_empty_string_value_counts_as_missing():
    r = render_template("{{buyer_name}}, привет", {"buyer_name": ""})
    assert r.missing == ["buyer_name"]


def test_template_variables_are_normalized_and_unique():
    assert template_variables("{{A}} {{a}} {{ b_1 }}") == ["a", "b_1"]
