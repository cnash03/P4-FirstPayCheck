"""Reference data: every value in the tax config has a source link and its tax year, and the
config covers federal rules, Colorado withholding, FAMLI and the Colorado cities with a local
wage tax, each city with its own source.

A value is a {value, source, tax_year} leaf, the shape engine/config.py unwraps. The planning
values are the team's rules of thumb, not tax rules: they cite the proposal instead of a link.
"""
import json
from pathlib import Path

import pytest

CONFIG = json.loads((Path(__file__).resolve().parents[2] / "config" / "tax_2026.json").read_text())
HEADER = {"_about", "schema_version", "tax_year"}
# Colorado cities with an occupational privilege tax in 2026; Aurora repealed its tax on Jan. 1, 2025.
CITIES = {"Denver", "Glendale", "Greenwood Village", "Sheridan"}


def leaves(node, path=""):
    """Yield (dotted path, leaf) for every {value, ...} leaf under node."""
    if isinstance(node, dict) and "value" in node:
        yield path, node
    elif isinstance(node, dict):
        for key, child in node.items():
            yield from leaves(child, f"{path}.{key}" if path else key)


LEAVES = list(leaves({k: v for k, v in CONFIG.items() if k not in HEADER}))


def is_link(source):
    return isinstance(source, str) and source.startswith("https://")


def test_config_has_values():
    assert len(LEAVES) >= 25


@pytest.mark.parametrize("path,leaf", LEAVES, ids=[p for p, _ in LEAVES])
def test_value_has_its_tax_year(path, leaf):
    assert leaf.get("tax_year") == CONFIG["tax_year"]


@pytest.mark.parametrize("path,leaf", LEAVES, ids=[p for p, _ in LEAVES])
def test_value_has_a_source_link(path, leaf):
    if path.startswith("planning."):
        assert leaf.get("source") and leaf.get("note", "").startswith("Rule of thumb")
    else:
        assert is_link(leaf.get("source")), leaf.get("source")


@pytest.mark.parametrize("section", ["federal", "colorado.withholding", "colorado.famli", "local"])
def test_covers_section(section):
    assert any(p == section or p.startswith(section + ".") for p, _ in LEAVES)


def test_covers_the_cities_with_a_local_tax():
    assert set(CONFIG["local"]["value"]) == CITIES


@pytest.mark.parametrize("city", sorted(CITIES))
def test_city_has_its_own_source_and_rule(city):
    rule = CONFIG["local"]["value"][city]
    assert is_link(rule.get("source"))
    assert rule["employee_monthly"] > 0 and rule["min_monthly_wages"] >= 0
