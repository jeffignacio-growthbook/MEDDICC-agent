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

# Import field semantics (single source of truth for stage meanings)
try:
    from field_semantics import stage_bucket, stage_label, is_won, is_lost, is_open
except ImportError:
    from api.field_semantics import stage_bucket, stage_label, is_won, is_lost, is_open

# Import renewal handlers (separated for clarity)
try:
    from api.handlers_renewal import query_upcoming_renewals
except ImportError:
    from handlers_renewal import query_upcoming_renewals


# overall_score is the SUM of the 7 MEDDICC components (0-10 each) — max 70,
# NOT 100. See hubspot_deals._extract_scores_from_analysis. Anything that
# surfaces overall_score to the synthesis layer should carry this denominator
# so the model never has to guess the scale (it guessed /100 for LiveSport,
# turning a 38/70 = 54% deal into a "38/100, relatively weak" one).
MEDDICC_OVERALL_MAX = 70
MEDDICC_COMPONENT_MAX = 10


def _labeled_overall(score):
    """Return overall_score with its denominator and percentage, or None."""
    try:
        s = int(score)
    except (TypeError, ValueError):
        return None
    return {"score": s, "max": MEDDICC_OVERALL_MAX,
            "pct": round(s / MEDDICC_OVERALL_MAX * 100),
            "display": f"{s}/{MEDDICC_OVERALL_MAX}"}


def _resolve_tw(params: dict) -> dict:
    """Return a resolved time window, defaulting to the current quarter.

    The router always injects params['time_window'], but a handler must never
    KeyError on a missing param: a raise drops the whole request to the dynamic
    loop, which burns the query budget and returns nothing useful (the most
    common user-visible failure in this system). Guarding here keeps every
    time-scoped handler answerable even when called directly or under test.
    """
    tw = params.get("time_window")
    if tw:
        return tw
    try:
        from api.time_resolver import resolve_time_window
    except ImportError:
        from time_resolver import resolve_time_window
    return resolve_time_window({})


