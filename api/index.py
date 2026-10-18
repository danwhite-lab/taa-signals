"""Read-only Vercel ASGI entrypoint; the existing engine remains authoritative."""
from dataclasses import fields
from pathlib import Path
import sys

from fastapi import FastAPI


SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from haa.model_catalog import MODEL_CATALOG  # noqa: E402


app = FastAPI(
    title="TAA Signals API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/api/strategies")
def strategies() -> list[dict]:
    """Expose catalogue metadata, not executable Python class objects."""
    return [
        {
            field.name: getattr(model, field.name)
            for field in fields(model)
            if field.name != "model_class"
        }
        for model in MODEL_CATALOG
    ]
