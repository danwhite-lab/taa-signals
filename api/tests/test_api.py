"""API-only tests: run with the isolated API development requirements installed."""
from dataclasses import fields
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("taa_api", ROOT / "api" / "index.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = TestClient(module.app)


def test_catalogue_is_exact_live_engine_metadata():
    from haa.model_catalog import MODEL_CATALOG

    response = client.get("/api/strategies")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    expected = [
        {f.name: getattr(item, f.name) for f in fields(item) if f.name != "model_class"}
        for item in MODEL_CATALOG
    ]
    assert response.json() == expected
    assert expected and any(item["execution_currency"] == "ILS" for item in expected)
    assert all("model_class" not in item for item in response.json())


def test_only_read_only_catalogue_endpoint_is_exposed():
    assert [route.path for route in module.app.routes] == ["/api/strategies"]
    assert client.post("/api/strategies", json={}).status_code == 405
    assert client.get("/api/holdings").status_code == 404
    assert client.get("/api/not-a-route").status_code == 404


def test_entrypoint_imports_src_without_pythonpath_or_repository_working_directory(tmp_path):
    code = """
import importlib.util, json, sys
from fastapi.testclient import TestClient
spec = importlib.util.spec_from_file_location('taa_api', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
response = TestClient(module.app).get('/api/strategies')
assert response.status_code == 200
assert 'streamlit' not in sys.modules
print(json.dumps(response.json()))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT / "api" / "index.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=True,
    )
    assert json.loads(result.stdout) == client.get("/api/strategies").json()


def test_vercel_keeps_frontend_and_python_under_one_repository_root():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["framework"] is None
    assert config["installCommand"] == "npm --prefix web ci"
    assert config["buildCommand"] == "npm --prefix web run build"
    assert config["outputDirectory"] == "web/out"
    assert config["rewrites"] == [{"source": "/api/:path*", "destination": "/api/index.py"}]
    assert config["functions"]["api/index.py"]["includeFiles"] == "src/haa/**"
    assert (ROOT / "web" / "app" / "page.tsx").is_file()
    assert "/requirements.txt" in (ROOT / ".vercelignore").read_text().splitlines()
    assert "/pyproject.toml" in (ROOT / ".vercelignore").read_text().splitlines()