def _resolve_owner_email(params: dict, sb):
    """Resolve a rep to an owner_email, accepting an email OR a person's name.

    The classifier is asked to turn a first name into an email via the roster,
    but that resolution silently fails when the roster is empty (personas not
    seeded) or the name is partial — the handler then gets a name where it
    wanted an ID, errors, and drops to the budget-burning dynamic loop. This
    resolves in-handler against user_personas so a rep's first name, full name,
    or email all work.

    Returns (email_or_None, note_or_None). `note` explains a name→email
    resolution or a miss, for transparency in the handler's output.
    """
    # 1. An email supplied under any of the known keys wins outright.
    for key in ("owner_email", "rep_email", "sdr_email", "email"):
        v = params.get(key)
        if v and "@" in str(v):
            return str(v).strip().lower(), None

    # 2. Otherwise gather any name-ish candidate the classifier may have passed.
    candidates = []
    for key in ("owner_email", "rep_email", "sdr_email", "email",
                "rep_name", "owner_name", "sdr_name", "name",
                "rep", "owner", "sdr"):
        v = params.get(key)
        if v and "@" not in str(v):
            candidates.append(str(v).strip())
    if not candidates:
        return None, None

    try:
        personas = select_all(sb, "user_personas",
                              columns="email,name,display_name")
    except Exception:
        personas = []

    for cand in candidates:
        cl = cand.lower().strip()
        if not cl:
            continue
        for p in personas:
            for nm in (p.get("name"), p.get("display_name")):
                nml = str(nm or "").lower().strip()
                if not nml:
                    continue
                first = nml.split()[0] if nml.split() else nml
                if cl == nml or cl == first or cl in nml:
                    if p.get("email"):
                        return p["email"], f"resolved '{cand}' to {p['email']}"
    return None, f"could not resolve '{candidates[0]}' to a known rep"


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

    tw = _resolve_tw(params)
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

    tw = _resolve_tw(params)
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

        # Check each required component. Band comparison, not integer: a 5-vs-6
        # gap is noise the generator can't reproduce (both yellow), so a
        # component is only "at risk" when its BAND is below the gate's band —
        # gate 6 → needs yellow-or-better, gate 7 → green-or-better.
        from api.rubric import band_meets, band_label, get_band
        risk_flags = []
        for component, required_threshold in requirements.items():
            field_name = component_fields.get(component)
            if not field_name:
                continue

            actual_score = a.get(field_name)

            if not band_meets(component, actual_score, required_threshold):
                # Stage-aware risk message, in band language (the integer is
                # internal — surfacing "5/10" invites arguing the number
                # instead of the gap).
                from api.stage_requirements import _get_stage_by_id
                stage_info = _get_stage_by_id(stage_id)
                stage_name = stage_info["name"] if stage_info else "current stage"
                lbl = band_label(component, actual_score)
                need_band = get_band(component, required_threshold)

                risk_flags.append(
                    f"{component.replace('_', ' ').title()} is {lbl['text']} "
                    f"(needs {need_band}-or-better to advance from {stage_name})"
                )

        # Only flag if there are actual risk flags
        if risk_flags:
            at_risk.append({
                "deal_id":       a["deal_id"],
                "company_name":  a["company_name"],
                "overall_score": a.get("overall_score", 0) or 0,
                "champion_band": band_label("champion", a.get("champion_score"))["text"],
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
    tw = _resolve_tw(params)
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
    tw = _resolve_tw(params)
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
    tw = _resolve_tw(params)
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
    tw = _resolve_tw(params)
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

    # Band is the surfaced signal (the 0-10 integer is internal precision the
    # generator can't reproduce run-to-run). Attach bands to every component
    # regardless of which next-steps path we take, and lift a compact
    # {component: band-text} map to the top level so synthesis leads with bands.
    from api.rubric import band_label
    from api.db import unpack_jsonb
    component_details = unpack_jsonb(latest.get("component_details"), {})
    meddicc_bands = {}
    for component, data in component_details.items():
        if isinstance(data, dict):
            lbl = band_label(component, data.get("score"))
            data["band"] = lbl["band"]
            data["band_label"] = lbl["text"]
            data["borderline"] = lbl["borderline"]
            meddicc_bands[component] = lbl["text"]
    if meddicc_bands:
        result["meddicc_bands"] = meddicc_bands

    if output_file.exists():
        content = output_file.read_text()[:3000]
        result["deal_specific_next_steps"] = content
        result["next_steps_source"] = "deal_analysis"
    else:
        # Fall back to rubric next-steps coaching (bands already attached).
        from api.rubric import get_next_steps
        for component, data in component_details.items():
            if isinstance(data, dict):
                data["next_steps"] = get_next_steps(component, data.get("score", 0))
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
    tw = _resolve_tw(params)
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
    tw = _resolve_tw(params)
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
    tw = _resolve_tw(params)
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
    """MEDDICC scores for a set of deals.

    Two entry paths:
      * entity-scoped follow-up ("what are the MEDDICC scores for these deals?")
        passes deal_ids from prior thread context;
      * a direct question naming a company ("score the LiveSport deal on
        MEDDICC") passes `company` — we resolve it to its deal(s) here.

    Resolving the company in-handler answers the question in one call. Before
    this, a company-named question routed here had no deal_ids, raised
    KeyError('deal_ids'), fell through to the dynamic loop, and burned the query
    budget — surfacing a "Hit query budget with partial data" message even
    though the deal and its scores were right there. Never raises on a missing
    key now; returns a clear error instead.
    """
    deal_ids = list(params.get("deal_ids") or [])
    resolved_from_company = False
    # A CRO routinely asks about several companies in one question
    # ("Ecco, Zalando, Natera, and DEUNA"). Accept a LIST — companies /
    # company_names — as well as the single `company`. Resolve each via ilike
    # and UNION the deal_ids. No cap: if fifteen are named, answer about fifteen.
    companies = []
    for v in (params.get("companies"), params.get("company_names")):
        if isinstance(v, str):
            companies.append(v)
        elif isinstance(v, (list, tuple)):
            companies.extend(v)
    if params.get("company"):
        companies.append(params["company"])
    # de-dup company strings, preserve order
    seen_c, deduped = set(), []
    for c in companies:
        c = str(c).strip()
        if c and c.lower() not in seen_c:
            seen_c.add(c.lower())
            deduped.append(c)
    companies = deduped

    resolved_companies = []
    if not deal_ids and companies:
        resolved_from_company = True
        seen_ids = set()
        for c in companies:
            matches = select_all(sb, "deals", columns="deal_id,company_name",
                filters=[("ilike", "company_name", f"%{c}%")])
            if matches:
                resolved_companies.append(c)
            for d in matches:
                if d["deal_id"] not in seen_ids:
                    seen_ids.add(d["deal_id"])
                    deal_ids.append(d["deal_id"])

    if not deal_ids:
        return {"scores": [], "deal_count": 0, "scored_count": 0,
                "queried_deal_ids": [], "queried_companies": companies,
                "error": "No deal IDs provided and no company to resolve. "
                         "Name a deal (e.g. 'score the Acme deal on MEDDICC'), "
                         "one or more companies, or a specific set of deals."}

    rows = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,metrics_score,"
                "champion_score,economic_buyer_score,"
                "decision_criteria_score,"
                "decision_process_score,competition_score,"
                "pain_score,analyzed_at,component_details",
        filters=[("in_", "deal_id", deal_ids)])

    # Keep the latest analysis per deal — the current MEDDICC state — rather
    # than every historical scoring row (LiveSport had 5).
    latest = {}
    for a in rows:
        did = a.get("deal_id")
        if (did not in latest or
                str(a.get("analyzed_at") or "") > str(latest[did].get("analyzed_at") or "")):
            latest[did] = a
    scores = list(latest.values())
    # Label every score with its denominator so synthesis can't guess the
    # scale, AND attach the per-component band — the band is what we surface,
    # the 0-10 integer is internal (the generator reproduces a component's band
    # run-to-run but not its exact integer). Synthesis leads with bands.
    from api.rubric import meddicc_bands as _meddicc_bands
    _cols = {"metrics": "metrics_score", "economic_buyer": "economic_buyer_score",
             "decision_criteria": "decision_criteria_score",
             "decision_process": "decision_process_score", "pain": "pain_score",
             "champion": "champion_score", "competition": "competition_score"}
    import json as _json
    for s in scores:
        s["overall"] = _labeled_overall(s.get("overall_score"))
        # Per-component EVIDENCE — the fact behind the score. Without it,
        # synthesis fills the gap with generic template language ("identify who
        # has a personal stake") that names nothing about the deal. Pull it from
        # analyses.component_details ({component: {score, evidence}}); expose a
        # clean {component: evidence_string_or_None} map, and drop the raw blob.
        cd = s.pop("component_details", None)
        if isinstance(cd, str):
            try:
                cd = _json.loads(cd)
            except Exception:
                cd = None
        cd = cd or {}
        s["evidence"] = {}
        for c in _cols:
            cell = cd.get(c) if isinstance(cd.get(c), dict) else {}
            ev = (cell.get("evidence") or "").strip()
            s["evidence"][c] = ev or None

        # UNREAD vs RED. A component at 0 with NO evidence was never discussed —
        # "not yet assessed", not "clearly absent". A component at 0 WITH
        # evidence ("no champion identified on the call") is a real red. The band
        # (red=0-3) can't tell them apart, so a rep skimming sees red and reads
        # "problem". Route the never-discussed ones through the band function as
        # None so they render as the distinct `unread` band, and mark status so
        # synthesis can list them separately and not sort them to the top by a 0.
        band_input, s["status"] = {}, {}
        for c, col in _cols.items():
            sc = s.get(col)
            unread = (sc in (0, None)) and not s["evidence"][c]
            band_input[c] = None if unread else sc
            s["status"][c] = "unread" if unread else "assessed"
        s["bands"] = {c: lbl["text"] for c, lbl in
                      _meddicc_bands(band_input).items()}
        s["unread_components"] = [c for c in _cols if s["status"][c] == "unread"]
    # Deals we looked up but that have no analysis row yet — so synthesis can say
    # truthfully "these N were scored, these M haven't been analyzed" instead of
    # inventing a reason (the entity-scope path was confabulating "not scored
    # yet" / "no call activity logged" here).
    scored_ids = {s.get("deal_id") for s in scores}
    unscored_deal_ids = [d for d in deal_ids if d not in scored_ids]
    return {"scores": scores, "deal_count": len(deal_ids),
            "scored_count": len(scores),
            "resolved_from_company": resolved_from_company,
            "queried_deal_ids": deal_ids,
            "queried_companies": companies,
            "resolved_companies": resolved_companies,
            "unscored_deal_ids": unscored_deal_ids,
            "scale": {"overall_max": MEDDICC_OVERALL_MAX,
                      "component_max": MEDDICC_COMPONENT_MAX,
                      "note": "Surface the per-component BAND (red/yellow/green "
                              "in `bands`), not the raw /10 — the integer is "
                              "internal precision the generator can't reproduce "
                              "run-to-run. overall_score is the sum of 7 "
                              "components (0-70), secondary to the bands."}}

_MEDDICC_COMPONENT_KEYS = {
    "metrics": "metrics", "metric": "metrics",
    "economic_buyer": "economic_buyer", "economic buyer": "economic_buyer",
    "eb": "economic_buyer",
    "decision_criteria": "decision_criteria", "decision criteria": "decision_criteria",
    "criteria": "decision_criteria",
    "decision_process": "decision_process", "decision process": "decision_process",
    "process": "decision_process",
    "pain": "pain", "identified_pain": "pain", "identify_pain": "pain",
    "champion": "champion",
    "competition": "competition", "competitor": "competition",
}


async def submit_score_correction(params: dict, sb) -> dict:
    """Capture a rep's disagreement with a MEDDICC component score (Part 7).

    A REVIEW QUEUE, not a live edit: this writes to score_corrections and does
    NOT change any score. The agent proposes, a human disposes — same discipline
    as the proposals table. Purpose: a rep who can push back stops treating the
    tool as an accusation, and we accumulate labelled examples of where the
    generator is wrong.

    Never raises on a missing param — returns a clear error dict instead.
    """
    raw_component = str(params.get("component") or "").strip().lower()
    component = _MEDDICC_COMPONENT_KEYS.get(raw_component)
    proposed = params.get("proposed_score")
    reason = str(params.get("correction_reason") or params.get("reason") or "").strip()

    if not component:
        return {"logged": False,
                "error": "Name the MEDDICC component you're correcting (metrics, "
                         "economic buyer, decision criteria, decision process, "
                         "pain, champion, or competition)."}
    try:
        proposed_score = int(proposed)
    except (TypeError, ValueError):
        return {"logged": False, "component": component,
                "error": "Give the score you think it should be, 0-10 "
                         "(e.g. 'champion should be 7')."}
    if not (0 <= proposed_score <= 10):
        return {"logged": False, "component": component,
                "error": "Proposed score must be between 0 and 10."}
    if not reason:
        return {"logged": False, "component": component,
                "error": "Add a one-line reason — the evidence for the higher/lower "
                         "score is what makes the correction useful."}

    # Resolve the deal (by company name) and the current score, if we can.
    company = (params.get("company")
               or (params.get("company_names") or [None])[0])
    deal_id = None
    company_name = company
    current_score = None
    if company:
        matches = select_all(sb, "deals", columns="deal_id,company_name",
            filters=[("ilike", "company_name", f"%{str(company).strip()}%")])
        if matches:
            deal_id = matches[0]["deal_id"]
            company_name = matches[0].get("company_name") or company
            rows = select_all(sb, "analyses",
                columns=f"deal_id,{component}_score,analyzed_at,passed",
                filters=[("eq", "deal_id", deal_id)])
            passed = [r for r in rows if r.get("passed")]
            passed.sort(key=lambda r: str(r.get("analyzed_at") or ""), reverse=True)
            if passed:
                current_score = passed[0].get(f"{component}_score")

    row = {
        "deal_id": deal_id, "company_name": company_name,
        "component": component, "current_score": current_score,
        "proposed_score": proposed_score, "reason": reason,
        "submitted_by": params.get("submitted_by"), "status": "proposed",
    }
    try:
        sb.table("score_corrections").insert(
            {k: v for k, v in row.items() if v is not None}).execute()
    except Exception as e:
        return {"logged": False, "component": component,
                "error": f"Couldn't log the correction: {e}"}

    return {
        "logged": True,
        "correction": {"component": component, "current_score": current_score,
                       "proposed_score": proposed_score,
                       "company_name": company_name, "reason": reason},
        "note": ("Logged to the review queue. This does NOT change the score "
                 "automatically — a human reviews corrections before anything "
                 "is adjusted. Thanks for the pushback; it's how the scoring "
                 "gets better."),
    }


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
                "highest_stage_order_reached,close_date,segment",
        filters=[("in_", "deal_id", deal_ids)])
    return {"stages": rows}

async def query_deal_owners_bulk(params: dict, sb) -> dict:
    """Owner for a known set of deal_ids."""
    deal_ids = params.get("deal_ids") or []
    if not deal_ids:
        return {"owners": [],
                "error": "No deal IDs provided. This handler requires a "
                         "specific set of deals."}
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email,segment",
        filters=[("in_", "deal_id", deal_ids)])
    return {"owners": rows}

