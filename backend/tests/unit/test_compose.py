"""docker-compose передаёт в контейнер API настройки LLM и агента: README обещает их задавать в .env."""

from pathlib import Path

import yaml

from app.config import Settings

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _backend_env() -> dict[str, str]:
    env: dict[str, str] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["backend"]["environment"]
    return env


def test_compose_passes_llm_and_agent_settings():
    env = {k.lower() for k in _backend_env()}
    wanted = {name for name in Settings.model_fields if name.startswith(("agent_", "llm_"))}
    assert wanted <= env, sorted(wanted - env)
    assert "anthropic_api_key" in env


def test_compose_has_no_default_api_key():
    key = _backend_env()["ANTHROPIC_API_KEY"]
    assert key.replace(" ", "") == "${ANTHROPIC_API_KEY:-}"
