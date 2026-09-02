"""Schema context builder for dynamic queries."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Import field_semantics for canonical stage descriptions
try:
    from field_semantics import STAGE_MAP
except ImportError:
    from api.field_semantics import STAGE_MAP

_cached_context = None

def _stage_prose() -> str:
    """
    Generate stage ID prose from field_semantics (single source of truth).
    Returns a string like: 'presentationscheduled' = Technical Evaluation, 'qualifiedtobuy' = Scoping, ...
    """
    parts = [f"'{sid}' = {info['label']}" for sid, info in STAGE_MAP.items() if info.get('bucket') in ['discovery', 'scoping', 'proposal']]
    return ", ".join(parts[:3])  # Show first 3 for brevity

def get_schema_context(sb, tables_with_descriptions=None, lightweight=False):
    """
    Build schema context for dynamic query loop.

    Args:
        sb: Supabase client
        tables_with_descriptions: List of table names that should get full descriptions.
                                 If None, all tables get full descriptions (legacy behavior).
                                 If list, other tables get column names only.
        lightweight: If True, only include descriptions for core columns (identifiers,
                    values, status) to reduce prompt size. Other columns get name+type only.

    Returns hybrid schema:
        - ALL tables' names + column names (~1,500 tokens)
        - Full descriptions ONLY for tables in tables_with_descriptions (~2,000 tokens)
        - If lightweight=True, descriptions only for core columns (~500 tokens)
    """
    # Don't cache when using selective descriptions or lightweight mode
    if tables_with_descriptions is not None or lightweight:
        return _build_schema_context(sb, tables_with_descriptions, lightweight)

    # Legacy behavior: cache full schema
    global _cached_context
    if _cached_context:
        return _cached_context
    _cached_context = _build_schema_context(sb, tables_with_descriptions=None, lightweight=False)
    return _cached_context

def _build_schema_context(sb, tables_with_descriptions, lightweight=False):
    """Build schema context with optional selective descriptions."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[SCHEMA_BUILD] lightweight={lightweight}, tables_with_descriptions={tables_with_descriptions}")

    from supabase_client import select_all
    rows = select_all(sb, "data_dictionary",
        columns="supabase_table,supabase_column,data_type,description,enum_values,hubspot_name,source",
        filters=[("eq", "is_queryable", True)])
    if not rows:
        return _minimal_fallback_context()

    by_table = {}
    for r in rows:
        by_table.setdefault(r["supabase_table"], []).append(r)

    # Determine which tables get full descriptions
    if tables_with_descriptions is None:
        # Legacy: all tables get full descriptions
        tables_with_full_desc = set(by_table.keys())
    else:
        # Hybrid: only specified tables get full descriptions
        tables_with_full_desc = set(tables_with_descriptions)

    # Core columns that always get descriptions (lightweight mode)
    # Identifiers, values, status, dates — essentials for most queries
    core_columns = {
        "deal_id", "company_name", "owner_email", "owner_name",
        "deal_value", "arr_usd", "new_arr", "expansion_arr", "renewal_revenue",
        "deal_status", "stage", "pipeline_id",
        "close_date", "created_at", "create_date",
        "segment", "forecast_category",
        # Analyses table cores
        "overall_score", "champion_score", "economic_buyer_score",
        "metrics_score", "decision_criteria_score", "decision_process_score",
        "identify_pain_score", "compelling_event_score",
    }

    lines = ["QUERYABLE SUPABASE TABLES AND COLUMNS:", "(Use these exact column names in query tool calls)", ""]

    # Generate stage description from field_semantics (canonical source)
    stage_note = f"Note: stage column contains HubSpot stage IDs (e.g. {_stage_prose()}). Never filter on display names."

    table_descriptions = {
        "deals": f"Active and closed deals. One row per deal. {stage_note}",
        "analyses": "Nightly MEDDICC scores per deal. Latest row = most recent analysis.",
        "objections": "Objections raised in sales calls, extracted by AI. One row per objection instance.",
        "feature_gaps": "Feature gaps mentioned in sales calls. One row per gap instance.",
        "win_loss_narratives": "AI-generated win/loss analysis for closed deals.",
        "waterfall_weekly": "Weekly pipeline movement: new, won, lost, net_change. Precomputed.",
        "rep_targets": "Quota targets by rep/team/period.",
        "arr_by_customer": "VIEW: total ARR per won customer."}
    join_notes = """
TABLE RELATIONSHIPS:
  deals.deal_id → analyses.deal_id (one deal → many analyses; use latest)
  deals.deal_id → objections.deal_id
  deals.deal_id → feature_gaps.deal_id
  deals.company_name ≈ objections.company_name (fuzzy — prefer deal_id)
  deals.owner_email = rep identifier (maps to rep_targets.entity_email)
"""
    # Track description decisions for debugging
    described_count = 0
    skipped_count = 0

    for table, cols in sorted(by_table.items()):
        desc = table_descriptions.get(table, "")
        lines.append(f"TABLE: {table}")

        # Include purpose only if this table gets full descriptions
        if desc and table in tables_with_full_desc:
            lines.append(f"  Purpose: {desc}")

        for c in cols:
            col, dtype = c["supabase_column"], c["data_type"]
            enum, hs = c.get("enum_values"), c.get("hubspot_name") or ""
            hs_note = f" [HubSpot: {hs}]" if hs and hs != col else ""

            # Determine if this column gets a description
            should_describe = False
            if table in tables_with_full_desc:
                if lightweight:
                    # Lightweight mode: only core columns get descriptions
                    should_describe = col in core_columns
                else:
                    # Full mode: all columns in relevant tables get descriptions
                    should_describe = True

            if should_describe:
                described_count += 1
                cdesc = (c.get("description") or "")[:80]
                line = f"  {col} ({dtype}){hs_note}: {cdesc}"
                if enum and dtype == "enumeration":
                    try:
                        vals = json.loads(enum) if isinstance(enum, str) else enum
                        options = ", ".join(f'"{v["value"]}"' for v in vals[:8])
                        line += f" — values: [{options}]"
                    except: pass
            else:
                # Column name and type only (no description)
                line = f"  {col} ({dtype}){hs_note}"
                skipped_count += 1

            lines.append(line)
        lines.append("")

    result = "\n".join(lines + [join_notes])
    logger.info(f"[SCHEMA_BUILD] Built {len(result)} chars. Described: {described_count} cols, Skipped: {skipped_count} cols")
    return result

