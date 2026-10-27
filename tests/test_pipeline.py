from app.io import load
from app.pipeline import run, tray

PAYMENTS = load("samples/payments.csv")


def test_most_of_the_exposure_is_beyond_what_an_erp_would_catch():
    """The finding the whole tool exists for. Exact duplicates are already
    blocked. The money is in the near-duplicates."""
    s = run(PAYMENTS)["summary"]
    assert s["beyond_erp_share"] > 0.8
    assert s["exposure_beyond_erp"] > s["exposure_erp_would_catch"]


def test_recurring_rent_never_reaches_the_claim_tray():
    rows = run(PAYMENTS)["pairs"]
    assert not any("RENT" in r["reason"] for r in rows if r["tray"] == "claim")


def test_the_weakest_pattern_lands_in_review_not_claim():
    for r in run(PAYMENTS)["pairs"]:
        if r["pattern"] == "digits_only":
            assert r["tray"] == "review"


def test_a_legitimate_verdict_dismisses_even_a_high_rule_score():
    """The model can only ever argue a flag down, never up past the rules."""
    assert tray(0.95, "likely_legitimate") == "dismissed"
    assert tray(0.95, None) == "claim"
    assert tray(0.55, "likely_duplicate") == "claim"
    assert tray(0.55, None) == "review"


def test_no_model_is_called_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = run(PAYMENTS)
    assert d["summary"]["sent_to_model"] == 0
    assert all(r["judged_by"] == "rules" for r in d["pairs"])


def test_the_model_is_only_asked_about_the_uncertain_band(monkeypatch):
    import app.pipeline as pl
    seen = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(pl, "claude_judge",
                        lambda c: seen.append(c.score) or {"verdict": "unclear"})
    run(PAYMENTS)
    assert seen, "expected at least one uncertain pair in the sample"
    assert all(0.50 <= s < 0.90 for s in seen)


def test_a_judge_that_fails_every_call_still_spends_the_budget(monkeypatch):
    import app.pipeline as pl
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(pl, "claude_judge", lambda c: calls.append(1) or None)
    monkeypatch.setattr(pl, "MAX_JUDGE", 1)
    d = run(PAYMENTS)
    assert len(calls) == 1
    assert d["summary"]["sent_to_model"] == 1


def test_exposure_by_pattern_totals_every_pair_once():
    d = run(PAYMENTS)
    assert sum(v["pairs"] for v in d["by_pattern"].values()) == d["summary"]["pairs"]
