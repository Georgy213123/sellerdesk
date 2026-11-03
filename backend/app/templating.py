"""Подстановка переменных в шаблоны автоответов.

Правило безопасности: если хотя бы одна переменная не подставилась, ответ покупателю не уходит,
а сохраняется черновиком с причиной.

Имена переменных регистронезависимы и допускают пробелы внутри скобок: `{{ Buyer_Name }}`
и `{{buyer_name}}` — одна переменная. Раньше регулярка искала только `{{[a-z_]+}}`:
`{{Buyer_Name}}` не считался переменной, не попадал в список неподставленных
и уходил покупателю буквально (BUG-05). Поэтому после подстановки текст ещё раз
проверяется на любые остатки `{{` и `}}`.
"""

import re
from dataclasses import dataclass, field

VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

KNOWN_VARIABLES = ("buyer_name", "product", "order_number", "marketplace", "operator_name")


@dataclass(frozen=True)
class RenderResult:
    text: str
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def render_template(body: str, context: dict[str, str | None]) -> RenderResult:
    values = {k.lower(): v for k, v in context.items() if v not in (None, "")}
    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        value = values.get(name)
        if value is None:
            if name not in missing:
                missing.append(name)
            return match.group(0)
        return value

    text = VAR_RE.sub(substitute, body)
    if not missing and ("{{" in text or "}}" in text):
        # Сломанная разметка вроде `{{buyer name}}` или `{{product}` — тоже не отправляем.
        missing.append("<некорректная разметка>")
    return RenderResult(text=text, missing=missing)


def template_variables(body: str) -> list[str]:
    seen: list[str] = []
    for m in VAR_RE.finditer(body):
        name = m.group(1).lower()
        if name not in seen:
            seen.append(name)
    return seen
