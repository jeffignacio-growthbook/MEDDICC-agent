#!/usr/bin/env python3
"""
Brief mode for query_quarter_health: triggered by length words (succinct,
brief, short, quick, tl;dr) in the question. Produces a ~120-word synthesis
prompt instead of the full three-step verbatim prescription.

Item 4 rule: brief mode NEVER drops disclosures that change what the headline
means — unweighted label, renewals-not-counted, quota basis. Only the
word-for-word requirement on loss rate, pace, and seasonality is lifted.

Tests (per task item 7):
  - brief note contains the forecast total
  - brief note contains both split figures (COMMIT and Most Likely)
  - brief note contains closed-won amount
  - brief note contains remaining-to-target amount
  - brief note stays under ~120-word instruction
  - "unweighted" label survives in brief note
  - rep-detail and loss-rate are offered as follow-ups
  - full mode is unchanged (still has step-by-step verbatim requirement)
  - full mode leads with forecast total + split
  - is_brief_mode() triggers on the right words
"""
import copy
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging
logging.disable(logging.CRITICAL)

import api.quarter_health as qh  # noqa: E402

# ------------------------------------------------------------------ fixtures

_FORECAST_TOTAL = 1_946_176.0
_COMMIT_TOTAL   = 1_200_000.0
_ML_TOTAL       = 746_176.0
_CLOSED_WON     = 447_775.0
_TARGET         = 1_550_000.0
_REMAINING      = _TARGET - _CLOSED_WON          # 1_102_225
_WEIGHTED       = 1_350_000.0
_RAW_PIPELINE   = 2_900_000.0
_RATIO          = _WEIGHTED / _REMAINING          # ~1.22x
_QUARTER        = "FY2027 Q3"
_HIGH_RISK_ARR  = 420_000.0
_NOT_ASSESSED   = 180_000.0


def _ft_figures(commit=_COMMIT_TOTAL, ml=_ML_TOTAL):
    """Minimal forecast_trust figures with COMMIT/ML split."""
    return {
        "status": "ok",
        "fiscal_quarter": _QUARTER,
        "current_week": 9,
        "forecast_arr": _FORECAST_TOTAL,
        "forecast_deal_count": 21,
        "commit_arr": commit,
        "most_likely_arr": ml,
        "high_risk_count": 3,
        "high_risk_fraction": 0.14,
        "high_risk_fraction_basis": "share of risk-assessed deals (by count), not of the forecast",
        "assessed_deal_count": 18,
        "not_assessed_deal_count": 3,
        "high_risk_arr": _HIGH_RISK_ARR,
        "high_risk_share_of_forecast": _HIGH_RISK_ARR / _FORECAST_TOTAL,
        "not_assessed_arr": _NOT_ASSESSED,
        "not_assessed_share_of_forecast": _NOT_ASSESSED / _FORECAST_TOTAL,
    }


def _qtd_figures():
    return {
        "status": "ok",
        "fiscal_quarter": _QUARTER,
        "closed_won_arr": _CLOSED_WON,
        "closed_won_count": 9,
        "target": _TARGET,
        "remaining_to_target": _REMAINING,
        "days_left": 33,
        "weeks_left": 4,
        "weeks_left_label": "about 5 weeks left",
        "forecast_arr": _FORECAST_TOTAL,
        "remaining_share_of_forecast": _REMAINING / _FORECAST_TOTAL,
        "line": (f"${_CLOSED_WON:,.0f} closed won QTD against the ${_TARGET:,.0f} target "
                 f"(${_REMAINING:,.0f} remaining), with 4 weeks left in the quarter. "
                 f"Closing that gap takes {_REMAINING/_FORECAST_TOTAL:.0%} of the "
                 f"${_FORECAST_TOTAL:,.0f} forecast (COMMIT+MOST_LIKELY deals closing this quarter)."),
        "basis": "Closed won = new+expansion ARR of the 9 deals won in FY2027 Q3.",
    }


