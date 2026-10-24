"""All API routes register on this shared Api instance (see app/web.py)."""
from ..web import Api

api = Api()


def load_all() -> Api:
    from . import cases, debug, demo, events, health, rules, runs, sandbox, steps  # noqa: F401
    return api
