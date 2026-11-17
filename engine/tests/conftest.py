"""Shared inputs for the engine tests.

Until the quiz fields are final, the tests use three hard-coded profiles: the eval set's
default and Tyler profiles (eval/profiles/) and a third, married family on the HDHP, that
exercises the other branches. Document fields come from samples/answers/*.json, the hand-
written stand-in for extracted fields.
"""
import json
from pathlib import Path

import pytest

from engine.config import load_config

ROOT = Path(__file__).resolve().parents[2]

MARRIED_HDHP_FAMILY = {
    "filing_status": "married_filing_jointly",
    "city": "Denver",
    "coverage": "family",
    "emergency_fund_months": 0,
    "annual_salary": 120000,
    "pay_frequency": "biweekly",
    "state": "CO",
    "health_plan": "HDHP with HSA",
    "retirement_401k_percent": 4,
    "retirement_401k_type": "traditional",
    "espp_percent": 5,
    "savings_goal_per_check": 1000,
    "age": 56,
}


def _profile(name):
    data = json.loads((ROOT / "eval" / "profiles" / f"{name}.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.fixture(scope="session")
def config():
    return load_config(ROOT / "config" / "tax_2026.json")


@pytest.fixture(scope="session")
def profiles():
    return {"default": _profile("default"), "tyler": _profile("tyler"), "married_hdhp_family": MARRIED_HDHP_FAMILY}


@pytest.fixture(scope="session")
def fields():
    """Every sample document field by id, e.g. fields['offer_letter.pdf:offer.annual_salary']."""
    out = {}
    for path in sorted((ROOT / "samples" / "answers").glob("*.json")):
        for field in json.loads(path.read_text())["fields"]:
            out[field["id"]] = field["value"]
    return out