async def query_deal_values_bulk(params: dict, sb) -> dict:
    """ARR/value for a known set of deal_ids."""
    deal_ids = params.get("deal_ids") or []
    if not deal_ids:
        return {"values": [], "total_arr": 0,
                "error": "No deal IDs provided. This handler requires a "
                         "specific set of deals."}
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,"
                "arr_usd,new_arr,expansion_arr,segment",
        filters=[("in_", "deal_id", deal_ids)])
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

    tw = _resolve_tw(params)
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
        # Use dedicated SDR attribution field (captures post-handoff deals).
        # select_all's "not null" operator is "__not_null__" (→ .not_.is_(col,
        # "null")). The old "not.is" op was not one select_all understands —
        # getattr(q, "not.is") raised AttributeError against Supabase too,
        # dropping this handler into the budget-burning dynamic loop whenever
        # sdr_field attribution was configured.
        filters.append(("__not_null__", "sdr_owner_email"))
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
    tw = _resolve_tw(params)

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

    # Meetings breakdown: Call recordings can confirm held but not no-shows
    booked = len(meetings_rows)
    call_recording_confirmed = sum(1 for m in meetings_rows
                              if m.get("held") is True
                              and m.get("held_confidence") == "call_recording_match")
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
        {"label": "Confirmed held (recording)", "value": str(call_recording_confirmed)},
        {"label": "Unknown outcome", "value": str(unknown_outcome),
         "note": "could be held, no-show, or cancelled"}
    ]

    # Show rate data gap message
    show_rate_gap_message = (
        f"{call_recording_confirmed} meetings confirmed held via call recording. "
        f"{unknown_outcome} meetings have unknown outcome — absence of recording "
        f"doesn't confirm no-show. Show rate requires HubSpot "
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
    tw = _resolve_tw(params)

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
    tw = params.get("time_window")

    # Accept an email OR a rep name (first / full / display). The classifier is
    # supposed to resolve names to emails via the roster, but that fails
    # silently when personas aren't seeded or the name is partial — which is
    # exactly what dropped "show me Christian's pipeline" into the dynamic loop
    # and burned the query budget. Resolve in-handler so a name always works.
    owner_email, resolved_note = _resolve_owner_email(params, sb)

    if not owner_email:
        return {
            "error": "Couldn't resolve that to a rep. Name a rep by first name, "
                     "full name, or email (e.g. \"show me Christian's pipeline\"). "
                     "If the name is right, that person may not be in the "
                     "user_personas roster yet.",
            "resolution_note": resolved_note,
            "deals": [],
            "summary": {"total_deals": 0, "total_pipeline": 0,
                        "avg_deal_value": None, "no_value_count": 0},
            "data_gap": True,
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
        "resolution_note": resolved_note,
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
    # A rep name resolves to owner_email; None means "all reps" (valid here).
    owner_email, _rep_note = _resolve_owner_email(params, sb)
    tw = _resolve_tw(params)

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
    # A rep name resolves to owner_email; None means "all reps" (valid here).
    owner_email, _rep_note = _resolve_owner_email(params, sb)
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
    # A rep name resolves to owner_email; None means "all reps" (valid here).
    owner_email, _rep_note = _resolve_owner_email(params, sb)
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
    tw = _resolve_tw(params)
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


# ==========================================================================
# COACHING HANDLERS
# Pre-call brief, coaching priorities, and call quality review
# ==========================================================================

async def query_pre_call_brief(params: dict, sb) -> dict:
    """
    Pre-call intelligence brief for a specific deal.

    Answers: "prep me for my call with Skyscanner"
             "quick brief on the Stone deal before I jump on"
             "what should I focus on in my IKEA renewal?"

    Returns:
    - Current MEDDICC scores with weakest components flagged
    - Last 2 call summaries
    - Open objections from this deal with blocker type and prescribed response
    - Feature gaps logged for this deal
    - 3-5 specific questions to ask based on what's missing in MEDDICC
    - Blocker type if identifiable from the data

    params:
      company: str       — company name
      owner_email: str   — optional, for persona-aware framing
    """
    try:
        from .coaching_thresholds import COACHING_THRESHOLDS
    except ImportError:
        from coaching_thresholds import COACHING_THRESHOLDS

    # Load coaching config (seed + client merged)
    import sys
    from pathlib import Path
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    from coaching_config import load_coaching_config
    coaching_config = load_coaching_config()

    # 1. Resolve the deal
    company = params.get("company") or (params.get("company_names") or [""])[0]
    if not company:
        return {"error": "Company name required — e.g. 'prep me for Skyscanner'"}

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,stage,deal_value,arr_usd,"
                "owner_email,close_date,deal_status",
        filters=[("eq", "deal_status", "active")])
    deal = next((d for d in deals
                 if company.lower() in (d.get("company_name") or "").lower()), None)
    if not deal:
        return {"error": f"No active deal found for '{company}'"}

    deal_id = deal["deal_id"]
    company_name = deal["company_name"]

    # 2. Latest MEDDICC analysis — PASSED ONLY for trend integrity
    analyses = select_all(sb, "analyses",
        columns="overall_score,metrics_score,economic_buyer_score,"
                "decision_criteria_score,decision_process_score,"
                "pain_score,champion_score,competition_score,"
                "analyzed_at,passed,full_analysis_text",
        filters=[("eq", "deal_id", deal_id)])

    # Trends and latest score must use passed analyses only
    passed_analyses = [a for a in analyses if a.get("passed")]
    passed_analyses.sort(key=lambda x: x.get("analyzed_at", ""), reverse=True)

    # If no passed analysis exists, the deal has never been reliably scored
    if not passed_analyses:
        latest_analysis = {}
        reliable_score = False
        score_age_days = None
        score_is_stale = False
    else:
        latest_analysis = passed_analyses[0]
        reliable_score = True

        # Staleness: flag if score is older than threshold
        from datetime import datetime, timezone
        analyzed_at_str = latest_analysis.get("analyzed_at", "")
        if analyzed_at_str:
            analyzed_at = datetime.fromisoformat(analyzed_at_str.replace('Z', '+00:00'))
            score_age_days = (datetime.now(timezone.utc) - analyzed_at).days
            score_is_stale = score_age_days > COACHING_THRESHOLDS["stale_analysis_days"]
        else:
            score_age_days = None
            score_is_stale = False

    recent_analyses = passed_analyses[:6]

    # 3. Identify weakest MEDDICC components
    COMPONENTS = {
        "metrics_score": "Metrics",
        "economic_buyer_score": "Economic Buyer",
        "decision_criteria_score": "Decision Criteria",
        "decision_process_score": "Decision Process",
        "pain_score": "Pain",
        "champion_score": "Champion",
        "competition_score": "Competition",
    }
    scores = {
        label: latest_analysis.get(field)
        for field, label in COMPONENTS.items()
        if latest_analysis.get(field) is not None
    }
    sorted_scores = sorted(scores.items(), key=lambda x: x[1])
    weakest = sorted_scores[:3] if sorted_scores else []

    # Helper: compute trend across recent passed analyses (per-call framing)
    def _compute_trend(component_field: str) -> dict:
        """
        Compute trend for a MEDDICC component across recent passed analyses.
        Returns: {"direction": "improving"/"declining"/"stable", "span": "over 3 calls (Jan 5 - Feb 10)"}
        """
        values = [a.get(component_field) for a in recent_analyses if a.get(component_field) is not None]
        if len(values) < 2:
            return {"direction": "insufficient_data", "span": None}

        # Compute trend: compare first half vs second half average
        mid = len(values) // 2
        recent_avg = sum(values[:mid]) / mid if mid > 0 else values[0]
        older_avg = sum(values[mid:]) / len(values[mid:]) if len(values[mid:]) > 0 else values[-1]

        if recent_avg > older_avg + 0.5:
            direction = "improving"
        elif recent_avg < older_avg - 0.5:
            direction = "declining"
        else:
            direction = "stable"

        # Date span from oldest to newest analysis
        dates = [a.get("analyzed_at", "")[:10] for a in recent_analyses if a.get("analyzed_at")]
        if len(dates) >= 2:
            span = f"over {len(recent_analyses)} calls ({dates[-1]} to {dates[0]})"
        else:
            span = f"over {len(recent_analyses)} calls"

        return {"direction": direction, "span": span}

    # Compute trends for weakest components
    trends = {}
    if reliable_score:
        for component_label, _ in weakest[:3]:
            field_name = [k for k, v in COMPONENTS.items() if v == component_label]
            if field_name:
                trends[component_label] = _compute_trend(field_name[0])

    # 4. Last 2 call summaries
    calls = select_all(sb, "calls",
        columns="call_id,call_date,source,summary,title",
        filters=[("eq", "deal_id", deal_id)])
    calls.sort(key=lambda c: c.get("call_date", ""), reverse=True)
    recent_calls = [
        {
            "date": c.get("call_date", "")[:10],
            "title": c.get("title", ""),
            "source": c.get("source", ""),
            "summary": (c.get("summary") or "")[:600],
        }
        for c in calls[:2]
        if c.get("summary") and not c["summary"].startswith("[Summary failed]")
    ]

    # 5. Open objections for this deal (open = no rep_response)
    objections = select_all(sb, "objections",
        columns="category,verbatim_quote,rep_response,stage_when_raised",
        filters=[("eq", "company_name", company_name)])
    open_objections = [o for o in objections if not o.get("rep_response")]

    # Recurring objection categories (open objections only)
    from collections import Counter
    open_categories = [o.get("category") for o in open_objections if o.get("category")]
    recurring_objections = [cat for cat, count in Counter(open_categories).items() if count >= 2]

    # 6. Feature gaps for this deal
    gaps = select_all(sb, "feature_gaps",
        columns="feature_description,severity,category,competitor_mentioned",
        filters=[("eq", "deal_id", deal_id)])
    blockers = [g for g in gaps if g.get("severity") == "blocker"]

    # 7. Generate stage-aware focus questions based on weak components
    # Use canonical stage bucket from field_semantics (single source of truth)
    current_stage = deal.get("stage", "")
    current_bucket = stage_bucket(current_stage)

    # Stage-aware questions from coaching_client.yaml
    STAGE_COMPONENT_QUESTIONS = coaching_config.get("stage_focus_questions", {})

    # Select questions based on stage bucket
    focus_questions = []
    stage_questions = STAGE_COMPONENT_QUESTIONS.get(current_bucket, STAGE_COMPONENT_QUESTIONS["scoping"])
    for component_label, _ in weakest[:3]:
        qs = stage_questions.get(component_label, [])
        if qs:
            focus_questions.append({
                "weak_component": component_label,
                "questions": qs[:2],
            })

    # 8. Identify blocker type if inferable
    blocker_type = None
    blocker_prescribed_response = None
    if open_objections:
        # Map objection categories to blocker taxonomy (from config)
        BLOCKER_MAP = coaching_config.get("objection_category_to_blocker", {})
        obj_categories = [o.get("category", "") for o in open_objections]
        mapped = [BLOCKER_MAP.get(c) for c in obj_categories if BLOCKER_MAP.get(c)]
        if mapped:
            blocker_type = max(set(mapped), key=mapped.count)
            # Get prescribed response from blocker_taxonomy in seed
            blocker_taxonomy = coaching_config.get("blocker_taxonomy", {})
            blocker_def = blocker_taxonomy.get(blocker_type, {})
            blocker_prescribed_response = blocker_def.get("right_response")

    return {
        "company_name": company_name,
        "deal": {
            "deal_id": deal_id,  # Required for entity extraction
            "company_name": company_name,  # Required for entity extraction
            "stage": deal.get("stage"),
            "arr_usd": deal.get("arr_usd"),
            "close_date": deal.get("close_date"),
            "owner_email": deal.get("owner_email"),
        },
        "stage_context": {
            "current_stage": current_stage,
            "stage_bucket": current_bucket,
        },
        "meddicc": {
            "overall_score": latest_analysis.get("overall_score"),
            "analyzed_at": (latest_analysis.get("analyzed_at") or "")[:10],
            "reliable_score": reliable_score,
            "score_age_days": score_age_days,
            "score_is_stale": score_is_stale,
            "scores": scores,
            "weakest_components": [
                {"component": label, "score": score}
                for label, score in weakest
            ],
            "trends": trends,
        },
        "recent_calls": recent_calls,
        "open_objections": open_objections,
        "recurring_objections": recurring_objections,
        "blocker_type": blocker_type,
        "blocker_prescribed_response": blocker_prescribed_response,
        "blockers_logged": blockers,
        "focus_questions": focus_questions,
        "data_gap": not latest_analysis,
    }


async def query_coaching_priorities(params: dict, sb) -> dict:
    """
    Which deals and reps need coaching attention right now.

    Answers: "which reps need coaching this week?"
             "prep me for my 1:1 with Christian"
             "show me deals where discovery is incomplete"
             "which deals have a missing economic buyer?"
             "which of James's deals haven't had activity in 3 weeks?"

    Returns a prioritized list of deals needing attention with
    the specific reason for each, grouped by rep when no rep filter.

    params:
      owner_email: str   — filter to one rep (for 1:1 prep)
      time_window: dict  — for staleness calculation
      focus: str         — 'champion' | 'economic_buyer' | 'stale'
                           | 'objections' | 'all' (default: 'all')
    """
    try:
        from .coaching_thresholds import COACHING_THRESHOLDS
    except ImportError:
        from coaching_thresholds import COACHING_THRESHOLDS

    # A rep name resolves to owner_email; None means "all reps" (valid here).
    owner_email, _rep_note = _resolve_owner_email(params, sb)
    focus = params.get("focus", "all")
    from datetime import date, timedelta
    today = today_in_reporting_tz()
    stale_threshold = (today - timedelta(days=COACHING_THRESHOLDS["stale_call_days"])).isoformat()

    # Load active deals
    deal_filters = [("eq", "deal_status", "active")]
    if owner_email:
        deal_filters.append(("eq", "owner_email", owner_email))

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email,stage,"
                "deal_value,arr_usd,close_date",
        filters=deal_filters)

    if not deals:
        return {
            "priorities": [],
            "data_gap": True,
            "note": f"No active deals found{f' for {owner_email}' if owner_email else ''}",
        }

    deal_ids = [d["deal_id"] for d in deals]
    deal_map = {d["deal_id"]: d for d in deals}

    # Latest analysis per deal
    all_analyses = select_all(sb, "analyses",
        columns="deal_id,overall_score,champion_score,"
                "economic_buyer_score,decision_process_score,"
                "pain_score,analyzed_at,passed")
    # Keep only latest per deal
    latest_by_deal = {}
    for a in sorted(all_analyses, key=lambda x: x.get("analyzed_at", "")):
        latest_by_deal[a["deal_id"]] = a

    # Latest call date per deal
    all_calls = select_all(sb, "calls",
        columns="deal_id,call_date")
    latest_call_by_deal = {}
    for c in all_calls:
        did = c.get("deal_id")
        cd = c.get("call_date", "")
        if did and (did not in latest_call_by_deal or cd > latest_call_by_deal[did]):
            latest_call_by_deal[did] = cd

    # Open objections per deal
    all_objections = select_all(sb, "objections",
        columns="company_name,category,rep_response")
    open_obj_by_company = {}
    for o in all_objections:
        if not o.get("rep_response"):
            cn = o.get("company_name", "")
            open_obj_by_company.setdefault(cn, []).append(o.get("category", ""))

    # Build priority list
    priorities = []
    for deal in deals:
        deal_id = deal["deal_id"]
        analysis = latest_by_deal.get(deal_id, {})
        last_call = latest_call_by_deal.get(deal_id, "")
        open_objs = open_obj_by_company.get(deal["company_name"], [])

        flags = []

        # Check each coaching priority. Surface the BAND, not the /10 (the
        # integer is internal precision the generator can't reproduce).
        from api.rubric import band_label
        if focus in ("all", "economic_buyer"):
            eb = analysis.get("economic_buyer_score")
            if eb is not None and eb <= COACHING_THRESHOLDS["weak_component_max"]:
                flags.append({
                    "type": "missing_economic_buyer",
                    "detail": f"Economic buyer is {band_label('economic_buyer', eb)['text']} — not yet identified",
                    "urgency": "high" if (deal.get("close_date") or "") > today.isoformat() else "medium",
                })

        if focus in ("all", "champion"):
            ch = analysis.get("champion_score")
            if ch is not None and ch <= COACHING_THRESHOLDS["weak_component_max"]:
                flags.append({
                    "type": "weak_champion",
                    "detail": f"Champion is {band_label('champion', ch)['text']} — no internal advocate confirmed",
                    "urgency": "high",
                })

        if focus in ("all", "stale"):
            if last_call and last_call < stale_threshold:
                days_since = (today - date.fromisoformat(last_call)).days
                flags.append({
                    "type": "no_recent_activity",
                    "detail": f"Last call {days_since} days ago ({last_call})",
                    "urgency": "high" if days_since > COACHING_THRESHOLDS["critical_stale_days"] else "medium",
                })
            elif not last_call:
                flags.append({
                    "type": "no_calls_recorded",
                    "detail": "No call recordings found — deal may be dark",
                    "urgency": "medium",
                })

        if focus in ("all", "objections"):
            if open_objs:
                flags.append({
                    "type": "unaddressed_objections",
                    "detail": f"{len(open_objs)} open objection(s): {', '.join(set(open_objs))}",
                    "urgency": "medium",
                })

        # Strong score but stuck — potential coaching on closing
        overall = analysis.get("overall_score")
        if overall and overall >= COACHING_THRESHOLDS["strong_score_min"]:
            stage = deal.get("stage", "")
            if last_call and last_call < stale_threshold:
                flags.append({
                    "type": "strong_score_no_movement",
                    "detail": f"MEDDICC score {overall}/70 but no call in {(today - date.fromisoformat(last_call)).days} days — deal may be stalling",
                    "urgency": "high",
                })

        if flags:
            priorities.append({
                "company_name": deal["company_name"],
                "owner_email": deal.get("owner_email"),
                "stage": deal.get("stage"),
                "arr_usd": deal.get("arr_usd"),
                "close_date": deal.get("close_date"),
                "overall_score": analysis.get("overall_score"),
                "flags": flags,
                "flag_count": len(flags),
                "highest_urgency": "high" if any(f["urgency"] == "high" for f in flags) else "medium",
            })

    # Sort: high urgency first, then by ARR
    priorities.sort(key=lambda x: (
        0 if x["highest_urgency"] == "high" else 1,
        -(x.get("arr_usd") or 0)
    ))

    # Group by owner if no specific rep requested
    if not owner_email:
        by_owner = {}
        for p in priorities:
            owner = p.get("owner_email", "unknown")
            by_owner.setdefault(owner, []).append(p)

        # Cap deals per owner (top 5) and total deals (25)
        MAX_PER_OWNER = 5
        MAX_TOTAL = 25

        capped_by_owner = {}
        total_shown = 0
        truncated = False

        # Sort owners by total urgency (high count first, then deal count)
        sorted_owners = sorted(
            by_owner.items(),
            key=lambda x: (
                -sum(1 for d in x[1] if d["highest_urgency"] == "high"),
                -len(x[1])
            )
        )

        for owner, deals in sorted_owners:
            if total_shown >= MAX_TOTAL:
                truncated = True
                break

            # Take top N deals for this owner
            capped_deals = deals[:MAX_PER_OWNER]
            remaining_budget = MAX_TOTAL - total_shown

            # Mark as truncated if we capped this owner's deals
            if len(deals) > MAX_PER_OWNER:
                truncated = True

            if len(capped_deals) > remaining_budget:
                capped_deals = capped_deals[:remaining_budget]
                truncated = True

            capped_by_owner[owner] = capped_deals
            total_shown += len(capped_deals)

        # Final check: if we showed fewer deals than exist, mark as truncated
        if total_shown < len(priorities):
            truncated = True

        return {
            "by_owner": capped_by_owner,
            "total_deals_needing_attention": len(priorities),
            "deals_shown": total_shown,
            "high_urgency_count": sum(1 for p in priorities if p["highest_urgency"] == "high"),
            "truncated": truncated,
            "focus": focus,
        }

    # Single owner mode - cap to 25 deals
    MAX_DEALS = 25
    truncated = len(priorities) > MAX_DEALS

    return {
        "owner_email": owner_email,
        "priorities": priorities[:MAX_DEALS],
        "total": len(priorities),
        "deals_shown": min(len(priorities), MAX_DEALS),
        "high_urgency": sum(1 for p in priorities if p["highest_urgency"] == "high"),
        "truncated": truncated,
        "focus": focus,
    }


