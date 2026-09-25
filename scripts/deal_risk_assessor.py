#!/usr/bin/env python3
"""
Deal Risk Assessor — structured risk assessment for high-priority deals.

Targets deals that are EITHER late-stage (Negotiating/Awaiting Signature)
OR forecast_category='COMMIT', with close_date in current fiscal quarter.

Risk signals:
1. Deal duration vs. typical segment sales cycle (from historical closed-won data)
2. MEDDICC weakness/staleness (DEFERRED - insufficient historical data)

MEDDICC Signal Status (as of 2026-09-21):
- Coverage improved to 67/229 closed-won deals (29.3%) via backfill
- Pre-close analyses (40 won, 276 lost) show +0.5 points raw difference
- Statistical test: p=0.80, 95% CI [-3.44, +4.45], Cohen's d=0.04 (negligible)
- Signal NOT statistically distinguishable from zero - direction could flip by chance
- MEDDICC displayed as INFORMATIONAL CONTEXT ONLY - NOT weighted into risk classification
- Pre-close filtering still enforced (post-close analyses excluded as non-predictive)

Returns per-deal risk_factors list + overall_label (high_risk/moderate_risk/
low_risk/insufficient_data). No fabricated probabilities.

WHY SEPARATE FROM compute_at_risk_deals (api/handlers.py):
- Different scope: late-stage/COMMIT only vs. ALL active deals
- Different signal: cycle-length duration vs. MEDDICC stage-progression readiness
- Different use case: "which high-priority deals are overdue" vs. "which deals lack stage requirements"
- Data grounding: cycle-length from 327 historical wins vs. abstract MEDDICC bands

Both exist intentionally. Convergence attempted 2026-09-16, determined to be
inappropriate due to fundamentally different scopes and signals.
"""
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)

# Historical sales cycle benchmarks (75th percentile) from 327 closed-won deals
# Computed 2026-09-16, should be recomputed periodically as more data accumulates
SEGMENT_CYCLE_BENCHMARKS = {
    "Enterprise": 214,   # 74 deals, 75th percentile = 214 days
    "Mid-Market": 168,   # 110 deals, 75th percentile = 168 days
    "SMB": 138,          # 87 deals, 75th percentile = 138 days
    # "Unknown" segment: if insufficient sample, use blended benchmark from all segments
    # (not another segment's threshold - Unknown deals may have different characteristics)
}

MEDDICC_STALENESS_DAYS = 14  # Scores older than this are flagged as stale
HIGH_RISK_DAYS_PAST = 30     # > this many days past the benchmark = high_risk

try:
    from api.field_semantics import _RENEWAL_PIPELINE_ID
except ImportError:
    from field_semantics import _RENEWAL_PIPELINE_ID

# Renewal-pipeline deals get no label. The benchmark is new-business cycle
# time; renewals run on a different clock (won renewals' 75th percentile is
# 364 days for SMB vs the 138 applied), so the label called deals high risk
# for being renewals (2026-09-25: 4 of the forecast's 9 high-risk deals).
# There is no reliable renewal-risk signal yet; they are reported, not labelled.
NOT_ASSESSED_REASON = ("Renewal-pipeline deal: not risk-assessed. There is no reliable "
                       "renewal-risk signal yet, and the cycle-length benchmark measures "
                       "new-business sales cycles, not renewals.")


def risk_basis() -> str:
    """The method behind overall_label, returned with every result so an
    answer (or a composed answer) states it instead of relaying bare
    counts. Built from the constants _classify_risk uses."""
    bench = ", ".join(f"{seg} {days}" for seg, days in SEGMENT_CYCLE_BENCHMARKS.items())
    return (
        "Risk label is cycle-length only: days open vs. the deal's segment 75th percentile "
        f"sales cycle from historical closed-won deals ({bench} days). high_risk = more than "
        f"{HIGH_RISK_DAYS_PAST} days past it, moderate_risk = 0-{HIGH_RISK_DAYS_PAST} days past, "
        "low_risk = within it, insufficient_data = no benchmark for the segment. MEDDICC is "
        "shown for context only and not weighted (p=0.80, not distinguishable from zero); "
        f"a score older than {MEDDICC_STALENESS_DAYS} days is marked stale. The label is not "
        "a probability. Renewal-pipeline deals are not assessed: they are listed in "
        "not_assessed_deals and counted in summary.not_assessed, outside every risk count."
    )

