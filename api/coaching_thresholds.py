"""
Shared coaching thresholds for MEDDICC assessment and prioritization.
Used by query_pre_call_brief, query_coaching_priorities, and related handlers.
"""

COACHING_THRESHOLDS = {
    # MEDDICC component scoring
    "weak_component_max": 4,      # <= this is a weak component needing coaching
    "critical_component_max": 2,  # <= this is critical/missing
    "strong_score_min": 40,       # overall_score >= this is considered strong

    # Activity and staleness
    "stale_call_days": 21,        # calls older than this are stale
    "critical_stale_days": 30,    # urgent intervention needed
    "stale_analysis_days": 21,    # score_is_stale threshold

    # Deal health
    "at_risk_score_max": 30,      # overall_score <= this is at-risk
    "deal_dark_days": 45,          # no activity = deal is dark
}