async def query_call_quality(params: dict, sb) -> dict:
    """
    Review what happened on a specific call and how good the discovery was.

    Answers: "how did the last Skyscanner call go?"
             "what happened on Christian's call with Stone?"
             "show me the quality of James's calls this month"
             "where is the team weak in discovery?"

    Two modes:
    - Single call review: company + optional date
    - Rep/team pattern: owner_email + time_window (no company)

    params:
      company: str         — specific company (single call mode)
      owner_email: str     — filter by rep
      time_window: dict    — for pattern mode
    """
    company = params.get("company") or (params.get("company_names") or [""])[0]
    owner_email = params.get("owner_email")
    tw = params.get("time_window", {})

    # Mode 1: Single call review for a specific company
    if company:
        # Find the deal
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,owner_email,stage")
        deal = next((d for d in deals
                     if company.lower() in
                        (d.get("company_name") or "").lower()), None)
        if not deal:
            return {"error": f"No deal found for '{company}'"}

        # Get recent calls with summaries
        calls = select_all(sb, "calls",
            columns="call_id,call_date,title,source,summary",
            filters=[("eq", "deal_id", deal["deal_id"])])
        calls.sort(key=lambda c: c.get("call_date", ""), reverse=True)
        recent = [c for c in calls[:3] if c.get("summary")]

        if not recent:
            return {
                "company_name": deal["company_name"],
                "data_gap": True,
                "note": "No call summaries found for this deal",
            }

        # Check for existing call quality scores
        quality_rows = select_all(sb, "call_quality",
            columns="call_date,overall_quality_score,quantification_score,"
                    "decision_process_score,numbers_obtained,numbers_missing,"
                    "blocker_type,strongest_moment,weakest_moment,pattern_flags",
            filters=[("eq", "deal_id", deal["deal_id"])])
        quality_rows.sort(key=lambda x: x.get("call_date", ""), reverse=True)

        # Get objections raised on this deal
        objections = select_all(sb, "objections",
            columns="category,verbatim_quote,rep_response,stage_when_raised",
            filters=[("eq", "company_name", deal["company_name"])])

        latest_call = recent[0]
        latest_quality = quality_rows[0] if quality_rows else {}

        return {
            "company_name": deal["company_name"],
            "owner_email": deal.get("owner_email"),
            "stage": deal.get("stage"),
            "latest_call": {
                "date": latest_call.get("call_date"),
                "title": latest_call.get("title"),
                "source": latest_call.get("source"),
                "summary": (latest_call.get("summary") or "")[:800],
            },
            "quality_score": latest_quality,
            "objections_raised": objections,
            "call_history_count": len(calls),
            "recent_call_count": len(recent),
        }

    # Mode 2: Rep or team discovery pattern
    filters = []
    if owner_email:
        filters.append(("eq", "owner_email", owner_email))
    if tw.get("start"):
        filters.append(("gte", "call_date", tw["start"]))
    if tw.get("end"):
        filters.append(("lte", "call_date", tw["end"]))

    quality_rows = select_all(sb, "call_quality",
        columns="owner_email,call_date,overall_quality_score,"
                "quantification_score,decision_process_score,"
                "numbers_missing,pattern_flags,blocker_type",
        filters=filters)

    if not quality_rows:
        return {
            "data_gap": True,
            "note": (
                "No call quality scores found. The call quality assessment "
                "runs as part of the enrichment pipeline — scores accumulate "
                "as new calls are processed."
            ),
            "owner_email": owner_email,
            "period": tw.get("label", ""),
        }

    # Aggregate patterns
    all_flags = []
    for row in quality_rows:
        flags = row.get("pattern_flags") or []
        if isinstance(flags, list):
            all_flags.extend(flags)

    flag_counts = Counter(all_flags)
    avg_score = (
        sum(r.get("overall_quality_score") or 0 for r in quality_rows) /
        max(len(quality_rows), 1)
    )

    # What discovery numbers are most commonly missing?
    missing_counts = Counter()
    for row in quality_rows:
        missing = row.get("numbers_missing") or []
        if isinstance(missing, list):
            for m in missing:
                missing_counts[m] += 1

    return {
        "owner_email": owner_email or "all reps",
        "period": tw.get("label", ""),
        "calls_assessed": len(quality_rows),
        "avg_quality_score": round(avg_score, 1),
        "most_common_gaps": dict(flag_counts.most_common(5)),
        "discovery_numbers_most_missed": dict(missing_counts.most_common(5)),
        "by_rep": (
            None if owner_email else
            {
                owner: {
                    "calls": len([r for r in quality_rows if r.get("owner_email") == owner]),
                    "avg_score": round(
                        sum(r.get("overall_quality_score") or 0
                            for r in quality_rows
                            if r.get("owner_email") == owner) /
                        max(len([r for r in quality_rows if r.get("owner_email") == owner]), 1),
                        1
                    ),
                }
                for owner in set(r.get("owner_email") for r in quality_rows if r.get("owner_email"))
            }
        ),
    }