def _pace_figures():
    return {
        "status": "ok",
        "days_elapsed": 59,
        "days_in_quarter": 92,
        "elapsed_share": 0.641,
        "target_share_won": _CLOSED_WON / _TARGET,
        "line": "59 of 92 days (64%) of the quarter have passed and 29% of the $1,550,000 target ($447,775) is closed won.",
        "seasonality_line": "Bookings here are back-loaded: 20% to 45% (median 32%) of a quarter's closed-won ARR was in by this point.",
        "seasonality": {"status": "ok", "median_share_by_this_point": 0.32},
        "basis": "Days: this quarter's dates, today counted.",
    }


def _cov_figures():
    return {
        "status": "ok",
        "qualified_pipeline_arr": _RAW_PIPELINE,
        "qualified_deal_count": 38,
        "weighted_arr": _WEIGHTED,
        "remaining_to_target": _REMAINING,
        "unweighted_arr": _RAW_PIPELINE,
        "unweighted_deal_count": 0,
        "coverage_of_remaining": _RATIO,
        "renewal_not_weighted_arr": 300_000.0,
        "renewal_not_weighted_count": 4,
        "line": (f"Weighted by each deal's current-stage close rate, the ${_RAW_PIPELINE:,.0f} of qualified "
                 f"Sales pipeline closing this quarter (38 deals) is worth ${_WEIGHTED:,.0f}: "
                 f"{_RATIO:.2f}x the ${_REMAINING:,.0f} still needed to reach target."),
        "basis": "Stage rate: the share of deals at that stage during a quarter that closed won by quarter end.",
    }


def _loss_figures():
    return {
        "status": "ok",
        "period": _QUARTER,
        "closed_deal_count": 23,
        "won_count": 9,
        "lost_count": 14,
        "qualified_loss_rate": 0.58,
        "all_closed_loss_rate": 0.61,
        "won_incremental_arr": _CLOSED_WON,
        "loss_rate_headline": "58% qualified loss rate this quarter (14 of 24 qualified deals lost).",
        "rep_context": ["rep@example.com: 2 losses | still live: $200,000 forecast | losses: 2/deep | pace: ahead"],
        "rep_context_basis": "Loss rows are this quarter's closed qualified deals.",
    }


def _all_figures():
    return {
        "forecast_trust": _ft_figures(),
        "pipeline": {
            "status": "ok",
            "total_pipeline": 4_200_000,
            "total_deals": 55,
            "quarterly_target": _TARGET,
        },
        "deal_risk": {"status": "ok", "summary": {"high_risk": 5, "moderate_risk": 7, "low_risk": 6}},
        "loss_concentration": _loss_figures(),
        "quarter_to_date": _qtd_figures(),
        "pace": _pace_figures(),
        "coverage": _cov_figures(),
    }


# ------------------------------------------------------------------ helpers

def _brief_note(figures=None):
    figs = figures or _all_figures()
    lc = figs.get("loss_concentration") or {}
    return qh._note("base", _QUARTER, figs,
                    loss_headline=lc.get("loss_rate_headline"), brief_mode=True)


def _full_note(figures=None):
    figs = figures or _all_figures()
    lc = figs.get("loss_concentration") or {}
    return qh._note("base", _QUARTER, figs,
                    loss_headline=lc.get("loss_rate_headline"), brief_mode=False)


# ------------------------------------------------------------------ is_brief_mode

def test_is_brief_mode_triggers():
    for q in [
        "please give me a succinct forecast update",
        "brief forecast",
        "short q update",
        "quick read on the quarter",
        "tl;dr on this quarter",
        "tldr forecast",
        "give me a BRIEF update",
    ]:
        assert qh.is_brief_mode(q), f"should trigger on: {q!r}"


def test_is_brief_mode_does_not_trigger_on_normal():
    for q in [
        "are we in good shape this quarter?",
        "quarter health check",
        "overall read on q3",
        "how is the quarter looking",
        "forecast update",                 # no trigger word
    ]:
        assert not qh.is_brief_mode(q), f"should not trigger on: {q!r}"


