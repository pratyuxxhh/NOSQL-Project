"""Host-machine wrapper for `python -m app.benchmark` (which also runs inside the backend container:
`docker compose exec backend python -m app.benchmark`). Needs the backend's Python dependencies."""

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# From the host, Neo4j and PostgreSQL are on localhost and data/ is at the repo root.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("DATA_DIR", str(ROOT / "data"))
sys.argv = [sys.argv[0], *sys.argv[1:]]
runpy.run_module("app.benchmark", run_name="__main__")