# Late-stage stage IDs (from config/field_semantics.yaml)
LATE_STAGE_IDS = ['24682892', '43449439']  # Negotiating, Awaiting Signature


def assess_deal_risk(deals: List[Dict[str, Any]], sb) -> Dict[str, Any]:
    """
    Assess risk for high-priority deals (late-stage OR COMMIT forecast).

    Args:
        deals: List of deal dicts with required fields:
               - deal_id
               - company_name
               - stage
               - create_date
               - close_date
               - segment
               - forecast_category
               - deal_status
        sb: Supabase client (for querying analyses table)

    Returns:
        {
            "assessed_deals": [
                {
                    "deal_id": str,
                    "company_name": str,
                    "days_open": int,
                    "segment": str,
                    "stage": str,
                    "forecast_category": str,
                    "risk_factors": [str],  # Plain factual statements
                    "overall_label": "high_risk" | "moderate_risk" | "low_risk" | "insufficient_data",
                    "cycle_benchmark_days": int,  # Segment's 75th percentile
                    "days_past_benchmark": int | None,
                    "meddicc_status": "fresh" | "stale" | "missing",
                    "meddicc_age_days": int | None,
                    "meddicc_overall_score": int | None,  # 0-70 scale (pre-close only)
                    "weak_components": [str]  # DEFERRED - not used (individual components too noisy)
                }
            ],
            "summary": {
                "total_assessed": int,
                "high_risk": int,
                "moderate_risk": int,
                "low_risk": int,
                "insufficient_data": int
            }
        }
    """
    not_assessed = [
        {"deal_id": str(d.get("deal_id", "")), "company_name": d.get("company_name", "Unknown"),
         "pipeline_id": str(d.get("pipeline_id")), "segment": d.get("segment") or "Unknown",
         "stage": d.get("stage", ""), "forecast_category": d.get("forecast_category"),
         "reason": NOT_ASSESSED_REASON}
        for d in deals if str(d.get("pipeline_id")) == _RENEWAL_PIPELINE_ID]
    deals = [d for d in deals if str(d.get("pipeline_id")) != _RENEWAL_PIPELINE_ID]

    if not deals:
        return {
            "assessed_deals": [],
            "not_assessed_deals": not_assessed,
            "not_assessed_note": NOT_ASSESSED_REASON,
            "basis": risk_basis(),
            "summary": {
                "total_assessed": 0,
                "high_risk": 0,
                "moderate_risk": 0,
                "low_risk": 0,
                "insufficient_data": 0,
                "not_assessed": len(not_assessed),
            }
        }

    # Batch-fetch MEDDICC scores for all deals (PRE-CLOSE filtering applied)
    deal_ids = [str(d.get("deal_id")) for d in deals if d.get("deal_id")]
    deals_dict = {str(d.get("deal_id")): d for d in deals if d.get("deal_id")}
    meddicc_scores = _fetch_latest_meddicc_scores(sb, deal_ids, deals_dict)

    assessed = []
    today = date.today()
    now = datetime.now(timezone.utc)

    for deal in deals:
        deal_id = str(deal.get("deal_id", ""))
        company_name = deal.get("company_name", "Unknown")
        segment = deal.get("segment") or "Unknown"
        stage = deal.get("stage", "")
        forecast_category = deal.get("forecast_category")

        # Calculate days open
        create_date_str = deal.get("create_date")
        if not create_date_str:
            logger.warning(f"[RISK_ASSESSOR] Deal {deal_id} missing create_date, skipping")
            continue

        try:
            create_date = datetime.fromisoformat(create_date_str[:10]).date()
            days_open = (today - create_date).days
        except (ValueError, TypeError) as e:
            logger.warning(f"[RISK_ASSESSOR] Deal {deal_id} invalid create_date: {e}")
            continue

        risk_factors = []

        # RISK SIGNAL 1: Deal duration vs. segment benchmark
        cycle_benchmark = SEGMENT_CYCLE_BENCHMARKS.get(segment)
        days_past_benchmark = None

        if cycle_benchmark:
            days_past_benchmark = days_open - cycle_benchmark
            if days_past_benchmark > 0:
                risk_factors.append(
                    f"{days_open} days open, {days_past_benchmark} days past "
                    f"{segment} 75th percentile benchmark ({cycle_benchmark} days)"
                )
        else:
            # Unknown segment with no benchmark - flag as insufficient data for this signal
            risk_factors.append(
                f"{days_open} days open (segment '{segment}' has no historical "
                f"benchmark for comparison)"
            )

        # RISK SIGNAL 2: MEDDICC overall score (INFORMATIONAL ONLY - NOT WEIGHTED)
        # 2026-09-21: Coverage improved to 29.3% (67/229 won deals) via backfill.
        # Statistical test on pre-close data (n=40 won, n=276 lost): p=0.80, 95% CI [-3.44, +4.45]
        # Discrimination (+0.5 points) NOT distinguishable from zero - direction could flip by chance.
        #
        # MEDDICC displayed for context but NOT used in risk classification (cycle-length only).
        # Pre-close filtering still enforced in _fetch_latest_meddicc_scores.
        meddicc_data = meddicc_scores.get(deal_id)
        meddicc_status = "missing"
        meddicc_age_days = None
        meddicc_overall_score = None
        weak_components = []

        if meddicc_data:
            meddicc_overall_score = meddicc_data.get("overall_score")
            analyzed_at = meddicc_data.get("analyzed_at")

            if analyzed_at:
                try:
                    analyzed_dt = datetime.fromisoformat(analyzed_at.replace('Z', '+00:00'))
                    if analyzed_dt.tzinfo is None:
                        analyzed_dt = analyzed_dt.replace(tzinfo=timezone.utc)
                    meddicc_age_days = (now - analyzed_dt).days

                    # Flag stale scores (>14 days old)
                    if meddicc_age_days > MEDDICC_STALENESS_DAYS:
                        meddicc_status = "stale"
                    else:
                        meddicc_status = "fresh"
                except (ValueError, TypeError):
                    pass

            # Display MEDDICC score with explicit note that it's NOT weighted
            if meddicc_overall_score is not None:
                risk_factors.append(
                    f"MEDDICC: {meddicc_overall_score}/70 overall score "
                    f"({meddicc_status}, {meddicc_age_days} days old) "
                    f"[shown for context only; not yet strong enough signal to weight into risk classification - p=0.80]"
                )
        else:
            risk_factors.append(
                "MEDDICC: no pre-close analysis available (active deals with only "
                "post-close analyses are excluded)"
            )

        # OVERALL LABEL: Classify based on cycle-length only (MEDDICC not statistically significant)
        overall_label = _classify_risk(
            days_past_benchmark=days_past_benchmark,
            segment=segment
        )

        assessed.append({
            "deal_id": deal_id,
            "company_name": company_name,
            "days_open": days_open,
            "segment": segment,
            "stage": stage,
            "forecast_category": forecast_category,
            "risk_factors": risk_factors,
            "overall_label": overall_label,
            "cycle_benchmark_days": cycle_benchmark,
            "days_past_benchmark": days_past_benchmark,
            "meddicc_status": meddicc_status,
            "meddicc_age_days": meddicc_age_days,
            "meddicc_overall_score": meddicc_overall_score,
            "weak_components": weak_components
        })

    # Summary counts
    summary = {
        "total_assessed": len(assessed),
        "high_risk": sum(1 for d in assessed if d["overall_label"] == "high_risk"),
        "moderate_risk": sum(1 for d in assessed if d["overall_label"] == "moderate_risk"),
        "low_risk": sum(1 for d in assessed if d["overall_label"] == "low_risk"),
        "insufficient_data": sum(1 for d in assessed if d["overall_label"] == "insufficient_data"),
        "not_assessed": len(not_assessed),
    }

    return {
        "assessed_deals": assessed,
        "not_assessed_deals": not_assessed,
        "not_assessed_note": NOT_ASSESSED_REASON,
        "basis": risk_basis(),
        "summary": summary
    }


