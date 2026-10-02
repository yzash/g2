import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdal import DB_PATH, RAW_DIR  # noqa: E402
from sdal.curated import build_curated, connect  # noqa: E402
from sdal.engine import Engine  # noqa: E402
from sdal.generator import generate  # noqa: E402


@pytest.fixture(scope="session")
def generated():
    if not (RAW_DIR / "_generator_truth.json").exists():
        generate()
    if not DB_PATH.exists():
        build_curated().close()
    return RAW_DIR


@pytest.fixture(scope="session")
def engine(generated):
    return Engine(con=connect()).run()


@pytest.fixture()
def db_copy(generated, tmp_path):
    """A private copy of the curated layer a test may modify."""
    p = tmp_path / "curated.duckdb"
    shutil.copy(DB_PATH, p)
    return p