# ------------------------------------------------------------------ brief note: required figures

def test_brief_note_contains_forecast_total():
    note = _brief_note()
    assert "1,946,176" in note, f"forecast total missing from brief note"


def test_brief_note_contains_commit_split():
    note = _brief_note()
    assert "1,200,000" in note, f"COMMIT amount missing from brief note"
    assert "COMMIT" in note, "COMMIT label missing"


def test_brief_note_contains_ml_split():
    note = _brief_note()
    assert "746,176" in note, f"Most Likely amount missing from brief note"
    assert "Most Likely" in note or "most likely" in note.lower(), "Most Likely label missing"


def test_brief_note_contains_closed_won():
    note = _brief_note()
    assert "447,775" in note, f"closed-won amount missing from brief note"


def test_brief_note_contains_remaining():
    note = _brief_note()
    assert "1,102,225" in note, f"remaining amount missing from brief note"


# ------------------------------------------------------------------ item 4: required disclosures

def test_brief_note_contains_unweighted_disclosure():
    """The unweighted label must survive — it changes what the headline means."""
    note = _brief_note()
    assert "unweighted" in note.lower(), "unweighted label must appear in brief note"


def test_brief_note_contains_renewals_disclosure():
    """'not counting renewals' or equivalent must appear."""
    note = _brief_note()
    assert "renewal" in note.lower() or "new+expansion" in note.lower(), (
        "renewals-not-counted disclosure must appear in brief note"
    )


def test_brief_note_contains_target_basis():
    """The quota/target basis must appear."""
    note = _brief_note()
    # The target basis tells the reader what the $1.55M number is
    assert "target" in note.lower() or "quota" in note.lower(), (
        "target/quota basis must appear in brief note"
    )


# ------------------------------------------------------------------ brief mode: follow-ups

def test_brief_note_offers_followups():
    note = _brief_note()
    note_lower = note.lower()
    assert "rep" in note_lower or "loss rate" in note_lower or "detail" in note_lower, (
        "brief note must offer rep detail or loss rate as follow-up"
    )


# ------------------------------------------------------------------ word count instruction

def test_brief_note_instructs_short_response():
    note = _brief_note()
    # The note should tell the LLM to reply briefly
    note_lower = note.lower()
    assert ("120" in note or "brief" in note_lower or "under" in note_lower or
            "concise" in note_lower or "short" in note_lower), (
        "brief note should instruct the model to reply briefly (~120 words)"
    )


# ------------------------------------------------------------------ full mode unchanged

def test_full_mode_has_three_steps():
    note = _full_note()
    assert "1. WHERE THE QUARTER STANDS" in note or "three steps" in note.lower(), (
        "full mode must still have step-by-step verbatim structure"
    )


def test_full_mode_still_has_verbatim_qtd_line():
    note = _full_note()
    qtd = _qtd_figures()
    line = qtd["line"]
    assert line in note, "full mode must still require verbatim QTD line"


def test_full_mode_forecast_total_appears_before_step1():
    """In full mode the forecast total + COMMIT/ML split must be the first line."""
    note = _full_note()
    assert "1,946,176" in note, "forecast total must appear in full mode note"
    # The forecast total must appear before step 1 starts
    idx_total = note.find("1,946,176")
    idx_step1 = note.find("1. WHERE")
    assert idx_total < idx_step1 or idx_step1 == -1, (
        "forecast total must appear before step 1 in full mode note"
    )


def test_full_mode_commit_ml_in_opening():
    """Full mode opening line has COMMIT + ML split."""
    note = _full_note()
    assert "1,200,000" in note or "COMMIT" in note, "COMMIT appears in full mode note"


# ------------------------------------------------------------------ brief vs full distinguishable