# ============================================================================
# query_pipeline_movement — reads deals_snapshot directly (COUNTS ONLY)
# ============================================================================
# Makes the reconstructed historical substrate (24,160 deals_snapshot rows,
# FY2026 Q3–FY2027 Q2 backfilled + FY2027 Q3 forward) reachable from Slack.
#
# Scope discipline (see PIPELINE_MOVEMENT_HANDLER_SPEC.md):
#   * reads deals_snapshot ONLY — never calls forecast_analyses.py, which is
#     known-broken (the 7-site null-coalescing ledger + numerator/scope/
#     close-date bugs).
#   * COUNTS ONLY. deal_value is not even selected, so nothing can sum or
#     average it. Dollar movement is blocked until the ledger is worked off.
#   * scoping is applied AT READ TIME via the shared point_in_time functions
#     (the row set is deliberately written unscoped so GRR/NRR can read
#     renewals) and the scope used is reported in the output.
#   * null-stage rows are COUNTED as stage 'unknown', never dropped —
#     dropping them understates population, the defect this substrate fixes.
#   * the two weekday grids (backfilled=Monday vs forward=cron weekday) are
#     never silently mixed.

_PM_SNAPSHOT_COLUMNS = (
    # Only the columns the views actually use — deal_status and fiscal_quarter
    # (the latter is the filter, never read back) were dropped to shrink the
    # per-row payload the curve/composition views page through (Issue 5).
    "deal_id,snapshot_date,pipeline_id,stage_id,stage_order,"
    "close_date,owner_email,snapshot_source,"
    "backfill_confidence,week_of_quarter"
)
# deal_value is intentionally absent from the column list above. Counts only.

_PM_CONFIDENCE_KEYS = ("exact", "pre_history", "no_history")
_PM_VIEWS = ("movement", "composition", "deal_changes", "curve", "stage_deals")


def _pm_load_scoping():
    """Import the SHARED analytics-scoping functions (not reimplemented)."""
    analytics_dir = str(Path(__file__).parent.parent / "scripts" / "analytics")
    if analytics_dir not in sys.path:
        sys.path.insert(0, analytics_dir)
    # scripts/ is already on sys.path (top of this module), so the shared
    # module is importable as analytics.point_in_time — same path
    # eval_reconstruction.py uses.
    from analytics.point_in_time import (
        load_scope_config, is_deal_in_analytics_scope,
    )
    return load_scope_config, is_deal_in_analytics_scope


def _pm_current_quarter_label():
    """Current fiscal quarter in the stored column's format ('FY2027 Q3')."""
    from utils import get_fiscal_quarter
    _, _, label = get_fiscal_quarter()
    return label


