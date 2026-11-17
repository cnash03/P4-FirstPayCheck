"""Read tax-year rates and limits from the config file.

Every rate and limit a calculator uses comes through TaxConfig.get(), never from a number
in the code. The file format is a draft (see config/tax_2026.json); if the final format from
Documents and retrieval differs, this module is the only one that changes.

The config path is, in order: the `path` argument, the FIRSTPAYCHECK_TAX_CONFIG environment
variable, then config/tax_2026.json.
"""
import copy
import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "tax_2026.json"
ENV_VAR = "FIRSTPAYCHECK_TAX_CONFIG"


class TaxConfig:
    """A loaded config. get("a.b.c") returns the value at that dotted path."""

    def __init__(self, data, path=None):
        self.data = data
        self.path = path
        self.tax_year = data.get("tax_year")

    def _node(self, key):
        node = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"tax config has no '{key}' (missing '{part}')")
            node = node[part]
        return node

    def get(self, key):
        """The value at a dotted path; unwraps {value, source, tax_year} leaves."""
        node = self._node(key)
        if isinstance(node, dict) and "value" in node:
            return node["value"]
        return node

    def source(self, key):
        """Where a value came from, for citations next to a calculated figure."""
        node = self._node(key)
        if isinstance(node, dict) and "source" in node:
            return {"source": node["source"], "tax_year": node.get("tax_year", self.tax_year)}
        raise KeyError(f"tax config '{key}' has no source")

    def with_value(self, key, value):
        """A copy with one value replaced. For tests and what-if runs."""
        data = copy.deepcopy(self.data)
        node = data
        parts = key.split(".")
        for part in parts[:-1]:
            node = node[part]
        leaf = node[parts[-1]]
        if isinstance(leaf, dict) and "value" in leaf:
            leaf["value"] = value
        else:
            node[parts[-1]] = value
        return TaxConfig(data, self.path)


@lru_cache(maxsize=None)
def _load(path):
    return TaxConfig(json.loads(Path(path).read_text()), path)


def load_config(path=None):
    """Load the config from `path`, $FIRSTPAYCHECK_TAX_CONFIG, or config/tax_2026.json."""
    path = path or os.environ.get(ENV_VAR) or DEFAULT_PATH
    return _load(str(Path(path).resolve()))


def resolve(config):
    """Accept a TaxConfig, a raw dict, a path, or None (the default file)."""
    if isinstance(config, TaxConfig):
        return config
    if isinstance(config, dict):
        return TaxConfig(config)
    return load_config(config)


def periods_per_year(pay_frequency, config):
    frequencies = config.get("pay_periods")
    if pay_frequency not in frequencies:
        raise ValueError(f"unknown pay_frequency '{pay_frequency}'; expected one of {sorted(frequencies)}")
    return frequencies[pay_frequency]