def invalidate_cache():
    global _cached_context
    _cached_context = None

def _minimal_fallback_context():
    # Generate stage note from field_semantics
    stage_note = f"Note: stage column contains HubSpot stage IDs (e.g. {_stage_prose()}). Never filter on display names."

    return f"""
QUERYABLE TABLES (data dictionary not yet populated — run discover_properties.py):
  deals: company_name, deal_value, stage, deal_status, owner_email,
         create_date, close_date, segment, forecast_category,
         sao, new_arr, expansion_arr, lost_reason, pipeline_id
         {stage_note}
  analyses: deal_id, overall_score, champion_score, economic_buyer_score,
            decision_criteria_score, decision_process_score, pain_score,
            competition_score, component_details (JSONB), analyzed_at, status
  objections: company_name, category, verbatim_quote, rep_response,
              stage_when_raised, extracted_at
  feature_gaps: company_name, category, severity, competitor_mentioned,
                feature_description, extracted_at
  win_loss_narratives: company_name, outcome, stated_reason, narrative,
                       key_factors, generated_at
  waterfall_weekly: week_ending, pipeline_id, new_pipeline_value,
                    won_value, lost_value, net_change
  arr_by_customer: company_name, total_arr, won_deal_count

TABLE JOINS:
  deals.deal_id → analyses.deal_id, objections.deal_id, feature_gaps.deal_id
"""
