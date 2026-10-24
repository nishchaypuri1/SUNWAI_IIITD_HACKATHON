from .. import schemas
from ..llm.gateway import gateway
from . import api


@api.route("GET", "/api/debug/llm-stats", summary="LLM gateway statistics (E26)", tag="system",
           response=schemas.LlmStats)
async def llm_stats() -> schemas.LlmStats:
    return schemas.LlmStats(**gateway().stats_snapshot())
