import json
from datetime import datetime
from functools import lru_cache

from . import CONFIG_PATH


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s)
