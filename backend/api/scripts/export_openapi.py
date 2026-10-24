"""Write the OpenAPI document to ../contracts/openapi.json (for openapi-typescript on the frontend)."""
import json
import os
import sys
from pathlib import Path

API = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API))
os.environ.setdefault("MOCK_MODE", "1")

from app.config import VERSION  # noqa: E402
from app.main import api  # noqa: E402

out = API.parent / "contracts" / "openapi.json"
out.write_text(json.dumps(api.openapi("Sunwai API", VERSION), indent=2, ensure_ascii=False))
print(f"wrote {out}")
