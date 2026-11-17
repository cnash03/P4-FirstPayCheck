"""FirstPaycheck financial engine: deterministic calculators, no model calls.

Each calculator is a plain function that takes JSON-friendly inputs and returns a dict, so
the agent can expose it as a tool and the app can call it directly. Rates and limits come
from the tax config (engine/config.py). Inputs and where they come from: engine/fields.md.
"""
from .benefits_cost import benefits_cost
from .config import load_config
from .contribution_order import contribution_order
from .espp import espp
from .paycheck import paycheck

__all__ = ["benefits_cost", "contribution_order", "espp", "load_config", "paycheck"]
