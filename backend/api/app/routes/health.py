from .. import schemas
from ..config import VERSION, get_settings
from ..llm.gateway import gateway
from ..tinyfish.client import tinyfish
from . import api


@api.route("GET", "/api/health", summary="Health and configuration (E1)", tag="system", response=schemas.Health)
async def health() -> schemas.Health:
    s = get_settings()
    if not s.tinyfish_api_key:
        tf = "missing_key"
    elif tinyfish().last_error_code in ("INVALID_API_KEY", "UNAUTHORIZED", "MISSING_API_KEY"):
        tf = "error"
    else:
        tf = "ok"
    return schemas.Health(ok=True, mock_mode=s.mock_mode, version=VERSION, tinyfish=tf,
                          models=gateway().health_models())
