"""Generate synthetic data from the host machine (outside Docker).

    python scripts/generate_data.py --load --wipe

Same options as `python -m app.datagen` (inside the backend container), but
defaults to the host's Neo4j port and writes to <repo>/data/.
Needs the backend's Python dependencies (see README, Testing).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.datagen.__main__ import main  # noqa: E402

if __name__ == "__main__":
    # Later arguments win, so anything the user passes overrides these defaults.
    main(["--out", str(ROOT / "data"), "--neo4j-uri", "bolt://localhost:7687", *sys.argv[1:]])