def _fetch_latest_meddicc_scores(sb, deal_ids: List[str], deals_dict: Dict[str, Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Fetch latest PRE-CLOSE MEDDICC analysis for each deal.

    CRITICAL: Only pre-close analyses are predictive signals. Post-close analyses
    are retrospective artifacts and must be excluded.

    Pre-close filter: analyzed_at < deal close_date (for closed deals) or
                      analyzed_at < now (for open deals, by definition all are pre-close)

    Args:
        deal_ids: List of deal IDs to fetch scores for
        deals_dict: Dict of deal data keyed by deal_id (for pre-close filtering)

    Returns:
        {deal_id: {analyzed_at, overall_score, component_scores dict}}
    """
    if not deal_ids:
        return {}

    try:
        # Query all analyses for these deals, ordered by analyzed_at desc
        response = sb.table("analyses").select(
            "deal_id,analyzed_at,overall_score,champion_score,economic_buyer_score,"
            "decision_criteria_score,decision_process_score,pain_score,"
            "competition_score,metrics_score"
        ).in_("deal_id", deal_ids).order("analyzed_at", desc=True).execute()

        # Filter to PRE-CLOSE analyses only, then keep latest per deal
        latest = {}
        now = datetime.now(timezone.utc)

        for row in response.data:
            deal_id = str(row["deal_id"])

            # Skip if we already have a latest for this deal
            if deal_id in latest:
                continue

            # PRE-CLOSE FILTER: Check if analysis happened before deal closed
            analyzed_at_str = row.get("analyzed_at")
            if not analyzed_at_str:
                continue

            try:
                analyzed_at = datetime.fromisoformat(analyzed_at_str.replace('Z', '+00:00'))
                if analyzed_at.tzinfo is None:
                    analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)

                # Get deal close date if available
                if deals_dict and deal_id in deals_dict:
                    close_date_str = deals_dict[deal_id].get("close_date")
                    deal_status = deals_dict[deal_id].get("deal_status", "active")

                    # For closed deals, require analyzed_at < close_date
                    if close_date_str and deal_status != "active":
                        if 'T' in close_date_str:
                            close_date = datetime.fromisoformat(close_date_str.replace('Z', '+00:00'))
                            if close_date.tzinfo is None:
                                close_date = close_date.replace(tzinfo=timezone.utc)
                        else:
                            close_date = datetime.strptime(close_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)

                        # EXCLUDE post-close analyses
                        if analyzed_at >= close_date:
                            continue

                    # For active deals, all analyses are by definition pre-close
                    # (the deal hasn't closed yet), so no filter needed

                # This analysis passed the pre-close filter
                latest[deal_id] = row

            except (ValueError, TypeError) as e:
                logger.warning(f"[RISK_ASSESSOR] Failed to parse dates for deal {deal_id}: {e}")
                continue

        return latest
    except Exception as e:
        logger.error(f"[RISK_ASSESSOR] Failed to fetch MEDDICC scores: {e}")
        return {}


def _identify_weak_components(meddicc_data: Dict[str, Any], stage: str) -> List[str]:
    """
    Identify MEDDICC components scoring below expected threshold for stage.

    2026-09-16: CURRENTLY UNUSED - MEDDICC signal deferred.
    Kept for future use once sufficient historical data exists (≥30 won deals
    with scores that discriminate from at-risk deals).

    Original logic:
    - Late-stage deals (Negotiating/Awaiting Signature) should have Green (8-10) across the board
    - Yellow (5-7) or Red (0-4) in late stage = weak component
    """
    weak = []

    # Late-stage deals should have all Green scores (8-10)
    if stage in LATE_STAGE_IDS:
        threshold = 8  # Green band
        components = {
            "Champion": meddicc_data.get("champion_score"),
            "Economic Buyer": meddicc_data.get("economic_buyer_score"),
            "Decision Criteria": meddicc_data.get("decision_criteria_score"),
            "Decision Process": meddicc_data.get("decision_process_score"),
            "Pain": meddicc_data.get("pain_score"),
            "Competition": meddicc_data.get("competition_score"),
            "Metrics": meddicc_data.get("metrics_score")
        }

        for name, score in components.items():
            if score is not None and score < threshold:
                weak.append(f"{name} ({score}/10)")

    return weak


def _classify_risk(
    days_past_benchmark: Optional[int],
    segment: str
) -> str:
    """
    Classify overall risk level based on cycle-length signal only.

    2026-09-21: MEDDICC signal tested but NOT statistically significant (p=0.80,
    95% CI [-3.44, +4.45], discrimination indistinguishable from zero). MEDDICC
    displayed for context but NOT weighted into risk classification.

    Logic:
    - insufficient_data: Unknown segment with no cycle benchmark
    - high_risk: Significantly past benchmark (>30 days)
    - moderate_risk: Moderately past benchmark (0-30 days)
    - low_risk: Within benchmark

    Args:
        days_past_benchmark: Days beyond segment's 75th percentile, or None if no benchmark
        segment: Deal segment for context
    """
    # Insufficient data: no cycle benchmark to assess
    # MEDDICC alone insufficient (p=0.80, not statistically significant)
    if days_past_benchmark is None:
        return "insufficient_data"

    # High risk: significantly overdue (>30 days past benchmark)
    if days_past_benchmark > HIGH_RISK_DAYS_PAST:
        return "high_risk"

    # Moderate risk: moderately overdue (0-30 days past benchmark)
    if days_past_benchmark > 0:
        return "moderate_risk"

    # Low risk: within or ahead of benchmark
    return "low_risk"


def get_at_risk_deals(sb, fiscal_quarter: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function: Query target deals and assess risk in one call.

    Target: late-stage (Negotiating/Awaiting Signature) OR forecast_category='COMMIT',
    with deal_status='active' and close_date in current fiscal quarter.

    Args:
        sb: Supabase client
        fiscal_quarter: Optional explicit quarter (e.g. 'FY2027 Q3'), defaults to current

    Returns:
        assess_deal_risk() output dict
    """
    from utils import get_fiscal_quarter

    # Resolve fiscal quarter
    if not fiscal_quarter:
        _, _, fiscal_quarter = get_fiscal_quarter()

    # Get quarter boundaries for close_date filter
    # Parse fiscal quarter to get dates
    # FY2027 Q3 -> Q3 of fiscal year 2027
    import re
    match = re.match(r'FY(\d{4})\s+Q([1-4])', fiscal_quarter)
    if not match:
        logger.error(f"[RISK_ASSESSOR] Invalid fiscal_quarter format: {fiscal_quarter}")
        return assess_deal_risk([], sb)

    fiscal_year = int(match.group(1))
    quarter_num = int(match.group(2))

    # Fiscal year starts Feb 1 (from get_fiscal_quarter logic)
    # Q1: Feb-Apr, Q2: May-Jul, Q3: Aug-Oct, Q4: Nov-Jan
    quarter_start_month = 2 + (quarter_num - 1) * 3
    if quarter_start_month > 12:
        quarter_start_month -= 12
        calendar_year = fiscal_year
    else:
        calendar_year = fiscal_year - 1

    from datetime import date as dt
    import calendar

    q_start = dt(calendar_year, quarter_start_month, 1)

    # Quarter end is 3 months later
    end_month = quarter_start_month + 2
    end_year = calendar_year
    if end_month > 12:
        end_month -= 12
        end_year += 1

    last_day = calendar.monthrange(end_year, end_month)[1]
    q_end = dt(end_year, end_month, last_day)

    # Query deals
    try:
        # Build filters for Union query: (stage IN late_stage_ids OR forecast_category='COMMIT')
        # AND deal_status='active' AND close_date in quarter
        # PostgreSQL REST API doesn't support complex OR filters directly, so we'll do two queries

        # Query 1: Late-stage deals
        response1 = sb.table("deals").select(
            "deal_id,company_name,stage,create_date,close_date,segment,forecast_category,deal_status,pipeline_id"
        ).in_("stage", LATE_STAGE_IDS).eq("deal_status", "active").gte(
            "close_date", q_start.isoformat()
        ).lte("close_date", q_end.isoformat()).execute()

        # Query 2: COMMIT deals
        response2 = sb.table("deals").select(
            "deal_id,company_name,stage,create_date,close_date,segment,forecast_category,deal_status,pipeline_id"
        ).eq("forecast_category", "COMMIT").eq("deal_status", "active").gte(
            "close_date", q_start.isoformat()
        ).lte("close_date", q_end.isoformat()).execute()

        # Union and deduplicate by deal_id
        deals_dict = {}
        for deal in response1.data + response2.data:
            deals_dict[deal["deal_id"]] = deal

        deals = list(deals_dict.values())

        logger.info(
            f"[RISK_ASSESSOR] Found {len(deals)} target deals for {fiscal_quarter} "
            f"(late-stage OR COMMIT, close_date {q_start} to {q_end})"
        )

        return assess_deal_risk(deals, sb)

    except Exception as e:
        logger.error(f"[RISK_ASSESSOR] Failed to query target deals: {e}")
        return assess_deal_risk([], sb)


if __name__ == "__main__":
    # Test against real data
    import sys
    import os
    from pathlib import Path

    # Load env
    env_path = Path.home() / "MEDDICC-agent" / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip('"').strip("'")

    sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
    sys.path.insert(0, str(Path(__file__).parent))

    from db import get_supabase

    sb = get_supabase()

    print("=" * 80)
    print("DEAL RISK ASSESSOR - Real Data Test")
    print("=" * 80)
    print()

    result = get_at_risk_deals(sb)

    print(f"Total assessed: {result['summary']['total_assessed']}")
    print(f"High risk: {result['summary']['high_risk']}")
    print(f"Moderate risk: {result['summary']['moderate_risk']}")
    print(f"Low risk: {result['summary']['low_risk']}")
    print(f"Insufficient data: {result['summary']['insufficient_data']}")
    print()

    # Sort by risk level, then days_open desc
    risk_order = {"high_risk": 0, "moderate_risk": 1, "low_risk": 2, "insufficient_data": 3}
    sorted_deals = sorted(
        result['assessed_deals'],
        key=lambda d: (risk_order[d['overall_label']], -d['days_open'])
    )

    for deal in sorted_deals:
        print("-" * 80)
        print(f"Company: {deal['company_name']}")
        print(f"Deal ID: {deal['deal_id']}")
        print(f"Risk Level: {deal['overall_label'].upper()}")
        print(f"Days Open: {deal['days_open']} days")
        print(f"Segment: {deal['segment']}")
        print(f"Stage: {deal['stage']}")
        print(f"Forecast: {deal['forecast_category']}")

        if deal['cycle_benchmark_days']:
            print(f"Cycle Benchmark: {deal['cycle_benchmark_days']} days ({deal['segment']} 75th %ile)")
            if deal['days_past_benchmark'] is not None:
                if deal['days_past_benchmark'] > 0:
                    print(f"Days Past Benchmark: +{deal['days_past_benchmark']} days")
                else:
                    print(f"Days Past Benchmark: {deal['days_past_benchmark']} days (within)")

        print(f"MEDDICC Status: {deal['meddicc_status']}")
        if deal['meddicc_age_days'] is not None:
            print(f"MEDDICC Age: {deal['meddicc_age_days']} days")
        if deal['weak_components']:
            print(f"Weak Components: {', '.join(deal['weak_components'])}")

        print("Risk Factors:")
        for factor in deal['risk_factors']:
            print(f"  • {factor}")
        print()

    # Verify Freie Presse is high_risk
    freie_presse = next(
        (d for d in result['assessed_deals'] if 'Freie Presse' in d['company_name']),
        None
    )
    if freie_presse:
        print("=" * 80)
        print("VERIFICATION: Freie Presse Risk Assessment")
        print("=" * 80)
        if freie_presse['overall_label'] == 'high_risk':
            print("✅ PASS: Freie Presse correctly flagged as HIGH RISK")
        else:
            print(f"❌ FAIL: Freie Presse flagged as {freie_presse['overall_label']}, expected high_risk")
        print(f"Days open: {freie_presse['days_open']}")
        print(f"Days past benchmark: {freie_presse['days_past_benchmark']}")
    else:
        print("⚠️  Freie Presse not found in assessed deals")
