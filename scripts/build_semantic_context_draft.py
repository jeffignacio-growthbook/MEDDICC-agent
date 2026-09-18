"""
Draft of build_semantic_context() function for V2 semantic layer.
Will be added to scripts/utils.py after review.
"""
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Tuple, Optional, Any
import yaml
from pathlib import Path


def build_semantic_context(config: Optional[Dict] = None) -> str:
    """
    Build semantic context from existing configs (client.yaml, field_semantics.yaml).

    Returns a structured text block that explains:
    - Fiscal calendar with resolved quarter boundaries
    - Pipeline meanings (new business vs renewal)
    - Value fields per pipeline
    - Vocabulary (what terms mean in this context)
    - Table relationships
    - What does NOT apply to each pipeline

    This is injected into prompts to prevent the model from:
    - Inventing quarter boundaries
    - Using wrong value fields for renewals
    - Computing metrics that don't apply to a pipeline

    Args:
        config: Optional pre-loaded config dict. If None, loads from client.yaml

    Returns:
        str: Formatted semantic context block
    """
    if config is None:
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        with open(config_path) as f:
            config = yaml.safe_load(f)

    # Load field semantics
    field_sem_path = Path(__file__).parent.parent / 'config' / 'field_semantics.yaml'
    with open(field_sem_path) as f:
        field_semantics = yaml.safe_load(f)

    lines = ["# SEMANTIC CONTEXT", ""]

    # ========================================================================
    # 1. FISCAL CALENDAR
    # ========================================================================
    lines.append("## Fiscal Calendar")
    lines.append("")

    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 1)
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    lines.append(f"Fiscal year starts: {month_names[fy_start_month]} 1")
    lines.append("")

    # Generate concrete quarter boundaries for current and next FY
    today = date.today()

    # Determine current fiscal year
    if today.month >= fy_start_month:
        current_fy = today.year + 1
    else:
        current_fy = today.year

    # Generate quarters for current FY and next FY
    lines.append("Quarter boundaries (DO NOT derive these - use these exact dates):")
    lines.append("")

    for fy in [current_fy, current_fy + 1]:
        for quarter_num in [1, 2, 3, 4]:
            # Calculate quarter start
            q_start_month = fy_start_month + ((quarter_num - 1) * 3)
            if q_start_month > 12:
                q_start_month -= 12
                q_start_year = fy
            else:
                q_start_year = fy - 1

            q_start = date(q_start_year, q_start_month, 1)
            q_end = q_start + relativedelta(months=3) - relativedelta(days=1)

            lines.append(f"  FY{fy} Q{quarter_num}: {q_start.isoformat()} to {q_end.isoformat()}")
        lines.append("")

    # ========================================================================
    # 2. PIPELINES AND MEANINGS
    # ========================================================================
    lines.append("## Pipelines")
    lines.append("")

    pipeline_config = config.get('pipeline', {})
    renewal_pipeline_ids = pipeline_config.get('value_field', {}).get('renewal_pipeline_ids', [])

    pipelines_list = pipeline_config.get('pipelines', [])

    # Identify renewal vs new business pipelines
    for p in pipelines_list:
        pid = p.get('id')
        pname = p.get('name', pid)

        if pid in renewal_pipeline_ids:
            purpose = "RENEWAL PIPELINE - existing customer renewals and expansions"
        else:
            purpose = "NEW BUSINESS PIPELINE - net-new customer acquisition"

        lines.append(f"**{pname}** (pipeline_id: '{pid}')")
        lines.append(f"  Purpose: {purpose}")
        lines.append("")

    # ========================================================================
    # 3. VALUE FIELDS PER PIPELINE
    # ========================================================================
    lines.append("## Value Fields")
    lines.append("")
    lines.append("CRITICAL: Different pipelines measure value differently.")
    lines.append("")

    value_field_config = pipeline_config.get('value_field', {})

    # New business value
    components = value_field_config.get('components', [])
    fallback = value_field_config.get('fallback')

    lines.append("**New Business Pipeline:**")
    if components:
        lines.append(f"  Primary: SUM({', '.join(components)})")
    if fallback:
        lines.append(f"  Fallback: {fallback} (when all components are NULL)")
    lines.append("")

    # Renewal value
    renewal_components = value_field_config.get('renewal_components', [])

    lines.append("**Renewal Pipeline:**")
    if renewal_components:
        lines.append(f"  Base value: {', '.join(renewal_components)}")
    lines.append(f"  Expansion: incremental_arr (may be NULL if no expansion)")
    lines.append(f"  Total deal value: renewal_revenue + COALESCE(incremental_arr, 0)")
    lines.append("")

    lines.append("NEVER use arr_usd or amount for renewal pipeline deals.")
    lines.append("NEVER use renewal_revenue for new business pipeline deals.")
    lines.append("")

    # ========================================================================
    # 4. VOCABULARY
    # ========================================================================
    lines.append("## Vocabulary")
    lines.append("")

    # Renewal vocabulary
    renewal_stages = [sid for sid, info in field_semantics.get('stage_map', {}).items()
                     if any(pid in sid or sid.startswith('129732') for pid in renewal_pipeline_ids)]

    lines.append("**Renewal-specific terms:**")
    lines.append(f"  'Due to renew' = renewal pipeline deals in open stages (not closed won/lost)")
    lines.append(f"  'At risk' = renewal deals with specific risk indicators (define per client)")
    lines.append(f"  'Upcoming renewals' = deals in earliest renewal stages")
    lines.append("")

    # Qualification
    qualified_stage_order = pipeline_config.get('qualified_stage_order', 1)
    lines.append("**Qualification:**")
    lines.append(f"  'Qualified' = new business deals where stage order >= {qualified_stage_order}")
    lines.append(f"  Qualification does NOT apply to renewal pipeline")
    lines.append("")

    # Outcome vocabulary
    outcome_buckets = field_semantics.get('outcome_buckets', {})
    won_buckets = outcome_buckets.get('won', [])
    lost_buckets = outcome_buckets.get('lost', [])
    open_buckets = outcome_buckets.get('open', [])

    lines.append("**Deal outcomes:**")
    lines.append(f"  Won = stage bucket in {won_buckets}")
    lines.append(f"  Lost = stage bucket in {lost_buckets}")
    lines.append(f"  Open = stage bucket in {open_buckets}")
    lines.append("")

    # ========================================================================
    # 5. TABLE RELATIONSHIPS
    # ========================================================================
    lines.append("## Table Relationships")
    lines.append("")
    lines.append("```")
    lines.append("deals.deal_id → analyses.deal_id (one deal → many analyses over time)")
    lines.append("deals.deal_id → calls.deal_id (one deal → many calls)")
    lines.append("deals.company_id → companies.company_id")
    lines.append("deals.owner_email → users.email")
    lines.append("```")
    lines.append("")

    # ========================================================================
    # 6. WHAT DOES NOT APPLY
    # ========================================================================
    lines.append("## What Does NOT Apply")
    lines.append("")
    lines.append("**Renewal pipeline:**")
    lines.append("  ✗ Week-3 conversion (this is a new business qualification metric)")
    lines.append("  ✗ Waterfall qualification tracking (renewals don't 'qualify')")
    lines.append("  ✗ SAO field (Sales Accepted Opportunity is new business only)")
    lines.append("  ✗ Discovery/Scoping stages (different funnel)")
    lines.append("")

    lines.append("**New business pipeline:**")
    lines.append("  ✗ Renewal revenue field")
    lines.append("  ✗ Churn metrics")
    lines.append("  ✗ GRR/NRR calculations")
    lines.append("")

    lines.append("**Both pipelines:**")
    lines.append("  ✗ DO NOT invent quarter boundaries - use the fiscal calendar above")
    lines.append("  ✗ DO NOT assume calendar quarters (Q1 = Jan-Mar) - use fiscal quarters")
    lines.append("  ✗ DO NOT filter on stage display names - use stage IDs from field_semantics")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test the function
    context = build_semantic_context()
    print(context)
    print("\n" + "="*80)
    print(f"Total length: {len(context)} characters")
    print(f"Estimated tokens: ~{len(context) // 4}")