def _pm_stage_name(stage_id, stage_cfg):
    if stage_id is None or not str(stage_id).strip():
        return "unknown"
    cfg = stage_cfg.get(str(stage_id))
    if cfg:
        return cfg["name"]
    # Unmapped stage at read time: degrade (label by id / field_semantics),
    # do not raise. Reconstruction raises on unclassifiable stages; a live
    # Slack handler degrades gracefully instead.
    try:
        return stage_label(str(stage_id))
    except Exception:
        return str(stage_id)


def _pm_stage_order(row, stage_cfg):
    so = row.get("stage_order")
    if so is not None:
        return so
    cfg = stage_cfg.get(str(row.get("stage_id")))
    return cfg["order"] if cfg else 9_999  # unknown sorts last


def _pm_in_scope(row, excluded_pipelines, stage_cfg, is_in_scope):
    """Read-time analytics scope.

    Delegates the stage judgement to the shared is_deal_in_analytics_scope;
    adds only the two deviations the spec mandates:
      - null-stage rows COUNT (returned as 'unknown'), rather than being
        dropped for lacking a stage;
      - Closed Won / Closed Lost are dropped explicitly (the shared function
        keeps them because their order is >= qualified; the spec lists them
        as excluded).
    """
    pid = row.get("pipeline_id")
    if pid is not None and str(pid) in excluded_pipelines:
        return False  # renewal / partner / marketing pipelines
    stage_id = row.get("stage_id")
    if stage_id is None or not str(stage_id).strip():
        return True   # null stage → counted downstream as 'unknown'
    try:
        if is_won(str(stage_id)) or is_lost(str(stage_id)):
            return False  # Closed Won / Closed Lost / Disqualified
    except Exception:
        pass
    return is_in_scope(str(stage_id), pid, excluded_pipelines, stage_cfg)


def _pm_confidence_mix(rows):
    mix = {k: 0 for k in _PM_CONFIDENCE_KEYS}
    for r in rows:
        c = r.get("backfill_confidence")
        if c in mix:
            mix[c] += 1
        else:
            mix["other"] = mix.get("other", 0) + 1
    return mix


def _pm_latest_row_per_deal(rows):
    """Collapse to one row per deal for a single snapshot date (PK is
    (deal_id, snapshot_date), so this is normally 1:1; guard duplicates)."""
    out = {}
    for r in rows:
        out[r["deal_id"]] = r
    return out


def _pm_by_date(scoped):
    by_date = {}
    for r in scoped:
        by_date.setdefault(r["snapshot_date"], []).append(r)
    return by_date


def _pm_stage_sets(date_rows, stage_cfg):
    """stage_name -> set(deal_id) and deal_id -> stage_name for one date."""
    stage_to_deals = {}
    deal_to_stage = {}
    for r in date_rows:
        name = _pm_stage_name(r.get("stage_id"), stage_cfg)
        stage_to_deals.setdefault(name, set()).add(r["deal_id"])
        deal_to_stage[r["deal_id"]] = name
    return stage_to_deals, deal_to_stage


def _pm_company_map(sb, deal_ids):
    """{deal_id: company_name} from the deals table for the given ids.

    deals_snapshot has no name column, so individual deals would otherwise be
    reported by opaque deal_id (Issue 2). Minimal join — only deal_id +
    company_name — chunked to keep the in_ filter URL bounded.
    """
    ids = sorted({str(d) for d in deal_ids if d is not None})
    out = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            drows = select_all(sb, "deals", columns="deal_id,company_name",
                               filters=[("in_", "deal_id", chunk)])
        except Exception:
            drows = []
        for r in drows:
            out[str(r["deal_id"])] = r.get("company_name")
    return out


def _pm_deal_rows(date_rows, stage_cfg, company_map=None, limit=200):
    """Entity-bearing rows for one snapshot date, so extract_entity_context
    can save deal_ids AND company_names for follow-up questions. Carries stage
    so a drill-down ('which of those are in Discovery?') has the context it
    needs, and company_name so deals are named, not shown as bare ids.

    Still COUNTS-ONLY: deal_value is neither selected nor emitted here.
    """
    company_map = company_map or {}
    rows = []
    for r in _pm_latest_row_per_deal(date_rows).values():
        did = r["deal_id"]
        rows.append({
            "deal_id": did,
            "company_name": company_map.get(str(did)),
            "stage": _pm_stage_name(r.get("stage_id"), stage_cfg),
            "owner_email": r.get("owner_email"),
            "close_date": r.get("close_date"),
            "week_of_quarter": r.get("week_of_quarter"),
            "backfill_confidence": r.get("backfill_confidence"),
        })
    rows.sort(key=lambda x: (x["stage"], str(x["deal_id"])))
    return rows[:limit]


def _pm_view_movement(by_date, all_dates, stage_cfg, data_gaps, requested_days=None, base=None):
    if len(all_dates) < 2:
        data_gaps.append(
            "movement needs two snapshot dates; found "
            f"{len(all_dates)} in this grid — returning null, not a zero"
        )
        return {
            "snapshot_dates": None,
            "by_stage": [],
            "totals": {"prior": None, "current": None, "net": None},
            "confidence": {},
            "summary": {},
            "current_position": None
        }

    # Select snapshots based on requested_days
    from datetime import date, timedelta

    current_date = all_dates[-1]  # Always use latest

    if requested_days:
        # Find snapshot on or before (current - requested_days)
        target_date = date.fromisoformat(current_date) - timedelta(days=requested_days)
        target_str = target_date.isoformat()

        # Find closest snapshot on or before target
        valid_prior = [d for d in all_dates if d <= target_str]
        if valid_prior:
            prior_date = valid_prior[-1]  # Closest to target
        else:
            # No snapshot old enough — use oldest available
            prior_date = all_dates[0]
            actual_days = (date.fromisoformat(current_date) - date.fromisoformat(prior_date)).days
            data_gaps.append(
                f"Requested {requested_days}-day window, but oldest snapshot is "
                f"{prior_date} ({actual_days} days). Comparing {actual_days} days "
                f"instead of {requested_days}."
            )
    else:
        # Default: use last two snapshots
        prior_date = all_dates[-2]

    # Check actual span
    actual_days = (date.fromisoformat(current_date) - date.fromisoformat(prior_date)).days
    if requested_days and abs(actual_days - requested_days) > 2:
        # Significant mismatch — warn user
        data_gaps.append(
            f"Comparing snapshots from {prior_date} and {current_date} "
            f"({actual_days} days). Requested {requested_days} days."
        )
    prior_rows = list(_pm_latest_row_per_deal(by_date[prior_date]).values())
    current_rows = list(_pm_latest_row_per_deal(by_date[current_date]).values())

    prior_sets, _ = _pm_stage_sets(prior_rows, stage_cfg)
    current_sets, _ = _pm_stage_sets(current_rows, stage_cfg)

    prior_all = {r["deal_id"] for r in prior_rows}
    current_all = {r["deal_id"] for r in current_rows}
    new_ids = current_all - prior_all         # absent in prior → new to pipeline
    left_ids = prior_all - current_all        # present in prior, gone in current

    stage_names = set(prior_sets) | set(current_sets)

    def _order(name):
        # order a stage name for display using stage_cfg
        for sid, cfg in stage_cfg.items():
            if cfg["name"] == name:
                return cfg["order"]
        return 9_999  # 'unknown' and unmapped sort last

    by_stage = []
    for name in sorted(stage_names, key=_order):
        p = prior_sets.get(name, set())
        c = current_sets.get(name, set())
        entered = c - p
        # A deal in this stage now that wasn't here before is either new to the
        # pipeline entirely (absent in prior) or moved in from another stage.
        # Reporting a newly-created deal as "entered a stage" overstates
        # movement (Issue 3), so split them.
        entered_new = entered & new_ids
        entered_moved = entered - new_ids
        by_stage.append({
            "stage": name,
            "prior": len(p),
            "current": len(c),
            "net": len(c) - len(p),
            "entered": len(entered),                 # total, back-compat
            "entered_from_other_stage": len(entered_moved),
            "new_to_pipeline": len(entered_new),
            "exited": len(p - c),
            "deal_ids": sorted(c),
            "entered_from_other_stage_ids": sorted(entered_moved),
            "new_to_pipeline_ids": sorted(entered_new),
            "exited_ids": sorted(p - c),
        })

    # Moved between stages = present in both snapshots but changed stage.
    _, prior_stage_of = _pm_stage_sets(prior_rows, stage_cfg)
    _, current_stage_of = _pm_stage_sets(current_rows, stage_cfg)
    moved_between = {d for d in (prior_all & current_all)
                     if prior_stage_of.get(d) != current_stage_of.get(d)}

    totals = {
        "prior": len(prior_rows),
        "current": len(current_rows),
        "net": len(current_rows) - len(prior_rows),
    }
    # Deal-level, mutually exclusive tallies so nothing double-counts: a new
    # deal is in `new_to_pipeline`, not in `moved_between_stages`.
    summary = {
        "new_to_pipeline": len(new_ids),
        "left_pipeline": len(left_ids),
        "moved_between_stages": len(moved_between),
    }
    confidence = _pm_confidence_mix(current_rows)

    # Check for off-grid current position
    current_position = None
    if base:
        position_date = base.get("_current_position_date")
        if position_date and position_date != current_date and position_date in by_date:
            # Current position is on a different grid - report it separately
            position_rows = list(_pm_latest_row_per_deal(by_date[position_date]).values())
            by_stage_position = {}
            for r in position_rows:
                stage_name = _pm_stage_name(r.get("stage_id"), stage_cfg)
                by_stage_position[stage_name] = by_stage_position.get(stage_name, 0) + 1

            current_position = {
                "snapshot_date": position_date,
                "source": base.get("_current_position_source"),
                "total": len(position_rows),
                "by_stage": by_stage_position,
                "note": "Mid-week position, not compared to weekly trend"
            }

    return {
        "snapshot_dates": [prior_date, current_date],
        "by_stage": by_stage,
        "totals": totals,
        "confidence": confidence,
        "summary": summary,
        "current_position": current_position
    }


