"""auction_pipeline — config loader."""
from __future__ import annotations

import logging
import logging.config
import os
from functools import lru_cache
from pathlib import Path

import yaml

_ROOT = Path(__file__).parent.parent  # repo root
_CONFIG_PATH = _ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(_CONFIG_PATH, "r") as fh:
        return yaml.safe_load(fh)


def get_county_config(county: str = "williamson") -> dict:
    cfg = load_config()
    return cfg["counties"][county]


def get_amortization_config() -> dict:
    return load_config()["amortization"]


def get_interest_rate(origination_month: str) -> float:
    """
    Return the assumed annual interest rate for a given origination month.

    Priority:
        1. month_overrides[YYYY-MM]
        2. interest_rates[YYYY]
        3. fallback 0.065
    """
    cfg = load_config()
    rates = cfg.get("interest_rates", {})
    overrides = rates.get("month_overrides", {})

    year = origination_month[:4]
    if origination_month in overrides:
        return float(overrides[origination_month])
    if year in rates:
        return float(rates[year])
    return 0.065  # reasonable fallback


def setup_logging() -> None:
    cfg = load_config().get("logging", {})
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    fmt = cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.basicConfig(level=level, format=fmt)


def workspace_path(*parts: str) -> Path:
    """Return an absolute path inside workspace/, creating parents as needed."""
    root = _ROOT / "workspace"
    p = root.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
