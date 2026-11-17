"""Every evaluation case is well formed and its expected numbers add up.

These run on every case file in eval/cases/, so a new case is checked as soon
as it is added: schema, field ids that exist in samples/answers/, input figures
that match their document or profile, and derivations that recompute exactly.
"""
import pytest

from eval.cases import CASES, check_case, evaluate, load_case, load_cases

ALL = load_cases()
IDS = {c["id"] for c in ALL}


@pytest.mark.parametrize("case", ALL, ids=lambda c: c["id"])
def test_case_is_valid(case):
    assert check_case(case, IDS) == []


def test_the_five_examples_are_present():
    main = {c["example"] for c in ALL if "variant_of" not in c and "example" in c}
    assert main == {1, 2, 3, 4, 5}


def test_hard_case_never_says_always_buy():
    """Proposal: for Example 4, a holding period or no emergency fund rules out 'always buy'."""
    for c in ALL:
        if c["analysis"] == "espp":
            assert "always buy" in [s.lower() for s in c["expected"].get("must_not_include", [])], c["id"]


def test_example1_lines_add_up_to_net():
    case = next(c for c in ALL if c["id"] == "ex1-take-home")
    f = {x["id"]: x["value"] for x in case["expected"]["figures"]}
    deductions = ["pretax_401k", "medical_premium", "federal_withholding", "social_security",
                  "medicare", "colorado_withholding", "colorado_famli", "denver_opt"]
    assert round(f["gross_pay"] - sum(f[d] for d in deductions), 2) == f["net_pay"]


# ---- the checker itself catches mistakes ----

def _broken(tmp_path, edit):
    case = load_case(CASES / "ex1-take-home.json")
    edit(case)
    case["_path"] = str(tmp_path / "ex1-take-home.json")
    return check_case(case, IDS)


def test_catches_wrong_arithmetic(tmp_path):
    def edit(c):
        next(f for f in c["expected"]["figures"] if f["id"] == "net_pay")["value"] = 2500.00
    assert any("net_pay" in p and "derivation" in p for p in _broken(tmp_path, edit))


def test_catches_value_that_disagrees_with_the_document(tmp_path):
    def edit(c):
        next(f for f in c["expected"]["figures"] if f["id"] == "annual_salary")["value"] = 95000
    assert any("document field says 90000" in p for p in _broken(tmp_path, edit))


def test_catches_unknown_field_id(tmp_path):
    def edit(c):
        c["fields"].append("offer_letter.pdf:offer.signing_bonus")
    assert any("signing_bonus" in p for p in _broken(tmp_path, edit))


def test_derivations_reject_code():
    with pytest.raises(ValueError):
        evaluate("__import__('os').system('true')", {})
    assert evaluate("min(a, 2) + 3 ** 2 / 3", {"a": 1}) == 4
