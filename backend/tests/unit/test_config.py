from typing import Any

import pytest
from pydantic import ValidationError

from app.config import DEMO_JWT_SECRET, Settings


def make(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def test_dev_allows_demo_secret():
    assert make().jwt_secret == DEMO_JWT_SECRET


def test_production_rejects_demo_secret():
    with pytest.raises(ValidationError):
        make(app_env="production")


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError):
        make(app_env="production", jwt_secret="x" * 31)


def test_production_accepts_long_secret():
    assert make(app_env="production", jwt_secret="x" * 32).app_env == "production"