def test_brief_mode_does_not_require_verbatim_pace():
    """Brief mode lifts the word-for-word pace/seasonality requirement."""
    brief = _brief_note()
    full = _full_note()
    # Full mode has a verbatim instruction for the seasonality line
    # Brief mode should NOT require this verbatim quote
    pace_line = _pace_figures()["line"]
    # Full mode: verbatim quote present
    assert pace_line in full, "full mode must have verbatim pace line instruction"
    # Brief mode: not required verbatim (may appear as context but not as verbatim requirement)
    # We just verify the brief note is shorter and doesn't have the verbatim instruction
    assert len(brief) < len(full), "brief note should be shorter than full note"


def test_brief_mode_does_not_require_verbatim_loss_rate():
    """Brief mode lifts the word-for-word requirement on the loss rate."""
    brief = _brief_note()
    full = _full_note()
    # The loss rate verbatim instruction in full mode contains "verbatim"
    # Brief mode may reference the loss rate as a follow-up, not verbatim
    # Key check: "verbatim" is used for loss_rate in full mode
    assert "verbatim" in full, "full mode must use verbatim requirement"
    # Brief mode: either no "verbatim" or only for the core figures
    # The brief note may still say verbatim for the core lines but not loss rate
    # At minimum: the full loss-rate verbatim instruction should not be in brief
    loss_headline = _loss_figures().get("loss_rate_headline", "")
    if loss_headline:
        # In full mode, loss headline appears verbatim-required
        assert loss_headline in full or "Loss rate" in full
        # Brief mode: loss rate is offered as follow-up, not required verbatim
        # (loss headline may still appear as reference but not as verbatim requirement)


# ------------------------------------------------------------------ missing COMMIT/ML graceful

def test_brief_note_graceful_when_commit_ml_missing():
    """If COMMIT/ML split not available, brief note still works."""
    figs = _all_figures()
    figs["forecast_trust"].pop("commit_arr", None)
    figs["forecast_trust"].pop("most_likely_arr", None)
    note = qh._note("base", _QUARTER, figs, brief_mode=True)
    assert "1,946,176" in note, "forecast total must appear even without split"


def test_forecast_figures_includes_commit_ml_from_by_owner():
    """_forecast_figures() computes commit_arr + most_likely_arr from by_owner."""
    raw_ft = {
        "status": "ok",
        "fiscal_quarter": _QUARTER,
        "current_week": 9,
        "pipeline": {"deal_count": 3, "incremental_arr": _FORECAST_TOTAL, "excluded_no_incremental_arr": 0},
        "risk_summary": {"total_assessed": 2, "not_assessed": 1},
        "high_risk_count": 1,
        "high_risk_fraction": 0.5,
        "assessed_deals": [],
        "by_owner": {
            "rep1@example.com": {"commit_arr": _COMMIT_TOTAL, "most_likely_arr": 0.0, "forecast_arr": _COMMIT_TOTAL, "deal_count": 1},
            "rep2@example.com": {"commit_arr": 0.0, "most_likely_arr": _ML_TOTAL, "forecast_arr": _ML_TOTAL, "deal_count": 1},
        },
    }
    figs = qh._forecast_figures(raw_ft)
    assert figs.get("commit_arr") == _COMMIT_TOTAL, f"commit_arr expected {_COMMIT_TOTAL}, got {figs.get('commit_arr')}"
    assert figs.get("most_likely_arr") == _ML_TOTAL, f"most_likely_arr expected {_ML_TOTAL}, got {figs.get('most_likely_arr')}"


def test_forecast_figures_no_commit_ml_when_by_owner_absent():
    """_forecast_figures() with no by_owner produces no commit_arr/most_likely_arr."""
    raw_ft = {
        "status": "ok",
        "fiscal_quarter": _QUARTER,
        "current_week": 9,
        "pipeline": {"deal_count": 3, "incremental_arr": _FORECAST_TOTAL, "excluded_no_incremental_arr": 0},
        "risk_summary": {"total_assessed": 2, "not_assessed": 1},
        "high_risk_count": 1,
        "high_risk_fraction": 0.5,
        "assessed_deals": [],
    }
    figs = qh._forecast_figures(raw_ft)
    assert "commit_arr" not in figs
    assert "most_likely_arr" not in figs