def _pm_view_composition(by_date, all_dates, stage_cfg, weeks):
    dates = all_dates[-weeks:]
    grid = []
    for d in dates:
        rows = list(_pm_latest_row_per_deal(by_date[d]).values())
        counts = {}
        for r in rows:
            name = _pm_stage_name(r.get("stage_id"), stage_cfg)
            counts[name] = counts.get(name, 0) + 1
        week_of_quarter = rows[0].get("week_of_quarter") if rows else None
        grid.append({
            "snapshot_date": d,
            "week_of_quarter": week_of_quarter,
            "by_stage": counts,
            "total": len(rows),
            "confidence": _pm_confidence_mix(rows),
        })
    return dates, grid


def _pm_left_reason(deal_id, unscoped_current):
    """Why a deal that was in the scoped pipeline last snapshot is gone now.

    A deal absent from the CURRENT scoped snapshot either closed (won/lost),
    dropped to an excluded stage (Meeting Set / Disqualified), or is simply
    gone from the snapshot. We can distinguish the first two by looking at the
    UNSCOPED current-date row (which still carries closed/excluded stages).
    """
    stage_id = unscoped_current.get(deal_id)
    if stage_id is None:
        return "gone_from_snapshot"
    try:
        if is_won(str(stage_id)):
            return "closed_won"
        if is_lost(str(stage_id)):
            return "closed_lost"
    except Exception:
        pass
    return "moved_to_excluded_stage"


def _pm_view_deal_changes(by_date, all_dates, stage_cfg, data_gaps,
                          company_map=None, unscoped_current=None):
    if len(all_dates) < 2:
        data_gaps.append(
            "deal_changes needs two snapshot dates; found "
            f"{len(all_dates)} in this grid — returning null, not a zero"
        )
        return None, []
    company_map = company_map or {}
    unscoped_current = unscoped_current or {}
    prior_date, current_date = all_dates[-2], all_dates[-1]
    prior_rows = _pm_latest_row_per_deal(by_date[prior_date])
    current_rows = _pm_latest_row_per_deal(by_date[current_date])

    changes = []
    all_ids = set(prior_rows) | set(current_rows)
    for deal_id in all_ids:
        pr = prior_rows.get(deal_id)
        cr = current_rows.get(deal_id)
        prior_stage = _pm_stage_name(pr.get("stage_id"), stage_cfg) if pr else None
        current_stage = _pm_stage_name(cr.get("stage_id"), stage_cfg) if cr else None

        reason = None
        if pr and not cr:
            # Absent now — this is leaving the pipeline, NOT a stage move.
            direction = "left_pipeline"
            reason = _pm_left_reason(deal_id, unscoped_current)
        elif cr and not pr:
            # Absent in prior — a newly-created deal, NOT a stage entry (Issue 3).
            direction = "new_to_pipeline"
        elif prior_stage == current_stage:
            continue  # unchanged — only report movement
        else:
            po = _pm_stage_order(pr, stage_cfg)
            co = _pm_stage_order(cr, stage_cfg)
            if co > po:
                direction = "advanced"
            elif co < po:
                direction = "regressed"
            else:
                direction = "moved"
        item = {
            "deal_id": deal_id,
            "company_name": company_map.get(str(deal_id)),
            "owner_email": (cr or pr).get("owner_email"),
            "prior_stage": prior_stage,
            "current_stage": current_stage,
            "direction": direction,
        }
        if reason:
            item["reason"] = reason
        changes.append(item)

    order = {"advanced": 0, "regressed": 1, "moved": 2,
             "new_to_pipeline": 3, "left_pipeline": 4}
    changes.sort(key=lambda x: (order.get(x["direction"], 9), str(x["deal_id"])))
    return [prior_date, current_date], changes


def _pm_view_curve(by_date, all_dates, stage_cfg):
    curve = []
    for d in all_dates:
        rows = list(_pm_latest_row_per_deal(by_date[d]).values())
        curve.append({
            "week_of_quarter": rows[0].get("week_of_quarter") if rows else None,
            "snapshot_date": d,
            "count": len(rows),
            "confidence": _pm_confidence_mix(rows),
        })
    curve.sort(key=lambda x: (x["week_of_quarter"] is None, x["week_of_quarter"]))
    return curve


