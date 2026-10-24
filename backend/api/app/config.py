"""Settings. Reads environment variables, falling back to a `.env` file in api/ or the repo root.

Every value can be overridden by an env var with the same name in upper case.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

API_DIR = Path(__file__).resolve().parent.parent          # .../api
REPO_DIR = API_DIR.parent                                  # repo root
DATA_DIR = API_DIR / "data"
VERSION = "1.0.0"


def _read_dotenv() -> dict[str, str]:
    """Tiny .env parser (KEY=VALUE, # comments, optional quotes). api/.env wins over root .env."""
    out: dict[str, str] = {}
    for path in (REPO_DIR / ".env", API_DIR / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if value and value[0] in "\"'" and value[-1:] == value[0]:
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].strip()
            out[key.strip()] = value
    return out


def _bool(v: str | None, default: bool) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


class ProviderConfig(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str
    max_concurrency: int = 4
    rps: float = 3.0
    vision: bool = False


class Settings(BaseModel):
    mock_mode: bool = True
    record_fixtures: bool = False
    database_url: str = "sqlite:///./sunwai.db"
    cors_origins: list[str] = ["http://localhost:3000"]
    sandbox_public_url: str = "http://localhost:3000"
    demo_base_date: str | None = None          # YYYY-MM-DD: pin "real today" (rehearsals, tests)
    mock_delay_scale: float = 1.0               # 0 = replay mock agent runs instantly
    scheduler_enabled: bool = True
    startup_rule_refresh: bool = True
    rate_limit_per_min: int = 120
    rule_ttl_hours: int = 24
    log_level: str = "INFO"
    eval_dir: str = str(REPO_DIR / "eval")

    # TinyFish
    tinyfish_api_key: str = ""
    tinyfish_agent_base: str = "https://agent.tinyfish.ai"
    tinyfish_search_url: str = "https://api.search.tinyfish.ai"
    tinyfish_fetch_url: str = "https://api.fetch.tinyfish.ai"
    tinyfish_search_location: str = "IN"
    tinyfish_proxy_country: str = ""            # e.g. "IN" to route live portal runs via an Indian exit
    tinyfish_browser_profile: str = "lite"

    # LLM providers (OpenAI-compatible) and role chains
    providers: dict[str, ProviderConfig] = {}
    role_intake: list[str] = ["glm", "deepseek"]
    role_reason: list[str] = ["deepseek", "glm"]
    role_fast: list[str] = ["nemotron", "glm"]

    @property
    def sqlite_path(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///"):
            p = url[len("sqlite:///"):]
            if p == ":memory:":
                return p
            path = Path(p)
            if not path.is_absolute():
                path = (API_DIR / path).resolve()
            return str(path)
        raise RuntimeError(
            f"DATABASE_URL={url!r} is not supported. This backend uses SQLite (sqlite:///path.db)."
        )


def _split(v: str | None, default: list[str]) -> list[str]:
    if not v:
        return default
    return [x.strip() for x in v.split(",") if x.strip()]


def load_settings() -> Settings:
    env = {**_read_dotenv(), **os.environ}
    g = env.get

    providers: dict[str, ProviderConfig] = {}
    defaults = {
        "deepseek": "deepseek/deepseek-v4-flash",
        "glm": "z-ai/glm-5.3-flash",
        "nemotron": "nvidia/nemotron-3.5-lightning",
    }
    for name, default_model in defaults.items():
        up = name.upper()
        providers[name] = ProviderConfig(
            name=name,
            base_url=(g(f"{up}_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/"),
            api_key=g(f"{up}_API_KEY") or g("OPENROUTER_API_KEY") or "",
            model=g(f"{up}_MODEL") or default_model,
            max_concurrency=int(g(f"{up}_MAX_CONCURRENCY") or 4),
            rps=float(g(f"{up}_RPS") or 3),
            vision=_bool(g(f"{up}_VISION"), False),
        )

    return Settings(
        mock_mode=_bool(g("MOCK_MODE"), True),
        record_fixtures=_bool(g("RECORD_FIXTURES"), False),
        database_url=g("DATABASE_URL") or "sqlite:///./sunwai.db",
        cors_origins=_split(g("CORS_ORIGINS"), ["http://localhost:3000"]),
        sandbox_public_url=(g("SANDBOX_PUBLIC_URL") or "http://localhost:3000").rstrip("/"),
        demo_base_date=g("DEMO_BASE_DATE") or None,
        mock_delay_scale=float(g("MOCK_DELAY_SCALE") or 1.0),
        scheduler_enabled=_bool(g("SCHEDULER_ENABLED"), True),
        startup_rule_refresh=_bool(g("STARTUP_RULE_REFRESH"), True),
        rate_limit_per_min=int(g("RATE_LIMIT_PER_MIN") or 120),
        rule_ttl_hours=int(g("RULE_TTL_HOURS") or 24),
        log_level=g("LOG_LEVEL") or "INFO",
        eval_dir=g("EVAL_DIR") or str(REPO_DIR / "eval"),
        tinyfish_api_key=g("TINYFISH_API_KEY") or "",
        tinyfish_agent_base=(g("TINYFISH_AGENT_BASE") or "https://agent.tinyfish.ai").rstrip("/"),
        tinyfish_search_url=g("TINYFISH_SEARCH_URL") or "https://api.search.tinyfish.ai",
        tinyfish_fetch_url=g("TINYFISH_FETCH_URL") or "https://api.fetch.tinyfish.ai",
        tinyfish_search_location=g("TINYFISH_SEARCH_LOCATION") or "IN",
        tinyfish_proxy_country=g("TINYFISH_PROXY_COUNTRY") or "",
        tinyfish_browser_profile=g("TINYFISH_BROWSER_PROFILE") or "lite",
        providers=providers,
        role_intake=_split(g("ROLE_INTAKE"), ["glm", "deepseek"]),
        role_reason=_split(g("ROLE_REASON"), ["deepseek", "glm"]),
        role_fast=_split(g("ROLE_FAST"), ["nemotron", "glm"]),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
