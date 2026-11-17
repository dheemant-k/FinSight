"""Pytest configuration and environment fixtures for FinSight test suites."""

import sys
from pathlib import Path

# Ensure src/ is on sys.path for test discovery and module imports
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DATASET = PROJECT_ROOT / "data" / "processed" / "transactions.csv.gz"

# Tests that read the full processed PaySim dataset. The dataset (~470 MB raw) is not
# committed; run `python src/finsight/pipeline.py` after downloading it to enable them.
requires_processed_data = pytest.mark.skipif(
    not PROCESSED_DATASET.exists(),
    reason="needs data/processed/transactions.csv.gz (run src/finsight/pipeline.py first)",
)