async def query_pipeline_movement(params: dict, sb) -> dict:
    """
    Pipeline movement / composition / deal-level changes / coverage curve,
    read from deals_snapshot. COUNTS ONLY — never dollars (see module header).

    params:
      view          : 'movement' | 'composition' | 'deal_changes' | 'curve' |
                      'stage_deals' (default 'movement')
      fiscal_quarter: e.g. 'FY2027 Q2' (default: current fiscal quarter)
      weeks         : how many recent weeks for 'composition' (default 4)
      pipeline_id   : optional single-pipeline filter (default: config scope —
                      renewals and non-qualified stages excluded)
      owner_email   : optional rep filter (also accepts rep_email)
      deal_ids      : optional explicit deal set for 'deal_changes'
      stage         : for 'stage_deals' — the stage name (e.g. 'Discovery') or
                      a deal_id to list at the latest snapshot
      close_date_scope : 'all' (default) | 'current_quarter'. Default counts
                      all open deals (correct for coverage); 'current_quarter'
                      restricts to deals closing in the quarter, for
                      reconciliation against a CRM board — never the default.

    Every view also returns a `rows` list of {deal_id, company_name, stage, ...}
    from the latest snapshot so the thread-context layer can save entities for
    follow-up drill-downs. Counts only — deal_value is never selected/emitted.
    """
    load_scope_config, is_in_scope = _pm_load_scoping()
    excluded_pipelines, stage_cfg = load_scope_config()

    view = (params.get("view") or "movement").strip()
    if view not in _PM_VIEWS:
        view = "movement"

    fiscal_quarter = params.get("fiscal_quarter")
    if not fiscal_quarter:
        try:
            fiscal_quarter = _pm_current_quarter_label()
        except Exception as e:
            return {
                "view": view, "basis": "count",
                "error": f"could not resolve current fiscal quarter ({e}); "
                         "pass fiscal_quarter explicitly",
            }

    try:
        weeks = int(params.get("weeks")) if params.get("weeks") is not None else 4
    except (TypeError, ValueError):
        weeks = 4
    weeks = max(1, min(weeks, 13))

    owner_email = params.get("owner_email") or params.get("rep_email")
    pipeline_id = params.get("pipeline_id")
    deal_ids = params.get("deal_ids")
    close_date_scope = (params.get("close_date_scope") or "all").strip().lower()
    if close_date_scope not in ("all", "current_quarter"):
        close_date_scope = "all"

    # Parse time_window for movement view (select snapshots by date)
    time_window = params.get("time_window", {})
    requested_days = None
    if time_window and time_window.get("type") == "relative_days":
        requested_days = time_window.get("days", 0)

    # Explicit, prominent scope statement so a count can be reconciled against
    # a CRM board view (Issue 4). The default counts ALL open deals with no
    # close-date filter — correct for coverage math — which is usually the gap
    # against a board filtered to "close date this quarter".
    close_stmt = ("all open deals as of each snapshot, with NO close-date "
                  "filter" if close_date_scope == "all"
                  else f"only deals whose close date falls in {fiscal_quarter}")
    scope_statement = (
        f"Counting {close_stmt}. Excludes Meeting Set, Disqualified, "
        f"Closed Won, Closed Lost; the renewal pipeline is out of analytics "
        f"scope. A CRM board filtered by close date or including renewals "
        f"will not match."
    )
    scope_out = {
        "pipeline": (str(pipeline_id) if pipeline_id
                     else "default (renewals & non-qualified stages excluded)"),
        "excluded_stages": ["Meeting Set", "Disqualified",
                            "Closed Won", "Closed Lost"],
        "excluded_pipelines": sorted(excluded_pipelines),
        "close_date_scope": close_date_scope,
        "statement": scope_statement,
    }

    # ── load snapshot rows for the quarter ──
    filters = [("eq", "fiscal_quarter", fiscal_quarter)]
    if owner_email:
        filters.append(("eq", "owner_email", owner_email))
    if pipeline_id:
        filters.append(("eq", "pipeline_id", str(pipeline_id)))
    else:
        # Default scope always drops the excluded (renewal) pipelines. Push
        # that server-side so those rows are never paged in the first place —
        # a real reduction in rows/pages the curve & composition views scan
        # (Issue 5). Null-stage rows live in the default pipeline, so a `neq`
        # on the renewal id keeps them.
        for pid in sorted(excluded_pipelines):
            filters.append(("neq", "pipeline_id", str(pid)))
    rows = select_all(sb, "deals_snapshot",
                      columns=_PM_SNAPSHOT_COLUMNS, filters=filters)
    loaded_row_count = len(rows)
    loaded_pages = (loaded_row_count // 1000) + 1

    if deal_ids:
        wanted = {str(d) for d in deal_ids}
        rows = [r for r in rows if str(r.get("deal_id")) in wanted]

    base = {
        "view": view,
        "fiscal_quarter": fiscal_quarter,
        "scope": scope_out,
        # Surfaced at top level too, so a synthesis layer naturally includes it.
        "scope_statement": scope_statement,
        "basis": "count",  # explicit — never 'dollar' until the ledger clears
        "query_stats": {"rows_loaded": loaded_row_count,
                        "pages_loaded": loaded_pages},
    }

    if not rows:
        gap = f"no snapshot rows for {fiscal_quarter}"
        if owner_email:
            gap += f" (owner {owner_email})"
        return {**base, "snapshot_dates": [], "result": None,
                "data_gaps": [gap]}

    # ── grid handling: report both trend and current position ──
    data_gaps = []
    sources = {}
    for r in rows:
        src = r.get("snapshot_source") or "unknown"
        sources.setdefault(src, set()).add(r.get("snapshot_date"))

    if len(sources) > 1:
        # Multiple grids: pick trend grid (best span) + current position (most recent)
        # Trend grid = widest date span (answers "how has it moved")
        # Current position = most recent snapshot on any grid (stated as position, not compared)
        from datetime import date as dt

        def span_days(source):
            """Days between earliest and latest snapshot in this source."""
            dates = sorted(sources[source])
            if len(dates) < 2:
                return 0
            earliest = dt.fromisoformat(dates[0])
            latest = dt.fromisoformat(dates[-1])
            return (latest - earliest).days

        # Pick source with widest span (not most snapshots)
        trend_source = max(sources, key=span_days)
        all_dates_sorted = sorted(date for dates in sources.values() for date in dates)
        current_date = all_dates_sorted[-1]
        current_source = next(s for s, dates in sources.items() if current_date in dates)

        if trend_source != current_source:
            trend_dates = sorted(sources[trend_source])
            data_gaps.append(
                f"Weekly trend from {trend_source} grid ({len(trend_dates)} snapshots: "
                f"{', '.join(trend_dates)}). Current position as of {current_date} "
                f"is from {current_source} grid (different weekday, not compared to trend)."
            )
        chosen_source = trend_source
        # Store current position info for movement view
        base["_current_position_date"] = current_date
        base["_current_position_source"] = current_source
    else:
        # Single grid: use it for both trend and current
        chosen_source = list(sources.keys())[0]

    grid_rows = [r for r in rows
                 if (r.get("snapshot_source") or "unknown") == chosen_source]

    # Include current position rows if on different grid
    if base.get("_current_position_date") and base.get("_current_position_source") != chosen_source:
        position_rows = [r for r in rows
                        if r.get("snapshot_date") == base["_current_position_date"]
                        and (r.get("snapshot_source") or "unknown") == base["_current_position_source"]]
        grid_rows.extend(position_rows)

    # ── apply analytics scope at read time (null-stage rows counted) ──
    scoped = [r for r in grid_rows
              if _pm_in_scope(r, excluded_pipelines, stage_cfg, is_in_scope)]

    # Optional close-date scope (Issue 4). Default 'all' leaves the coverage
    # denominator unfiltered; 'current_quarter' restricts to deals whose
    # point-in-time close_date falls in the queried quarter, for reconciliation
    # against a CRM board — it never changes the default.
    if close_date_scope == "current_quarter" and scoped:
        from utils import get_fiscal_quarter
        any_date = datetime.fromisoformat(
            min(r["snapshot_date"] for r in scoped)).date()
        q_start, q_end, _ = get_fiscal_quarter(any_date)
        lo, hi = q_start.isoformat(), q_end.isoformat()
        before_n = len(scoped)
        scoped = [r for r in scoped
                  if r.get("close_date") and lo <= r["close_date"][:10] <= hi]
        data_gaps.append(
            f"close_date_scope=current_quarter: kept {len(scoped)} of "
            f"{before_n} in-scope deal-rows whose close date is in "
            f"{fiscal_quarter}")

    by_date = _pm_by_date(scoped)
    all_dates = sorted(by_date.keys())

    base["snapshot_source"] = chosen_source

    if not all_dates:
        data_gaps.append(
            f"no in-scope rows for {fiscal_quarter} on the '{chosen_source}' grid"
        )
        return {**base, "snapshot_dates": [], "result": None,
                "data_gaps": data_gaps}

    # Company names for the deals we'll name individually (Issue 2). Union of
    # the latest snapshot and the prior snapshot (deal_changes compares both).
    name_ids = {r["deal_id"] for r in by_date[all_dates[-1]]}
    if len(all_dates) >= 2:
        name_ids |= {r["deal_id"] for r in by_date[all_dates[-2]]}
    company_map = _pm_company_map(sb, name_ids)

    # Unscoped current-date stages (pre-scope) so deal_changes can say WHY a
    # deal left the scoped pipeline (closed vs dropped to an excluded stage).
    unscoped_current = {r["deal_id"]: r.get("stage_id")
                        for r in grid_rows
                        if r.get("snapshot_date") == all_dates[-1]}

    # Entity-bearing rows from the latest snapshot, attached to every view so
    # extract_entity_context saves deal_ids AND company_names and follow-ups
    # ("which of those are in Discovery?") have thread context.
    latest_rows = _pm_deal_rows(by_date[all_dates[-1]], stage_cfg, company_map)

    # ── stage-filtered deal list (direct drill-down) ──
    if view == "stage_deals":
        want = (params.get("stage") or "").strip().lower()
        if not want:
            data_gaps.append("stage_deals needs a 'stage' param (e.g. 'Discovery')")
            return {**base, "snapshot_dates": [all_dates[-1]],
                    "stage": None, "rows": [], "count": None,
                    "data_gaps": data_gaps}
        matched = [r for r in latest_rows
                   if r["stage"].lower() == want or str(r["deal_id"]) == want]
        if not matched:
            data_gaps.append(
                f"no in-scope deals in stage {params.get('stage')!r} at "
                f"{all_dates[-1]} (stages present: "
                f"{sorted({r['stage'] for r in latest_rows})})"
            )
        return {
            **base,
            "snapshot_dates": [all_dates[-1]],
            "stage": params.get("stage"),
            "rows": matched,
            "count": len(matched),
            "data_gaps": data_gaps,
        }

    # ── dispatch ──
    if view == "movement":
        result = _pm_view_movement(
            by_date, all_dates, stage_cfg, data_gaps, requested_days, base)
        return {
            **base,
            "snapshot_dates": result.get("snapshot_dates", []),
            "by_stage": result.get("by_stage", []),
            "totals": result.get("totals", {}),
            "summary": result.get("summary", {}),
            "confidence": result.get("confidence", {}),
            "current_position": result.get("current_position"),  # Off-grid snapshot if present
            "rows": latest_rows,
            "data_gaps": data_gaps,
        }

    if view == "composition":
        dates, grid = _pm_view_composition(
            by_date, all_dates, stage_cfg, weeks)
        return {
            **base,
            "snapshot_dates": dates,
            "weeks": grid,
            "rows": latest_rows,
            "data_gaps": data_gaps,
        }

    if view == "deal_changes":
        snap_dates, changes = _pm_view_deal_changes(
            by_date, all_dates, stage_cfg, data_gaps,
            company_map=company_map, unscoped_current=unscoped_current)
        summary = {}
        for c in changes:
            summary[c["direction"]] = summary.get(c["direction"], 0) + 1
        # For deal_changes the drillable set is the deals that MOVED, so the
        # entity rows are the changed deals rather than the whole snapshot.
        change_rows = [{
            "deal_id": c["deal_id"],
            "company_name": c.get("company_name"),
            "stage": c["current_stage"],
            "owner_email": c["owner_email"],
            "direction": c["direction"],
        } for c in changes]
        return {
            **base,
            "snapshot_dates": snap_dates or [],
            "changes": changes,
            "summary": summary,
            "rows": change_rows,
            "data_gaps": data_gaps,
        }

    # view == "curve"
    curve = _pm_view_curve(by_date, all_dates, stage_cfg)
    present_weeks = {c["week_of_quarter"] for c in curve
                     if c["week_of_quarter"] is not None}
    missing = [w for w in range(1, 14) if w not in present_weeks]
    if missing:
        data_gaps.append(
            f"no snapshot for week_of_quarter {missing} — reported as absent, "
            "not zero-filled"
        )
    return {
        **base,
        "snapshot_dates": all_dates,
        "curve": curve,
        "rows": latest_rows,
        "data_gaps": data_gaps,
    }
