"""
Handler functions for CRO Slack Agent.
Each handler reads ONLY precomputed Supabase tables and returns
structured data (not prose). The router generates prose answers
from this data using Sonnet.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

# Add scripts to path for supabase_client
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from supabase_client import select_all
from sdr_utils import rate_or_gap, today_in_reporting_tz


async def query_waterfall(params: dict, sb) -> dict:
    """
    Pipeline snapshot + movement in ONE handler with question-aware emphasis.

    Returns both:
    - pipeline_summary: current state (total, by-stage, needs-attention)
    - waterfall: weekly movement (new/won/lost)

    Synthesis adapts based on question framing:
    - "show me pipeline" → lead with snapshot
    - "how did pipeline change" → lead with movement

    G.7: Includes cache_payload with deal-level rows for follow-ups.
    """
    import yaml
    from pathlib import Path

    tw = params["time_window"]
    question = params.get("question", "").lower()

    # Load stage config from client.yaml
    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))

    # Build stage lookup: {stage_id: {name, order, exclude_from_analysis}}
    stage_lookup = {}
    excluded_stage_ids = set()

    for pipeline in config["pipeline"]["pipelines"]:
        if pipeline.get("analyze") is False:
            continue  # Skip renewal pipelines
        for stage in pipeline["stages"]:
            stage_id = stage["id"]
            stage_lookup[stage_id] = {
                "name": stage["name"],
                "order": stage["order"],
                "exclude_from_analysis": stage.get("exclude_from_analysis", False)
            }
            if stage.get("exclude_from_analysis"):
                excluded_stage_ids.add(stage_id)

    # === PIPELINE SUMMARY: Current state ===
    # Query active deals
    active_deals = select_all(sb, "deals",
        columns="deal_id,company_name,arr_usd,stage,deal_status",
        filters=[("eq", "deal_status", "active")])

    # Filter out excluded stages
    included_deals = [d for d in active_deals
                      if d.get("stage") not in excluded_stage_ids]

    # Total open pipeline
    total_open_arr = sum(d.get("arr_usd") or 0 for d in included_deals)
    total_open_count = len(included_deals)

    # By-stage breakdown
    from collections import defaultdict
    stage_stats = defaultdict(lambda: {"count": 0, "arr": 0})

    for d in included_deals:
        stage_id = d.get("stage")
        if stage_id in stage_lookup:
            stage_stats[stage_id]["count"] += 1
            stage_stats[stage_id]["arr"] += d.get("arr_usd") or 0

    # Sort by stage order
    by_stage = []
    for stage_id in sorted(stage_stats.keys(),
                          key=lambda sid: stage_lookup.get(sid, {}).get("order", 999)):
        stage_info = stage_lookup.get(stage_id, {})
        stats = stage_stats[stage_id]
        by_stage.append({
            "stage_name": stage_info.get("name", stage_id),
            "count": stats["count"],
            "arr": stats["arr"]
        })

    # Needs attention: deals with no ARR
    no_arr_deals = [d for d in included_deals if not d.get("arr_usd")]
    no_arr_count = len(no_arr_deals)
    no_arr_list = [d["company_name"] for d in no_arr_deals[:5]]

    # Needs attention: at-risk deals (reuse query_deals_at_risk threshold)
    # Threshold: overall_score < 40 or champion_score < 4
    analyses = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,analyzed_at",
        filters=[])

    # Deduplicate: keep most recent analysis per deal_id
    latest_analyses = {}
    for a in analyses:
        deal_id = a["deal_id"]
        analyzed_at = a.get("analyzed_at", "")
        if deal_id not in latest_analyses or analyzed_at > latest_analyses[deal_id].get("analyzed_at", ""):
            latest_analyses[deal_id] = a

    # Build active deal_id set for filtering
    active_deal_ids = {d["deal_id"] for d in included_deals}

    at_risk_deals = []
    for a in latest_analyses.values():
        if a["deal_id"] not in active_deal_ids:
            continue  # Only active deals
        score = a.get("overall_score", 0) or 0
        champ = a.get("champion_score", 0) or 0
        if score < 40 or champ < 4:
            risk_reason = []
            if score < 40:
                risk_reason.append(f"low MEDDICC ({score})")
            if champ < 4:
                risk_reason.append(f"champion gap ({champ})")
            at_risk_deals.append({
                "company": a["company_name"],
                "risk": " + ".join(risk_reason)
            })

    at_risk_count = len(at_risk_deals)
    at_risk_list = at_risk_deals[:5]

    pipeline_summary = {
        "total_open_arr": total_open_arr,
        "total_open_count": total_open_count,
        "by_stage": by_stage,
        "needs_attention": {
            "no_arr_count": no_arr_count,
            "no_arr_deals": no_arr_list,
            "at_risk_count": at_risk_count,
            "at_risk_deals": at_risk_list
        }
    }

    # === WATERFALL: Weekly movement (unchanged) ===
    weekly = select_all(sb, "waterfall_weekly",
        columns="week_ending,pipeline_id,new_pipeline_value,"
                "won_value,lost_value,net_change,"
                "pulled_in_value,pushed_out_value,"
                "deals_qualified_count",
        filters=[("gte", "week_ending", tw["start"]),
                 ("lte", "week_ending", tw["end"])])

    # Deal-level rows for follow-ups (cache_payload)
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,arr_usd,"
                "stage,close_date,owner_email,segment,deal_status",
        filters=[("gte", "close_date", tw["start"]),
                 ("lte", "close_date", tw["end"])])

    # === REPORT SHAPE: Question-aware emphasis ===
    # Detect question framing to select appropriate report shape
    # Use more specific patterns to avoid overlap
    movement_keywords = ["change", "moved", "movement", "trend",
                        "how did", "what happened", "new pipeline",
                        "won this", "lost this"]
    snapshot_keywords = ["current", "open", "show me", "what's in",
                        "what deals", "snapshot", "how much"]

    is_movement_question = any(kw in question for kw in movement_keywords)
    is_snapshot_question = any(kw in question for kw in snapshot_keywords)

    # Prioritize movement (trend shape) if both match
    if is_movement_question:
        report_shape = "trend"
    elif is_snapshot_question:
        report_shape = "snapshot"
    else:
        report_shape = "snapshot"  # Default to snapshot

    return {
        "pipeline_summary": pipeline_summary,  # Current state
        "waterfall": weekly,                   # Movement
        "period": tw["label"],
        "report_shape": report_shape,          # Declared shape for synthesis
        "cache_payload": {                     # Retained, NOT shown
            "deals": deals
        }
    }


async def query_arr(params: dict, sb) -> dict:
    """
    ARR by customer from the arr_by_customer view.
    Returns top N customers by ARR.
    """
    rows = select_all(sb, "arr_by_customer",
        columns="company_name,total_arr,"
                "won_deal_count,most_recent_close")
    limit = params.get("limit", 20)
    return {"arr_by_customer": rows[:limit]}


async def query_deals_at_risk(params: dict, sb) -> dict:
    """
    Deals with weak MEDDICC scores or champion gaps.

    PHASE G.10: Stage-aware risk determination.
    A deal is "at risk" if ANY component required at its CURRENT STAGE
    is below the threshold to advance. Components not yet required are
    excluded from risk determination.

    Uses stage_progression requirements from config/client.yaml.
    """
    from api.stage_requirements import get_requirements_for_stage

    tw = params["time_window"]
    deal_ids = params.get("deal_ids", [])

    # Filter analyses to specific deals if context provided
    analyses_filters = [("gte", "analyzed_at", tw["start"])]
    if deal_ids:
        analyses_filters.append(
            ("in_", "deal_id", deal_ids))

    # Fetch ALL component scores (not just champion/eb)
    analyses = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,economic_buyer_score,"
                "metrics_score,decision_criteria_score,"
                "decision_process_score,pain_score,"
                "competition_score,analyzed_at",
        filters=analyses_filters)

    # Deduplicate: keep only the most recent analysis per deal_id
    # (analyses table has historical snapshots from nightly runs)
    latest_analyses = {}
    for a in analyses:
        deal_id = a["deal_id"]
        analyzed_at = a.get("analyzed_at", "")
        if deal_id not in latest_analyses or analyzed_at > latest_analyses[deal_id].get("analyzed_at", ""):
            latest_analyses[deal_id] = a

    analyses = list(latest_analyses.values())

    # Fetch deal stage data for stage-aware requirements
    if deal_ids:
        # Entity-filtered: only fetch stages for these deals
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,deal_value,"
                    "deal_status,stage",
            filters=[("in_", "deal_id", deal_ids)])
    else:
        # Full query: only active deals
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,deal_value,"
                    "deal_status,stage",
            filters=[("eq", "deal_status", "active")])

    deal_map = {d["deal_id"]: d for d in deals}
    at_risk = []

    # Component name mapping
    component_fields = {
        "pain": "pain_score",
        "champion": "champion_score",
        "metrics": "metrics_score",
        "economic_buyer": "economic_buyer_score",
        "decision_criteria": "decision_criteria_score",
        "decision_process": "decision_process_score",
        "competition": "competition_score",
    }

    for a in analyses:
        d = deal_map.get(a["deal_id"])
        if not d:
            continue

        stage_id = d.get("stage")
        if not stage_id:
            continue

        # Get requirements for this deal's current stage
        requirements = get_requirements_for_stage(stage_id)

        # No requirements = terminal/excluded stage, never at-risk
        if not requirements:
            continue

        # Check each required component
        risk_flags = []
        for component, required_threshold in requirements.items():
            field_name = component_fields.get(component)
            if not field_name:
                continue

            actual_score = a.get(field_name, 0) or 0

            if actual_score < required_threshold:
                # Stage-aware risk message
                from api.stage_requirements import _get_stage_by_id
                stage_info = _get_stage_by_id(stage_id)
                stage_name = stage_info["name"] if stage_info else "current stage"

                risk_flags.append(
                    f"{component.replace('_', ' ').title()} {actual_score}/10 "
                    f"(need {required_threshold}+ to advance from {stage_name})"
                )

        # Only flag if there are actual risk flags
        if risk_flags:
            at_risk.append({
                "deal_id":       a["deal_id"],
                "company_name":  a["company_name"],
                "overall_score": a.get("overall_score", 0) or 0,
                "champion_score": a.get("champion_score", 0) or 0,
                "deal_value":    d.get("deal_value"),
                "stage":         stage_id,
                "risk_flags":    risk_flags
            })

    at_risk.sort(key=lambda x: (x["overall_score"],
                                 -(x["deal_value"] or 0)))

    if not at_risk:
        return {
            "deals_at_risk": [],
            "total_at_risk": 0,
            "message": ("No deals currently flagged as at-risk. "
                       "Note: Recently created deals may not have "
                       "MEDDICC analysis yet — those run nightly.")
        }

    return {"deals_at_risk": at_risk[:10],
            "total_at_risk": len(at_risk)}


async def query_win_loss(params: dict, sb) -> dict:
    """
    Comprehensive win/loss analysis combining:
    - win_loss_narratives (weekly AI narratives)
    - Recent closed-lost/won deals with lost_reason
    - MEDDICC scores at time of close

    Answers: 'why did we lose?', 'what did we win?',
    'win/loss summary', 'why are we losing?'
    """
    tw = params["time_window"]
    deal_ids = params.get("deal_ids", [])

    # 1. Check for AI-generated narratives first
    narratives = select_all(sb, "win_loss_narratives",
        columns="company_name,outcome,stated_reason,"
                "competitor_mentioned,key_factors,"
                "narrative,generated_at",
        filters=[("gte", "generated_at", tw["start"])])

    # 2. Get recent closed deals regardless
    # Base filters for closed deals
    deal_filters = [
        ("in_", "deal_status", ["won", "lost"]),
        ("gte", "close_date", tw["start"]),
        ("lte", "close_date", tw["end"]),
    ]
    if deal_ids:
        deal_filters.append(("in_", "deal_id", deal_ids))

    closed_deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,"
                "deal_status,close_date,lost_reason,"
                "owner_email,segment",
        filters=deal_filters)
    closed_deals.sort(
        key=lambda x: x.get("close_date") or "",
        reverse=True)

    # 3. Get MEDDICC scores for closed deals
    deal_ids = [d["deal_id"] for d in closed_deals[:20]]
    analyses = []
    if deal_ids:
        analyses = select_all(sb, "analyses",
            columns="deal_id,overall_score,champion_score,"
                    "economic_buyer_score,competition_score,"
                    "pain_score,analyzed_at",
            filters=[("in_", "deal_id", deal_ids)])
        # Get latest analysis per deal
        latest = {}
        for a in sorted(analyses,
                        key=lambda x: x.get("analyzed_at",""),
                        reverse=True):
            if a["deal_id"] not in latest:
                latest[a["deal_id"]] = a
        analyses = list(latest.values())

    wins  = [d for d in closed_deals
             if d.get("deal_status") == "won"]
    losses = [d for d in closed_deals
              if d.get("deal_status") == "lost"]

    return {
        "narratives":    narratives,
        "wins":          wins,
        "losses":        losses,
        "win_count":     len(wins),
        "loss_count":    len(losses),
        "analyses":      analyses,
        "period":        tw["label"],
        "has_narratives": len(narratives) > 0,
        "data_quality_note": (
            "Lost reasons are blank for most deals — "
            "recommend making lost_reason a required field "
            "in HubSpot when marking deals Closed Lost."
        ) if losses and not any(
            d.get("lost_reason") for d in losses
        ) else None,
    }


async def query_objections(params: dict, sb) -> dict:
    """
    Top objections by category for the period from objections table.
    Returns counts by category, total, and unaddressed percentage.
    """
    tw = params["time_window"]
    rows = select_all(sb, "objections",
        columns="category,stage_when_raised,"
                "rep_response,company_name,extracted_at",
        filters=[("gte", "extracted_at", tw["start"])])

    by_cat = Counter(r["category"] for r in rows)
    unaddressed = [r for r in rows if not r["rep_response"]]

    return {
        "by_category":   dict(by_cat.most_common()),
        "total":         len(rows),
        "unaddressed":   len(unaddressed),
        "unaddressed_pct": round(
            len(unaddressed)/max(len(rows),1)*100, 1),
        "period": tw["label"],
    }


async def query_feature_gaps(params: dict, sb) -> dict:
    """
    Feature gaps by severity and competitor from feature_gaps table.
    Returns total, blockers, counts by category, and top competitors.
    """
    tw = params["time_window"]
    rows = select_all(sb, "feature_gaps",
        columns="category,severity,competitor_mentioned,"
                "feature_description,company_name,extracted_at",
        filters=[("gte", "extracted_at", tw["start"])])

    blockers = [r for r in rows if r["severity"]=="blocker"]
    by_cat   = Counter(r["category"] for r in rows)
    competitors = Counter(
        r["competitor_mentioned"] for r in rows
        if r["competitor_mentioned"])

    return {
        "total": len(rows),
        "blockers": len(blockers),
        "by_category": dict(by_cat.most_common()),
        "competitors_mentioned": dict(competitors.most_common(5)),
        "period": tw["label"],
    }


async def query_coverage(params: dict, sb) -> dict:
    """
    Pipeline coverage vs quota targets from rep_targets and deals tables.
    Returns coverage % for each target (company/team/rep level).
    """
    tw = params["time_window"]
    period_label = tw.get("label", "").replace(" ", "_")

    targets = select_all(sb, "rep_targets",
        columns="level,entity_name,role,metric,target_value",
        filters=[("eq", "period", period_label)])

    deals = select_all(sb, "deals",
        columns="deal_value,deal_status,stage,owner_email,"
                "pipeline_id,highest_stage_order_reached",
        filters=[("eq", "deal_status", "active")])

    # Only qualified deals (above threshold)
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_pipeline_config

    pipeline = get_pipeline_config()
    qual_threshold = pipeline.get("qualified_stage_order", 2)
    qualified = [d for d in deals
                 if (d.get("highest_stage_order_reached") or 0)
                    >= qual_threshold]

    total_pipeline = sum(
        d.get("deal_value") or 0 for d in qualified)

    coverage_rows = []
    for t in targets:
        tv = t["target_value"] or 0
        coverage_rows.append({
            "entity":   t["entity_name"],
            "level":    t["level"],
            "role":     t["role"],
            "metric":   t["metric"],
            "target":   tv,
            "pipeline": total_pipeline,
            "coverage": round(total_pipeline/max(tv,1)*100, 1),
        })

    return {
        "coverage": coverage_rows,
        "total_qualified_pipeline": total_pipeline,
        "period": tw["label"],
        "note": "Coverage = qualified pipeline / target. "
                "No targets set → run 'set [team] target'.",
    }


async def query_deal(params: dict, sb) -> dict:
    """
    Deep dive on a specific company's deal.
    Returns deal info, latest MEDDICC analysis, and objections.
    """
    company = params.get("company", "")

    # If no explicit company but entity context has one,
    # use the first company from context
    if not company and params.get("company_names"):
        company = params["company_names"][0]

    if not company:
        return {"error": "Company name required"}

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,"
                "deal_status,close_date,owner_email,"
                "highest_stage_order_reached,forecast_category")

    deal = next((d for d in deals
                 if company.lower() in
                    (d.get("company_name") or "").lower()), None)
    if not deal:
        return {"error": f"No deal found for '{company}'"}

    deal_id = deal["deal_id"]

    analyses = select_all(sb, "analyses",
        columns="overall_score,component_details,"
                "analyzed_at,status",
        filters=[("eq", "deal_id", deal_id)])
    analyses.sort(key=lambda x: x.get("analyzed_at",""),
                  reverse=True)
    latest = analyses[0] if analyses else {}

    objections = select_all(sb, "objections",
        columns="category,verbatim_quote,rep_response",
        filters=[("eq", "company_name", deal["company_name"])])

    # Check for deal-specific analysis file
    from pathlib import Path
    import sys
    REPO_ROOT = Path(__file__).parent.parent
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from utils import slugify

    company_slug = slugify(deal["company_name"])
    output_file = REPO_ROOT / "memory" / "analyses" / f"{company_slug}.md"

    result = {
        "deal": deal,
        "latest_analysis": latest,
        "objections": objections,
    }

    if output_file.exists():
        content = output_file.read_text()[:3000]
        result["deal_specific_next_steps"] = content
        result["next_steps_source"] = "deal_analysis"
    else:
        # Fall back to rubric bands
        from api.rubric import get_band, get_next_steps
        from api.db import unpack_jsonb
        component_details = unpack_jsonb(latest.get("component_details"), {})
        for component, data in component_details.items():
            if isinstance(data, dict):
                score = data.get("score", 0)
                data["band"] = get_band(component, score)
                data["next_steps"] = get_next_steps(component, score)
        result["next_steps_source"] = "rubric_fallback"

    return result


async def query_rubric(params: dict, sb) -> dict:
    """
    General rubric questions like 'what does a 6 mean for champion?'
    Returns band descriptions and next steps guidance.
    """
    from api.rubric import RUBRIC, get_band, get_next_steps, get_band_description

    # Extract component and score from params if specified
    # Otherwise return full rubric
    component = params.get("component")
    score = params.get("score")

    if component and score is not None:
        # Specific component + score query
        band = get_band(component, score)
        description = get_band_description(component, score)
        next_steps = get_next_steps(component, score)

        return {
            "component": component,
            "score": score,
            "band": band,
            "description": description,
            "next_steps": next_steps,
        }
    elif component:
        # Just component, return all bands
        component_key = component.lower().replace(" ", "_")
        if component_key in RUBRIC:
            return {
                "component": component,
                "bands": RUBRIC[component_key]["bands"],
                "next_steps": RUBRIC[component_key]["next_steps"],
            }
        else:
            return {"error": f"Unknown component: {component}"}
    else:
        # General rubric query - return overview
        return {
            "rubric_overview": {
                comp: {
                    "bands": data["bands"],
                    "next_steps": data["next_steps"],
                }
                for comp, data in RUBRIC.items()
            }
        }


async def generate_win_loss(params: dict, sb) -> dict:
    """
    Full narrative for a specific closed deal (slow).
    Returns narrative if exists, otherwise returns component analysis.
    """
    company = params.get("company", "")
    if not company:
        return {"error": "Company name required for win/loss narrative"}

    rows = select_all(sb, "win_loss_narratives",
        columns="*",
        filters=[("ilike", "company_name", f"%{company}%")])
    if rows:
        return {"narrative": rows[0]}

    # No narrative yet — return the component analysis instead
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_status,close_date")
    deal = next((d for d in deals
                 if company.lower() in
                    (d.get("company_name") or "").lower()), None)
    if not deal:
        return {"error": f"No deal found for '{company}'"}

    analyses = select_all(sb, "analyses",
        columns="component_details,overall_score,status",
        filters=[("eq", "deal_id", deal["deal_id"])])

    return {
        "deal": deal,
        "analyses": analyses[-3:],
        "note": "No narrative generated yet — "
                "runs Sunday after close.",
    }


async def set_target(params: dict, sb) -> dict:
    """
    Admin: set quota target. Auth checked in router.
    Writes to rep_targets table with upsert on conflict.
    """
    entity  = params.get("entity_name", "")
    period  = params.get("period_label", "")
    metric  = params.get("metric", "total_arr")
    value   = params.get("target_value")
    role    = params.get("role")

    if not all([entity, period, value]):
        return {"error":
            "Need: entity name, period (e.g. Q3_FY2027), "
            "and value (e.g. $500K)"}

    # Determine level from entity name
    level = "rep" if "@" in entity else "team"

    # Parse value (handle $500K, $1.2M formats)
    value_str = str(value).replace("$","").replace(",","")
    if "K" in value_str.upper():
        value_float = float(value_str.upper().replace("K","")) * 1000
    elif "M" in value_str.upper():
        value_float = float(value_str.upper().replace("M","")) * 1000000
    else:
        value_float = float(value_str)

    sb.table("rep_targets").upsert({
        "period":       period,
        "level":        level,
        "entity_name":  entity,
        "role":         role,
        "metric":       metric,
        "target_value": value_float,
    }, on_conflict="period,level,entity_name,metric").execute()

    return {"set": True, "entity": entity,
            "period": period, "value": value_float}


async def query_new_deals(params: dict, sb) -> dict:
    """
    Deals created within the time window, from the
    deals table directly. Answers 'which deals were
    created this week/quarter/period?'
    """
    tw = params["time_window"]
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,"
                "owner_email,create_date,forecast_category,"
                "highest_stage_order_reached,pipeline_id",
        filters=[
            ("gte", "create_date", tw["start"]),
            ("lte", "create_date", tw["end"]),
        ])
    # Sort by value descending
    rows.sort(key=lambda x: x.get("deal_value") or 0,
              reverse=True)
    return {
        "new_deals": rows,
        "count": len(rows),
        "total_value": sum(
            r.get("deal_value") or 0 for r in rows),
        "period": tw["label"],
    }


# Vocabulary for build-vs-buy / DIY competition detection.
# Covers how prospects describe in-house alternatives.
COMPETITION_VOCAB = {
    "build_vs_buy": [
        "build", "built", "building", "in-house", "inhouse",
        "homegrown", "home-grown", "internal", "internally",
        "ourselves", "own platform", "own tool", "own solution",
        "DIY", "do it ourselves", "do it yourself",
        "vibe cod", "custom", "proprietary",
    ],
    "competitors": [
        "Statsig", "LaunchDarkly", "Optimizely", "Amplitude",
        "VWO", "Adobe Target", "Split.io", "Eppo",
        "Dr. Jekyll", "WISE", "Flagsmith", "Unleash",
    ],
    "evaluation": [
        "evaluating", "comparing", "looking at", "considering",
        "alternative", "instead of", "rather than",
        "competitive", "competitor",
    ],
    "deployment_preference": [
        "self-host", "self-hosted", "on-prem",
        "on-premise", "on premise", "our infrastructure",
        "our cloud", "data sovereignty",
    ],
}


async def query_competitive_intel(params: dict, sb) -> dict:
    """
    Search for competitive signals across all enrichment sources:
    objections, feature_gaps, win_loss_narratives, and MEDDICC
    competition scores in analyses.

    Handles questions like:
    - "have we come across DIY/build-it-yourself alternatives?"
    - "which companies mentioned building their own platform?"
    - "what competitors keep coming up?"
    - "where is Statsig showing up?"
    """
    tw = params["time_window"]
    search_term = params.get("search_term", "")

    # Build search vocabulary: a specific term (e.g. "Statsig", "DIY")
    # or the full build-vs-buy/competitor vocabulary
    vocab = [search_term] if search_term else (
        COMPETITION_VOCAB["build_vs_buy"] +
        COMPETITION_VOCAB["competitors"])

    # Internal calls (e.g. GrowthBook dogfooding/demo calls) get
    # ingested by the same enrichment pipeline — exclude them so
    # they don't read as external competitive signal.
    INTERNAL_COMPANIES = {"growthbook", "growth book"}

    # 1. Competitor mentions in feature_gaps (most structured data)
    comp_gaps = [r for r in select_all(sb, "feature_gaps",
        columns="company_name,competitor_mentioned,"
                "feature_description,severity,category")
        if r.get("competitor_mentioned")]
    comp_gaps = [r for r in comp_gaps
                 if (r.get("company_name") or "").lower()
                 not in INTERNAL_COMPANIES]

    # 2. Objections whose verbatim quote matches the vocabulary
    all_objections = select_all(sb, "objections",
        columns="company_name,category,verbatim_quote,"
                "rep_response,stage_when_raised")
    all_objections = [r for r in all_objections
                      if (r.get("company_name") or "").lower()
                      not in INTERNAL_COMPANIES]
    matching_objections = []
    for obj in all_objections:
        quote = (obj.get("verbatim_quote") or "").lower()
        if any(term.lower() in quote for term in vocab):
            matching_objections.append(obj)

    # 3. Win/loss narratives that mention the vocabulary
    narratives = select_all(sb, "win_loss_narratives",
        columns="company_name,outcome,stated_reason,"
                "competitor_mentioned,narrative")
    matching_narratives = []
    for n in narratives:
        text = " ".join(filter(None, [
            n.get("stated_reason", ""),
            n.get("narrative", ""),
            n.get("competitor_mentioned", ""),
        ])).lower()
        if any(term.lower() in text for term in vocab):
            matching_narratives.append(n)
    matching_narratives = [r for r in matching_narratives
                           if (r.get("company_name") or "").lower()
                           not in INTERNAL_COMPANIES]

    # Self-hosting / on-prem mentions are a GrowthBook deployment
    # option, not a build-vs-buy competitive signal — surface them
    # separately so they don't get counted as competitive objections.
    self_host_signals = [
        obj for obj in all_objections
        if any(t.lower() in
               (obj.get("verbatim_quote") or "").lower()
               for t in
               COMPETITION_VOCAB["deployment_preference"])
    ]

    # 4. Deals with a low MEDDICC competition score, for context
    low_comp_deals = select_all(sb, "analyses",
        columns="deal_id,company_name,competition_score,"
                "component_details,analyzed_at",
        filters=[("lte", "competition_score", 4)])
    low_comp_deals.sort(
        key=lambda x: x.get("analyzed_at", ""), reverse=True)

    competitor_counts = Counter(
        r["competitor_mentioned"] for r in comp_gaps
        if r.get("competitor_mentioned"))

    return {
        "competitor_mentions_in_gaps": comp_gaps[:20],
        "competitor_counts": dict(competitor_counts.most_common(10)),
        "build_vs_buy_objections": matching_objections,
        "narrative_mentions": matching_narratives,
        "low_competition_score_deals": low_comp_deals[:10],
        "search_vocab_used": vocab[:5],
        "self_host_signals": self_host_signals,
        "self_host_note": (
            "Self-hosting mentions are GrowthBook deployment "
            "discussions, not build-vs-buy objections."
        ) if self_host_signals else None,
        "period": tw["label"],
    }


async def query_won_deals(params: dict, sb) -> dict:
    """
    Deals that closed as won in the time window.
    Answers: 'what did we win?', 'show me our wins',
             'which deals closed won this quarter?'
    """
    tw = params["time_window"]
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,"
                "owner_email,close_date,forecast_category,"
                "new_arr,expansion_arr",
        filters=[
            ("eq",  "deal_status", "won"),
            ("gte", "close_date",  tw["start"]),
            ("lte", "close_date",  tw["end"]),
        ])
    rows.sort(
        key=lambda x: x.get("deal_value") or 0,
        reverse=True)
    return {
        "rows": rows,
        "count": len(rows),
        "total_value": sum(
            r.get("deal_value") or 0 for r in rows),
        "period": tw["label"],
    }

async def query_rubric_scores_bulk(params: dict, sb) -> dict:
    """MEDDICC scores for a known set of deal_ids.
    Used by entity-scoped follow-up questions like
    'what are the meddicc scores for these deals?'"""
    deal_ids = params["deal_ids"]
    rows = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,economic_buyer_score,"
                "decision_criteria_score,"
                "decision_process_score,competition_score,"
                "pain_score,analyzed_at",
        filters=[("in", "deal_id", deal_ids)])
    return {"scores": rows, "deal_count": len(deal_ids),
            "scored_count": len(rows)}

async def query_deal_stages_bulk(params: dict, sb) -> dict:
    """Current stage for a known set of deal_ids."""
    # Fix A2: Handle both entity-scope path (has deal_ids) and
    # direct intent path (may not have deal_ids)
    deal_ids = params.get("deal_ids", [])
    if not deal_ids:
        return {
            "stages": [],
            "error": "No deal IDs provided. This handler requires a list of specific deals."
        }

    rows = select_all(sb, "deals",
        columns="deal_id,company_name,stage,"
                "highest_stage_order_reached,close_date",
        filters=[("in_", "deal_id", deal_ids)])
    return {"stages": rows}

async def query_deal_owners_bulk(params: dict, sb) -> dict:
    """Owner for a known set of deal_ids."""
    deal_ids = params["deal_ids"]
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email",
        filters=[("in", "deal_id", deal_ids)])
    return {"owners": rows}

async def query_deal_values_bulk(params: dict, sb) -> dict:
    """ARR/value for a known set of deal_ids."""
    deal_ids = params["deal_ids"]
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,"
                "arr_usd,new_arr,expansion_arr",
        filters=[("in", "deal_id", deal_ids)])
    total = sum(r.get("arr_usd") or 0 for r in rows)
    return {"values": rows, "total_arr": total}

# ============================================================================
# SDR METRICS HANDLERS
# ============================================================================

async def query_sdr_pipeline_sourced(params: dict, sb) -> dict:
    """
    Pipeline attributed to SDRs/BDRs via configured attribution field.

    Uses sdr_owner_email field populated from HubSpot's attribution field
    (configured in client.yaml sdr_tools.pipeline_attribution.sdr_field).

    For GrowthBook: uses 'bdr_owner' field to track deals sourced by BDRs,
    even after handoff to AEs.
    """
    import yaml
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))

    tw = params["time_window"]
    sdr_email = params.get("sdr_email")  # Optional: filter to specific SDR

    # Get attribution method from config
    attribution_config = config.get("sdr_tools", {}).get("pipeline_attribution", {})
    attribution_method = attribution_config.get("method", "current_owner")
    sdr_field = attribution_config.get("sdr_field", "")

    # Build filters based on attribution method
    filters = [
        ("eq", "deal_status", "active"),  # Only active deals
    ]

    if attribution_method == "sdr_field" and sdr_field:
        # Use dedicated SDR attribution field (captures post-handoff deals)
        filters.append(("not.is", "sdr_owner_email", "null"))
        if sdr_email:
            filters.append(("eq", "sdr_owner_email", sdr_email))
    else:
        # Fall back to current owner (pre-handoff only)
        if sdr_email:
            filters.append(("eq", "owner_email", sdr_email))
        # Note: This will miss deals that have been handed off from SDR to AE

    # Query deals table
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,owner_email,sdr_owner_email,create_date",
        filters=filters
    )

    # Group by SDR email
    by_sdr = {}
    for row in rows:
        sdr = row.get("sdr_owner_email") if attribution_method == "sdr_field" else row.get("owner_email")
        if not sdr:
            continue
        if sdr not in by_sdr:
            by_sdr[sdr] = {
                "sdr_email": sdr,
                "deals": [],
                "total_pipeline": 0,
                "deal_count": 0
            }
        by_sdr[sdr]["deals"].append(row)
        by_sdr[sdr]["total_pipeline"] += row.get("deal_value") or 0
        by_sdr[sdr]["deal_count"] += 1

    # Convert to list and sort by pipeline value
    sdr_summary = sorted(by_sdr.values(), key=lambda x: x["total_pipeline"], reverse=True)

    return {
        "sdr_pipeline": sdr_summary,
        "attribution_method": attribution_method,
        "attribution_field": sdr_field if attribution_method == "sdr_field" else "current_owner",
        "total_sdr_pipeline": sum(s["total_pipeline"] for s in sdr_summary),
        "total_sdr_deals": sum(s["deal_count"] for s in sdr_summary),
        "period": tw["label"],
        "note": (
            "Post-handoff deals included via SDR attribution field"
            if attribution_method == "sdr_field"
            else "Only includes deals currently owned by SDRs (pre-handoff)"
        )
    }


async def query_sdr_metrics(params: dict, sb) -> dict:
    """
    SDR activity metrics for individual rep.

    Returns call volume, voicemails, connect rate (if available),
    email activity from sdr_metrics table.
    """
    sdr_email = params.get("sdr_email")
    tw = params["time_window"]

    if not sdr_email:
        return {
            "error": "No SDR email provided",
            "note": "This handler requires a specific SDR email address"
        }

    # Get user's tool_user_id from sdr_users table
    user_rows = select_all(sb, "sdr_users",
        columns="tool,tool_user_id,user_name,user_email",
        filters=[("eq", "user_email", sdr_email)]
    )

    if not user_rows:
        return {
            "error": f"No SDR metrics found for {sdr_email}",
            "note": "User may not be in sdr_users table or email doesn't match"
        }

    # Get metrics for this user across all tools
    metrics_rows = []
    for user in user_rows:
        tool = user.get("tool")
        tool_user_id = user.get("tool_user_id")

        tool_metrics = select_all(sb, "sdr_metrics",
            columns="tool,metric_date,calls_made,connected_calls,connect_rate,voicemails,"
                   "emails_sent,emails_opened,emails_replied,open_rate,reply_rate,data_gap",
            filters=[
                ("eq", "tool", tool),
                ("eq", "tool_user_id", tool_user_id),
                ("gte", "metric_date", tw["start"]),
                ("lte", "metric_date", tw["end"])
            ]
        )
        metrics_rows.extend(tool_metrics)

    # Aggregate across date range
    total_calls = sum(m.get("calls_made") or 0 for m in metrics_rows)
    total_voicemails = sum(m.get("voicemails") or 0 for m in metrics_rows)
    total_emails = sum(m.get("emails_sent") or 0 for m in metrics_rows)

    # Query meetings data
    meetings_rows = select_all(sb, "meetings",
        columns="scheduled_at,held,held_confidence,title",
        filters=[
            ("eq", "owner_email", sdr_email),
            ("gte", "scheduled_at", tw["start"]),
            ("lte", "scheduled_at", tw["end"])
        ]
    )

    # Meetings breakdown: Fireflies can confirm held but not no-shows
    booked = len(meetings_rows)
    fireflies_confirmed = sum(1 for m in meetings_rows
                              if m.get("held") is True
                              and m.get("held_confidence") == "fireflies_match")
    hs_confirmed = sum(1 for m in meetings_rows
                       if m.get("held_confidence") == "hs_outcome")
    unknown_outcome = sum(1 for m in meetings_rows if m.get("held") is None)

    # Query rep targets for current quarter
    # Determine which quarter the time window is in
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter
    import yaml

    # Load fiscal config
    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))
    cfg_wrap = {"fiscal": config.get("fiscal", {})}

    # Get the fiscal quarter for the start of the time window
    from datetime import date
    start_date = date.fromisoformat(tw["start"])
    _, _, quarter_label = get_fiscal_quarter(start_date, cfg_wrap)
    quarter_period = quarter_label.replace(" ", "_")  # e.g. "Q3_FY2027"

    # Query targets for this quarter
    target_rows = select_all(sb, "rep_targets",
        columns="metric,target_value",
        filters=[
            ("eq", "entity_email", sdr_email),
            ("eq", "period", quarter_period)
        ]
    )

    # Build target dict
    targets_raw = {t.get("metric"): t.get("target_value") for t in target_rows}

    # Prorate monthly targets if time window is monthly
    period_type = params.get("time_window", {}).get("period", "")
    is_monthly = period_type in ["current_month", "previous_month"]

    if is_monthly and targets_raw:
        # Monthly target = quarterly target / 3
        target_booked = int(targets_raw.get("meetings_booked", 0) / 3) if "meetings_booked" in targets_raw else None
        target_held = int(targets_raw.get("meetings_held", 0) / 3) if "meetings_held" in targets_raw else None
        target_sqls = int(targets_raw.get("sqls_created", 0) / 3) if "sqls_created" in targets_raw else None
    else:
        # Use full quarterly targets
        target_booked = targets_raw.get("meetings_booked")
        target_held = targets_raw.get("meetings_held")
        target_sqls = targets_raw.get("sqls_created")

    # Build list-friendly summary structures for bullet point rendering
    calls_summary = [
        {"label": "Calls made", "value": str(total_calls) if total_calls > 0 else None,
         "gap_reason": "No call data" if total_calls == 0 else None},
        {"label": "Connect rate", "value": None,
         "gap_reason": "Apollo calls API does not expose answered status"},
        {"label": "Voicemails", "value": str(total_voicemails) if total_voicemails > 0 else "0"}
    ]

    meetings_summary = [
        {"label": "Meetings booked", "value": str(booked), "target": str(target_booked) if target_booked else None},
        {"label": "Confirmed held (Fireflies)", "value": str(fireflies_confirmed)},
        {"label": "Unknown outcome", "value": str(unknown_outcome),
         "note": "could be held, no-show, or cancelled"}
    ]

    # Show rate data gap message
    show_rate_gap_message = (
        f"{fireflies_confirmed} meetings confirmed held via Fireflies. "
        f"{unknown_outcome} meetings have unknown outcome — Fireflies "
        f"absence doesn't confirm no-show. Show rate requires HubSpot "
        f"outcome field to be populated."
    )

    return {
        "sdr_email": sdr_email,
        "period": tw["label"],
        "calls_summary": calls_summary,
        "meetings_summary": meetings_summary,
        "show_rate_gap": show_rate_gap_message,
        "targets": {
            "meetings_booked": target_booked,
            "meetings_held": target_held,
            "sqls_created": target_sqls,
            "period": quarter_period,
            "prorated_monthly": is_monthly
        },
        "raw_data": {
            "metrics": metrics_rows,
            "meetings": meetings_rows
        }
    }


async def query_sdr_leaderboard(params: dict, sb) -> dict:
    """
    Team-wide SDR activity overview.

    Returns aggregated call and email metrics for all SDRs,
    sorted by activity level.
    """
    tw = params["time_window"]

    # Get all SDR metrics for time window
    metrics_rows = select_all(sb, "sdr_metrics",
        columns="tool,tool_user_id,user_name,metric_date,"
               "calls_made,connected_calls,voicemails,"
               "emails_sent,emails_opened,emails_replied",
        filters=[
            ("gte", "metric_date", tw["start"]),
            ("lte", "metric_date", tw["end"])
        ]
    )

    # Group by user (tool + tool_user_id)
    by_user = {}
    for row in metrics_rows:
        user_key = f"{row.get('tool')}:{row.get('tool_user_id')}"
        if user_key not in by_user:
            by_user[user_key] = {
                "user_name": row.get("user_name"),
                "tool": row.get("tool"),
                "calls_made": 0,
                "voicemails": 0,
                "emails_sent": 0
            }
        by_user[user_key]["calls_made"] += row.get("calls_made") or 0
        by_user[user_key]["voicemails"] += row.get("voicemails") or 0
        by_user[user_key]["emails_sent"] += row.get("emails_sent") or 0

    # Get all SDR users to map tool_user_id to email
    all_sdr_users = select_all(sb, "sdr_users",
        columns="tool,tool_user_id,user_email"
    )

    # Build tool_user_id → email mapping
    user_email_map = {
        f"{u.get('tool')}:{u.get('tool_user_id')}": u.get('user_email')
        for u in all_sdr_users
    }

    # Get meetings data for all SDRs
    meetings_rows = select_all(sb, "meetings",
        columns="owner_email,held",
        filters=[
            ("gte", "scheduled_at", tw["start"]),
            ("lte", "scheduled_at", tw["end"])
        ]
    )

    # Aggregate meetings by owner
    meetings_by_owner = {}
    for m in meetings_rows:
        owner = m.get("owner_email")
        if not owner:
            continue
        if owner not in meetings_by_owner:
            meetings_by_owner[owner] = {"booked": 0, "held": 0}
        meetings_by_owner[owner]["booked"] += 1
        if m.get("held") is True:
            meetings_by_owner[owner]["held"] += 1

    # Add meetings data to leaderboard
    for user_key, user_data in by_user.items():
        owner_email = user_email_map.get(user_key)

        if owner_email and owner_email in meetings_by_owner:
            user_data["meetings_booked"] = meetings_by_owner[owner_email]["booked"]
            user_data["meetings_held"] = meetings_by_owner[owner_email]["held"]
        else:
            user_data["meetings_booked"] = 0
            user_data["meetings_held"] = 0

    # Convert to list and sort by total activity
    leaderboard = sorted(
        by_user.values(),
        key=lambda x: x["calls_made"] + x["emails_sent"] + x.get("meetings_booked", 0),
        reverse=True
    )

    return {
        "leaderboard": leaderboard,
        "period": tw["label"],
        "team_summary": {
            "total_calls": sum(u["calls_made"] for u in leaderboard),
            "total_voicemails": sum(u["voicemails"] for u in leaderboard),
            "total_emails": sum(u["emails_sent"] for u in leaderboard),
            "total_meetings_booked": sum(u.get("meetings_booked", 0) for u in leaderboard),
            "total_meetings_held": sum(u.get("meetings_held", 0) for u in leaderboard)
        }
    }


# ============================================================================
# AE-FOCUSED HANDLERS
# ============================================================================

async def query_rep_pipeline(params: dict, sb) -> dict:
    """
    All active deals for a specific AE, sorted by deal value descending.
    Used for: "show me Christian's pipeline", "what deals does Cary own?"
    
    params:
      owner_email: str  — exact email from user_personas roster
      time_window: dict — optional, filters by close_date if provided
    """
    owner_email = params.get("owner_email")
    tw = params.get("time_window")
    
    if not owner_email:
        return {
            "error": "owner_email required — use the team roster to resolve a rep name to their email"
        }
    
    # Build filters for deals
    filters = [
        ("eq", "owner_email", owner_email),
        ("eq", "deal_status", "active")
    ]
    
    # Add time window filter if provided
    if tw:
        filters.append(("gte", "close_date", tw["start"]))
        filters.append(("lte", "close_date", tw["end"]))
    
    # Get active deals for this rep
    deals_rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,close_date,forecast_category",
        filters=filters
    )
    
    # Get latest analysis for each deal (left join)
    analyses_map = {}
    if deals_rows:
        deal_ids = [d["deal_id"] for d in deals_rows]
        # Get latest analysis per deal
        for deal_id in deal_ids:
            analyses = select_all(sb, "analyses",
                columns="deal_id,overall_score,champion_score",
                filters=[("eq", "deal_id", deal_id)]
            )
            if analyses:
                # Sort by analyzed_at (implicit - latest insert = latest)
                analyses_map[deal_id] = analyses[-1]
    
    # Enrich deals with analysis data
    enriched_deals = []
    total_pipeline = 0
    no_value_count = 0
    
    for deal in deals_rows:
        deal_id = deal["deal_id"]
        analysis = analyses_map.get(deal_id, {})
        
        deal_value = deal.get("deal_value")
        if deal_value is not None:
            total_pipeline += deal_value
        else:
            no_value_count += 1
        
        enriched_deals.append({
            "company_name": deal.get("company_name"),
            "deal_value": deal_value,
            "stage": deal.get("stage"),
            "close_date": deal.get("close_date"),
            "overall_score": analysis.get("overall_score"),
            "champion_score": analysis.get("champion_score"),
            "forecast_category": deal.get("forecast_category")
        })
    
    # Sort by deal_value descending, nulls last
    enriched_deals.sort(key=lambda x: (x["deal_value"] is None, -(x["deal_value"] or 0)))
    
    # Get persona name if available
    persona_rows = select_all(sb, "user_personas",
        columns="name,display_name",
        filters=[("eq", "email", owner_email)]
    )
    persona_name = None
    if persona_rows:
        persona_name = persona_rows[0].get("display_name") or persona_rows[0].get("name")
    
    avg_deal_value = total_pipeline / len([d for d in enriched_deals if d["deal_value"] is not None]) if enriched_deals and any(d["deal_value"] is not None for d in enriched_deals) else None
    
    return {
        "owner_email": owner_email,
        "owner_name": persona_name,
        "period": tw["label"] if tw else "all active",
        "deals": enriched_deals,
        "summary": {
            "total_deals": len(enriched_deals),
            "total_pipeline": total_pipeline,
            "avg_deal_value": avg_deal_value,
            "no_value_count": no_value_count
        },
        "data_gap": False
    }


async def query_rep_attainment(params: dict, sb) -> dict:
    """
    Quota attainment for one or all AEs this period.
    Used for: "who's on track to hit quota?", "show me Q3 attainment by rep",
              "which reps are above 50% to quota?", "who is furthest from their number?"
    
    params:
      owner_email: str or None  — if None, returns all reps
      time_window: dict         — determines which quarter to pull targets for
    """
    owner_email = params.get("owner_email")
    tw = params["time_window"]
    
    import yaml
    from pathlib import Path
    
    # Load fiscal config to build period label
    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))
    cfg_wrap = {"fiscal": config.get("fiscal", {})}
    
    # Get fiscal quarter label from time window start date
    from datetime import date
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter
    
    start_date = date.fromisoformat(tw["start"])
    _, _, quarter_label = get_fiscal_quarter(start_date, cfg_wrap)
    period = quarter_label.replace(" ", "_")  # e.g. "Q3_FY2027"
    
    # Load rep targets for this period
    target_filters = [
        ("eq", "period", period),
        ("eq", "level", "rep"),
        ("eq", "role", "ae")
    ]
    
    target_rows = select_all(sb, "rep_targets",
        columns="entity_email,target_value,metric",
        filters=target_filters
    )
    
    # Build target map
    targets_by_email = {}
    for t in target_rows:
        if t.get("metric") == "arr_won":  # or appropriate metric name
            targets_by_email[t["entity_email"]] = t["target_value"]
    
    # If no targets found, return data gap
    if not targets_by_email:
        return {
            "period": period,
            "reps": [],
            "team_summary": {
                "total_won": 0,
                "total_target": 0,
                "team_attainment": {"value": None, "data_gap": True},
                "reps_above_50pct": 0,
                "reps_above_100pct": 0
            },
            "note": "AE quotas not set — run seed_rep_targets.py or ask Ryan to set quotas for this period"
        }
    
    # Load won deals in time window
    won_filters = [
        ("eq", "deal_status", "won"),
        ("gte", "close_date", tw["start"]),
        ("lte", "close_date", tw["end"])
    ]
    
    won_rows = select_all(sb, "deals",
        columns="owner_email,deal_value",
        filters=won_filters
    )
    
    # Group won deals by owner
    won_by_email = {}
    for deal in won_rows:
        owner = deal.get("owner_email")
        value = deal.get("deal_value") or 0
        if owner:
            won_by_email[owner] = won_by_email.get(owner, 0) + value
    
    # Get all unique rep emails (union of targets and won)
    all_rep_emails = set(targets_by_email.keys()) | set(won_by_email.keys())
    
    # Filter to specific rep if requested
    if owner_email:
        all_rep_emails = {owner_email} if owner_email in all_rep_emails else set()
    
    # Load persona names
    persona_map = {}
    if all_rep_emails:
        persona_rows = select_all(sb, "user_personas",
            columns="email,display_name,name",
            filters=[]
        )
        for p in persona_rows:
            email = p.get("email")
            persona_map[email] = p.get("display_name") or p.get("name")
    
    # Build rep attainment list
    reps = []
    total_won = 0
    total_target = 0
    reps_above_50 = 0
    reps_above_100 = 0
    
    for email in all_rep_emails:
        target = targets_by_email.get(email)
        won = won_by_email.get(email, 0)
        
        attainment = rate_or_gap(won, target)
        attainment_pct = attainment.get("value")
        
        # Count won deals for this rep
        deals_won = len([d for d in won_rows if d.get("owner_email") == email])
        
        reps.append({
            "owner_email": email,
            "name": persona_map.get(email),
            "target": target,
            "won_arr": won,
            "attainment": attainment,
            "attainment_pct": attainment_pct,
            "deals_won": deals_won,
            "data_gap": target is None
        })
        
        total_won += won
        if target:
            total_target += target
        
        if attainment_pct and attainment_pct >= 50:
            reps_above_50 += 1
        if attainment_pct and attainment_pct >= 100:
            reps_above_100 += 1
    
    # Sort by attainment ascending (lowest first)
    reps.sort(key=lambda x: (x["attainment_pct"] is None, x["attainment_pct"] or 0))
    
    team_attainment = rate_or_gap(total_won, total_target)
    
    return {
        "period": period,
        "reps": reps,
        "team_summary": {
            "total_won": total_won,
            "total_target": total_target,
            "team_attainment": team_attainment,
            "reps_above_50pct": reps_above_50,
            "reps_above_100pct": reps_above_100
        }
    }


async def query_deal_health(params: dict, sb) -> dict:
    """
    MEDDICC health filter across a rep's deals or the full team.
    Used for: "show me Christian's weakest deals",
              "which deals have no champion identified?",
              "which deals closing this month have a score below 5?",
              "show me deals where pain is identified but metrics aren't"
    
    params:
      owner_email: str or None    — filter to one rep, or None for team
      score_threshold: int        — overall_score below this (default 5)
      component: str or None      — filter on a specific component
                                    e.g. "champion", "economic_buyer"
      component_threshold: int    — component score below this (default 4)
      time_window: dict or None   — filter close_date if provided
    """
    owner_email = params.get("owner_email")
    score_threshold = params.get("score_threshold", 5)
    component = params.get("component")
    component_threshold = params.get("component_threshold", 4)
    tw = params.get("time_window")
    
    # Valid components
    valid_components = [
        "champion", "economic_buyer", "metrics", "decision_criteria",
        "decision_process", "pain", "competition"
    ]
    
    if component and component not in valid_components:
        component = None
    
    # Get all analyses with overall_score below threshold
    analyses_filters = [
        ("lt", "overall_score", score_threshold)
    ]
    
    # Add component filter if specified
    if component:
        component_col = f"{component}_score"
        analyses_filters.append(("lt", component_col, component_threshold))
    
    analyses_rows = select_all(sb, "analyses",
        columns=f"deal_id,overall_score,champion_score,economic_buyer_score,metrics_score,decision_criteria_score,decision_process_score,pain_score,competition_score",
        filters=analyses_filters
    )
    
    if not analyses_rows:
        return {
            "filter_applied": {
                "owner": owner_email or "all reps",
                "score_threshold": score_threshold,
                "component": component,
                "close_window": tw["label"] if tw else None
            },
            "deals": [],
            "summary": {
                "total_at_risk": 0,
                "total_pipeline_at_risk": 0,
                "avg_score": None
            }
        }
    
    # Get deal IDs from analyses
    deal_ids = [a["deal_id"] for a in analyses_rows]
    
    # Get corresponding deals
    deals_filters = [
        ("eq", "deal_status", "active"),
        ("in", "deal_id", ",".join(deal_ids))
    ]
    
    if owner_email:
        deals_filters.append(("eq", "owner_email", owner_email))
    
    if tw:
        deals_filters.append(("gte", "close_date", tw["start"]))
        deals_filters.append(("lte", "close_date", tw["end"]))
    
    deals_rows = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email,close_date,deal_value",
        filters=deals_filters
    )
    
    # Join analyses to deals
    analyses_map = {a["deal_id"]: a for a in analyses_rows}
    
    enriched_deals = []
    total_pipeline_at_risk = 0
    scores = []
    
    for deal in deals_rows:
        deal_id = deal["deal_id"]
        analysis = analyses_map.get(deal_id)
        
        if not analysis:
            continue
        
        # Find weakest component
        component_scores = {
            "champion": analysis.get("champion_score"),
            "economic_buyer": analysis.get("economic_buyer_score"),
            "metrics": analysis.get("metrics_score"),
            "decision_criteria": analysis.get("decision_criteria_score"),
            "decision_process": analysis.get("decision_process_score"),
            "pain": analysis.get("pain_score"),
            "competition": analysis.get("competition_score")
        }
        
        valid_scores = {k: v for k, v in component_scores.items() if v is not None}
        weakest_component = min(valid_scores, key=valid_scores.get) if valid_scores else None
        weakest_score = valid_scores.get(weakest_component) if weakest_component else None
        
        enriched_deals.append({
            "company_name": deal.get("company_name"),
            "owner_email": deal.get("owner_email"),
            "overall_score": analysis.get("overall_score"),
            "champion_score": analysis.get("champion_score"),
            "economic_buyer_score": analysis.get("economic_buyer_score"),
            "close_date": deal.get("close_date"),
            "deal_value": deal.get("deal_value"),
            "weakest_component": weakest_component,
            "weakest_score": weakest_score
        })
        
        if deal.get("deal_value"):
            total_pipeline_at_risk += deal["deal_value"]
        
        scores.append(analysis.get("overall_score"))
    
    # Sort by overall_score ascending, then close_date ascending
    enriched_deals.sort(key=lambda x: (x["overall_score"], x["close_date"] or "9999-99-99"))
    
    avg_score = sum(scores) / len(scores) if scores else None
    
    return {
        "filter_applied": {
            "owner": owner_email or "all reps",
            "score_threshold": score_threshold,
            "component": component,
            "close_window": tw["label"] if tw else None
        },
        "deals": enriched_deals,
        "summary": {
            "total_at_risk": len(enriched_deals),
            "total_pipeline_at_risk": total_pipeline_at_risk,
            "avg_score": avg_score
        }
    }


async def query_stale_deals(params: dict, sb) -> dict:
    """
    Deals with no stage movement or past close date.
    Used for: "which deals have been in the same stage for 30+ days?",
              "show me deals stuck in Technical Evaluation",
              "which of Cary's deals haven't moved?",
              "show me deals past their close date"
    
    params:
      owner_email: str or None
      stage: str or None          — filter to a specific stage name
      stale_days: int             — deals in same stage longer than this (default 21)
      time_window: dict or None
    """
    owner_email = params.get("owner_email")
    stage = params.get("stage")
    stale_days = params.get("stale_days", 21)
    tw = params.get("time_window")
    
    import yaml
    from datetime import date, timedelta
    
    # Load config for reporting timezone
    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))
    
    today = today_in_reporting_tz(config)
    stale_cutoff = (today - timedelta(days=stale_days)).isoformat()
    
    # Get active deals
    filters = [("eq", "deal_status", "active")]
    
    if owner_email:
        filters.append(("eq", "owner_email", owner_email))
    
    if stage:
        filters.append(("eq", "stage", stage))
    
    if tw:
        filters.append(("gte", "close_date", tw["start"]))
        filters.append(("lte", "close_date", tw["end"]))
    
    deals_rows = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email,stage,close_date,deal_value,last_analyzed,updated_at",
        filters=filters
    )
    
    # Get latest analysis for each deal
    analyses_map = {}
    if deals_rows:
        deal_ids = [d["deal_id"] for d in deals_rows]
        for deal_id in deal_ids:
            analyses = select_all(sb, "analyses",
                columns="deal_id,overall_score",
                filters=[("eq", "deal_id", deal_id)]
            )
            if analyses:
                analyses_map[deal_id] = analyses[-1]
    
    # Filter stale and past-close deals
    stale_deals = []
    past_close_count = 0
    stale_count = 0
    total_stale_pipeline = 0
    
    for deal in deals_rows:
        # Use last_analyzed or updated_at as activity proxy
        activity_date = deal.get("last_analyzed") or deal.get("updated_at")
        is_stale = False
        is_past_close = False
        days_since_activity = None
        
        if activity_date:
            try:
                # Parse activity date and make it timezone-aware for comparison
                activity_dt = datetime.fromisoformat(activity_date.replace('Z', '+00:00'))
                if activity_dt.tzinfo is None:
                    activity_dt = activity_dt.replace(tzinfo=timezone.utc)
                days_since_activity = (datetime.now(timezone.utc) - activity_dt).days
                is_stale = activity_date < stale_cutoff
            except:
                pass
        
        close_date = deal.get("close_date")
        if close_date:
            try:
                close_dt = date.fromisoformat(close_date)
                is_past_close = close_dt < today
            except:
                pass
        
        if is_stale or is_past_close:
            analysis = analyses_map.get(deal["deal_id"], {})
            
            stale_deals.append({
                "company_name": deal.get("company_name"),
                "owner_email": deal.get("owner_email"),
                "stage": deal.get("stage"),
                "close_date": close_date,
                "deal_value": deal.get("deal_value"),
                "days_since_activity": days_since_activity,
                "is_past_close_date": is_past_close,
                "overall_score": analysis.get("overall_score")
            })
            
            if is_past_close:
                past_close_count += 1
            if is_stale:
                stale_count += 1
            
            if deal.get("deal_value"):
                total_stale_pipeline += deal["deal_value"]
    
    return {
        "stale_deals": stale_deals,
        "past_close_date_count": past_close_count,
        "stale_count": stale_count,
        "total_stale_pipeline": total_stale_pipeline,
        "stale_threshold_days": stale_days
    }


async def query_team_leaderboard(params: dict, sb) -> dict:
    """
    Full AE team ranking across pipeline, attainment, and deal quality.
    Used for: "show me the team leaderboard", "rank the AEs by pipeline",
              "who's carrying the team?", "who has the most pipeline closing this quarter?"
    
    params:
      time_window: dict
      sort_by: str — "pipeline" | "attainment" | "meddicc_score" | "deals_won"
                     default: "pipeline"
      limit: int   — default 10
    """
    tw = params["time_window"]
    sort_by = params.get("sort_by", "pipeline")
    limit = params.get("limit", 10)
    
    import yaml
    from datetime import date
    
    # Load fiscal config
    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))
    cfg_wrap = {"fiscal": config.get("fiscal", {})}
    
    # Get period label
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter
    
    start_date = date.fromisoformat(tw["start"])
    _, _, quarter_label = get_fiscal_quarter(start_date, cfg_wrap)
    period = quarter_label.replace(" ", "_")
    
    # Get all active deals (grouped by owner)
    active_deals = select_all(sb, "deals",
        columns="owner_email,deal_value",
        filters=[("eq", "deal_status", "active")]
    )
    
    # Get won deals in time window (grouped by owner)
    won_deals = select_all(sb, "deals",
        columns="owner_email,deal_value",
        filters=[
            ("eq", "deal_status", "won"),
            ("gte", "close_date", tw["start"]),
            ("lte", "close_date", tw["end"])
        ]
    )
    
    # Get targets for this period
    targets = select_all(sb, "rep_targets",
        columns="entity_email,target_value,metric",
        filters=[
            ("eq", "period", period),
            ("eq", "level", "rep"),
            ("eq", "role", "ae")
        ]
    )
    
    # Get all personas
    personas = select_all(sb, "user_personas",
        columns="email,display_name,name",
        filters=[]
    )
    
    # Build rep aggregations
    rep_data = {}
    
    # Active pipeline
    for deal in active_deals:
        owner = deal.get("owner_email")
        if not owner:
            continue
        if owner not in rep_data:
            rep_data[owner] = {}
        if "active_pipeline" not in rep_data[owner]:
            rep_data[owner]["active_pipeline"] = 0
            rep_data[owner]["active_deals"] = 0
        if deal.get("deal_value"):
            rep_data[owner]["active_pipeline"] += deal["deal_value"]
        rep_data[owner]["active_deals"] += 1
    
    # Won ARR
    for deal in won_deals:
        owner = deal.get("owner_email")
        if not owner:
            continue
        if owner not in rep_data:
            rep_data[owner] = {}
        if "won_arr" not in rep_data[owner]:
            rep_data[owner]["won_arr"] = 0
        if deal.get("deal_value"):
            rep_data[owner]["won_arr"] += deal["deal_value"]
    
    # Quotas
    targets_map = {}
    for t in targets:
        if t.get("metric") == "arr_won":
            targets_map[t["entity_email"]] = t["target_value"]
    
    for email, quota in targets_map.items():
        if email not in rep_data:
            rep_data[email] = {}
        rep_data[email]["quota"] = quota
    
    # Personas
    persona_map = {}
    for p in personas:
        email = p.get("email")
        persona_map[email] = p.get("display_name") or p.get("name")
    
    # Build leaderboard
    leaderboard = []
    team_total_pipeline = 0
    team_won_arr = 0
    data_gaps = []
    
    for email, data in rep_data.items():
        active_pipeline = data.get("active_pipeline")
        active_deals = data.get("active_deals")
        won_arr = data.get("won_arr")
        quota = data.get("quota")
        
        # Calculate attainment if quota exists
        attainment = None
        if quota and won_arr is not None:
            attainment = rate_or_gap(won_arr, quota)
        elif won_arr is not None and quota is None:
            attainment = None  # No quota set
        
        leaderboard.append({
            "owner_email": email,
            "name": persona_map.get(email),
            "active_pipeline": active_pipeline,
            "active_deals": active_deals,
            "won_arr": won_arr,
            "quota": quota,
            "attainment": attainment,
            "avg_meddicc_score": None,  # TODO: aggregate from rep_performance if exists
            "deals_analyzed": None
        })
        
        if active_pipeline:
            team_total_pipeline += active_pipeline
        if won_arr:
            team_won_arr += won_arr
    
    # Check for data gaps
    if not targets_map:
        data_gaps.append("quotas not set")
    
    # Sort leaderboard
    sort_keys = {
        "pipeline": lambda x: (x["active_pipeline"] is None, -(x["active_pipeline"] or 0)),
        "attainment": lambda x: (x["attainment"] is None, -(x["attainment"].get("value") if x["attainment"] else 0)),
        "meddicc_score": lambda x: (x["avg_meddicc_score"] is None, -(x["avg_meddicc_score"] or 0)),
        "deals_won": lambda x: (x["won_arr"] is None, -(x["won_arr"] or 0))
    }
    
    leaderboard.sort(key=sort_keys.get(sort_by, sort_keys["pipeline"]))
    
    # Add rank
    for i, rep in enumerate(leaderboard[:limit], 1):
        rep["rank"] = i
    
    return {
        "period": period,
        "sort_by": sort_by,
        "leaderboard": leaderboard[:limit],
        "team_total_pipeline": team_total_pipeline,
        "team_won_arr": team_won_arr,
        "data_gaps": data_gaps
    }
