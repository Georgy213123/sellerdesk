"""Контракт первым: docs/03-design/openapi.yaml должен совпадать с тем, что отдаёт код."""

import yaml

from app.cli import OPENAPI_PATH
from app.main import create_app


def test_openapi_file_matches_code():
    assert OPENAPI_PATH.exists(), "нет openapi.yaml — выполните `make openapi`"
    on_disk = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert on_disk == create_app().openapi(), "контракт разошёлся с кодом — выполните `make openapi`"


def test_reply_requires_idempotency_key_in_contract():
    spec = create_app().openapi()
    params = spec["paths"]["/api/chats/{chat_id}/reply"]["post"]["parameters"]
    idem = next(p for p in params if p["name"] == "Idempotency-Key")
    assert idem["required"] is True
