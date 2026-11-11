"""Export the FastAPI OpenAPI schema for the typed web client (apps/web/src/lib/api is generated from it).

    uv run python -m scripts.export_openapi && (cd apps/web && npm run gen:api)
"""
from __future__ import annotations

import json
from pathlib import Path

from apps.api.main import app

OUT = Path(__file__).resolve().parents[1] / "apps" / "web" / "openapi.json"

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({len(app.openapi()['paths'])} paths)")
