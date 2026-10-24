"""Demo clock. today() = real today in Asia/Kolkata (or DEMO_BASE_DATE) + persisted offset_days.

Every date computation in the backend goes through this module, never datetime.now() directly.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import db
from .config import get_settings

IST = ZoneInfo("Asia/Kolkata")
_OFFSET_KEY = "demo_offset_days"


def real_now() -> datetime:
    now = datetime.now(IST)
    base = get_settings().demo_base_date
    if base:
        d = date.fromisoformat(base)
        return datetime.combine(d, time(now.hour, now.minute, now.second), tzinfo=IST)
    return now


def offset_days() -> int:
    return int(db.get_setting(_OFFSET_KEY, "0") or 0)


def now() -> datetime:
    return real_now() + timedelta(days=offset_days())


def today() -> date:
    return now().date()


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()


def real_now_iso() -> str:
    return real_now().replace(microsecond=0).isoformat()


def advance(days: int) -> None:
    db.set_setting(_OFFSET_KEY, str(offset_days() + int(days)))


def reset() -> None:
    db.set_setting(_OFFSET_KEY, "0")


def snapshot() -> dict:
    off = offset_days()
    n = now()
    return {"now": n.replace(microsecond=0).isoformat(), "today": n.date().isoformat(),
            "offset_days": off, "simulated": off != 0}


def parse_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)
