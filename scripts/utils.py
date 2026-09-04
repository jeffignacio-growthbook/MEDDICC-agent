"""
Shared utility functions for MEDDICC agent.

This module provides common functionality used across ETL and analysis scripts.
"""

import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional


# ============================================================================
# PIPELINE CONFIGURATION HELPERS
# ============================================================================

def load_client_config() -> Dict[str, Any]:
    """
    Load full client configuration from config/client.yaml.

    Returns:
        dict: Full configuration dictionary
    """
    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        return yaml.safe_load(f)


def get_pipeline_config(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Load pipeline configuration from config/client.yaml.

    Args:
        config: Optional pre-loaded config dict (loaded if not provided)

    Returns:
        dict: Pipeline configuration with 'pipelines' key containing stage details
    """
    if config is None:
        config = load_client_config()

    return config.get('pipeline', {})


def get_stage_order(stage_id: str, pipeline_config: Optional[Dict] = None) -> Optional[int]:
    """
    Get the order value for a stage ID.

    Args:
        stage_id: HubSpot stage ID
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        int: Stage order value, or None if not found
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    for pipeline in pipeline_config.get('pipelines', []):
        for stage in pipeline.get('stages', []):
            if stage.get('id') == stage_id:
                return stage.get('order')

    return None


def get_value_field(pipeline_config: Optional[Dict] = None):
    """
    Get the deal value field configuration (string or dict).

    Args:
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        str or dict: Field name ('incremental_arr') or computed config dict
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    return pipeline_config.get('value_field', 'amount')


def get_value_properties(config: Optional[Dict] = None) -> list:
    """
    HubSpot property names the ETL must fetch to compute deal value.
    String field -> [field]; computed -> its components.

    Args:
        config: Optional full config dict (loaded if not provided)

    Returns:
        list: Property names to fetch from HubSpot
    """
    if config is None:
        from pathlib import Path
        import yaml
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
        else:
            config = {}

    vf = config.get('pipeline', {}).get('value_field', 'amount')
    if not isinstance(vf, dict):
        return [vf]

    # The fallback and renewal components are part of the value, so the ETL
    # must fetch them too. Omitting renewal_revenue is why renewal deals
    # computed to 0.
    props = list(vf.get('components', []))
    extras = ([vf['fallback']] if vf.get('fallback') else [])
    extras += list(vf.get('renewal_components', []))
    for extra in extras:
        if extra not in props:
            props.append(extra)
    return props


def _numeric_or_none(raw) -> Optional[float]:
    """Parse a HubSpot numeric property. Blank/None/'null' -> None, not 0."""
    if raw in (None, '', 'null'):
        return None
    try:
        clean = str(raw).replace('$', '').replace(',', '').strip()
        return float(clean) if clean else None
    except (ValueError, TypeError):
        return None


def compute_deal_value(properties: dict, config: Optional[Dict] = None,
                       pipeline_id: Optional[str] = None) -> float:
    """
    GrowthBook deal value from a HubSpot properties dict.

    Incremental ARR (new_revenue + expansion_revenue) is the value, with two
    rules the plain NULL-safe sum got wrong:

    1. If EVERY component is blank/null, Incremental ARR is unknown rather
       than zero, so fall back to `amount`. A component that is present and
       zero is a real value and does NOT trigger the fallback.
    2. Renewal-pipeline deals are Incremental ARR + Renewal ARR
       (`renewal_revenue`). incremental_arr carries only the expansion above
       the renewed base, so a renewal without expansion computes to 0 without
       this. Renewals fall back to `amount` only when Incremental ARR AND
       Renewal ARR are both blank -- falling back while also adding Renewal
       ARR would double-count, since `amount` equals the renewed base for 89%
       of renewals carrying both.

    Args:
        properties: HubSpot deal properties dict
        config: Optional full config dict (loaded if not provided)
        pipeline_id: Deal's pipeline. Required to apply the renewal rule;
            without it a renewal deal is valued as new business.

    Returns:
        float: Computed deal value
    """
    if config is None:
        from pathlib import Path
        import yaml
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
        else:
            config = {}

    vf = config.get('pipeline', {}).get('value_field', 'amount')
    if not isinstance(vf, dict):
        return _numeric_or_none(properties.get(vf)) or 0.0

    def summed(names):
        """(total, any_component_present). All-blank -> (0.0, False)."""
        total, present = 0.0, False
        for n in names:
            v = _numeric_or_none(properties.get(n))
            if v is not None:
                total += v
                present = True
        return total, present

    incremental, incremental_present = summed(vf.get('components', []))

    renewal_ids = [str(p) for p in vf.get('renewal_pipeline_ids', [])]
    is_renewal = pipeline_id is not None and str(pipeline_id) in renewal_ids

    if is_renewal:
        renewal, renewal_present = summed(vf.get('renewal_components', []))
    else:
        renewal, renewal_present = 0.0, False

    if incremental_present or renewal_present:
        return incremental + renewal

    # Nothing populated: Incremental ARR is unknown, not zero.
    fallback = vf.get('fallback')
    if fallback:
        return _numeric_or_none(properties.get(fallback)) or 0.0
    return 0.0


def is_won_stage(stage_id: str, pipeline_config: Optional[Dict] = None) -> bool:
    """
    Check if a stage ID is a won stage.

    Args:
        stage_id: HubSpot stage ID
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        bool: True if stage is marked as won
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    for pipeline in pipeline_config.get('pipelines', []):
        for stage in pipeline.get('stages', []):
            if stage.get('id') == stage_id:
                return stage.get('is_won', False)

    return False


def is_lost_stage(stage_id: str, pipeline_config: Optional[Dict] = None) -> bool:
    """
    Check if a stage ID is a lost stage.

    Args:
        stage_id: HubSpot stage ID
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        bool: True if stage is marked as lost
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    for pipeline in pipeline_config.get('pipelines', []):
        for stage in pipeline.get('stages', []):
            if stage.get('id') == stage_id:
                return stage.get('is_lost', False)

    return False


def get_segment(employee_count: Optional[int], config: Optional[Dict] = None) -> tuple:
    """
    Return (segment_name, expected_cycle_days) for an employee count.

    Maps employee count to configured segmentation bands (SMB, Mid-Market,
    Enterprise). Returns 'Unknown' for None/missing employee counts.

    Args:
        employee_count: Number of employees (from Company.numberofemployees)
        config: Optional full config dict (loaded if not provided)

    Returns:
        tuple: (segment_name, expected_cycle_days)
            e.g. ('SMB', 33), ('Enterprise', 132), ('Unknown', None)

    Examples:
        get_segment(100) -> ('SMB', 33)
        get_segment(500) -> ('Mid-Market', 84)
        get_segment(5000) -> ('Enterprise', 132)
        get_segment(None) -> ('Unknown', None)
    """
    if config is None:
        config = load_client_config()

    bands = config.get('segmentation', {}).get('bands', [])

    # Handle None/missing employee count -> Unknown
    if employee_count is None:
        unknown = next((b for b in bands if b['name'] == 'Unknown'), None)
        return ('Unknown', unknown.get('expected_cycle_days') if unknown else None)

    # Find matching band
    for band in bands:
        lo = band.get('min', 0)
        hi = band.get('max', float('inf'))
        if lo <= employee_count <= hi:
            return (band['name'], band.get('expected_cycle_days'))

    # No match found -> Unknown
    return ('Unknown', None)


# ============================================================================
# STRING UTILITIES
# ============================================================================

def slugify(name: str) -> str:
    """
    Convert company name to slug (e.g., 'Skyscanner + GrowthBook' -> 'skyscanner').

    CRITICAL: This logic must be identical across etl_calls.py, etl_deals.py,
    and run_nightly.py to ensure cache files match correctly.

    Args:
        name: Company name from HubSpot deal or call transcript

    Returns:
        str: Slugified company name for cache file naming

    Examples:
        'Acme Corp' -> 'acme-corp'
        'Scale AI' -> 'scale-ai'
        'Notion Labs Inc' -> 'notion-labs-inc'
        'Skyscanner + GrowthBook' -> 'skyscanner'
        'GrowthBook <> ClickHouse' -> 'clickhouse'
    """
    if not name:
        return ''

    # Split on connector symbols (-, +, <>, &, /) and "and"
    # This handles: "Skyscanner - GrowthBook", "Client + GrowthBook", etc.
    parts = re.split(r'\s*[-–—]\s+', name, maxsplit=1)
    company_part = parts[0]

    # Remove "GrowthBook" (case-insensitive) from anywhere in the name
    # Handles: "GrowthBook + Client" or "Client + GrowthBook"
    company_part = re.sub(r'growthbook', '', company_part, flags=re.IGNORECASE)

    # Remove connector symbols that might remain
    company_part = re.sub(r'[+<>&/,]', ' ', company_part)

    # Remove common filler words
    company_part = re.sub(
        r'\b(and|the|with|vs|versus|for|at|in|of)\b',
        '', company_part, flags=re.IGNORECASE
    )

    # Normalize whitespace and lowercase
    company_part = re.sub(r'\s+', ' ', company_part).strip().lower()

    # Remove non-alphanumeric characters (except spaces)
    company_part = re.sub(r'[^a-z0-9\s]', '', company_part)

    # Convert to hyphenated slug
    slug = company_part.replace(' ', '-').strip('-')

    # Return slug if >= 3 chars (avoid single-letter slugs)
    return slug if len(slug) >= 3 else ''


def get_fiscal_quarter(as_of=None, config: Optional[Dict] = None) -> tuple:
    """
    Return (q_start_date, q_end_date, label) for the fiscal quarter
    containing as_of, from fiscal.fy_start_month.

    fy_start_month=2 => Feb-Apr, May-Jul, Aug-Oct, Nov-Jan
    FY label is the year of the FY END (May 2026 sits in FY2027 Q2)

    Args:
        as_of: Date to find quarter for (default: today)
        config: Optional full config dict (loaded if not provided)

    Returns:
        tuple: (start_date, end_date, label) e.g. (date(2026,5,1), date(2026,7,31), "FY2027 Q2")
    """
    from datetime import date
    from dateutil.relativedelta import relativedelta

    if as_of is None:
        as_of = date.today()

    if config is None:
        from pathlib import Path
        import yaml
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
        else:
            config = {}

    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 1)

    # Find which quarter this date falls in
    # Quarters are 3 months each starting from fy_start_month
    year = as_of.year
    month = as_of.month

    # Calculate months since FY start
    if month >= fy_start_month:
        # Same fiscal year
        fy_year = year + 1  # FY label is END year
        months_into_fy = month - fy_start_month
    else:
        # Previous fiscal year
        fy_year = year
        months_into_fy = (12 - fy_start_month) + month

    # Which quarter (0-3)?
    quarter_num = months_into_fy // 3 + 1  # 1-4

    # Calculate quarter start
    q_start_month = fy_start_month + ((quarter_num - 1) * 3)
    if q_start_month > 12:
        q_start_month -= 12
        q_start_year = fy_year
    else:
        q_start_year = fy_year - 1

    q_start = date(q_start_year, q_start_month, 1)

    # Quarter end is last day of 3rd month
    q_end = q_start + relativedelta(months=3) - relativedelta(days=1)

    label = f"FY{fy_year} Q{quarter_num}"

    return (q_start, q_end, label)


# ============================================================================
# SEMANTIC CONTEXT BUILDER
# ============================================================================

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
        str: Formatted semantic context block (~650 tokens)
    """
    from datetime import date
    from dateutil.relativedelta import relativedelta

    if config is None:
        config = load_client_config()

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

    # ========================================================================
    # 7. FIELD VALUE SEMANTICS
    # ========================================================================
    # MOVED TO DYNAMIC LOOP ONLY (lines 1510-1514 in router.py)
    # This section was crowding the classifier (doubled semantic context from
    # 650 to 1320 tokens). It's useful for the dynamic loop (which has full
    # context), but noise for the classifier (which just needs to route).
    #
    # Missing Value Detection content now lives in DYNAMIC_SYSTEM_PROMPT where
    # it applies to tool-calling queries, not classification.

    # ========================================================================
    # 8. VERIFIED METRICS
    # ========================================================================
    metrics_path = Path(__file__).parent.parent / 'config' / 'metrics.yaml'
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = yaml.safe_load(f)

        lines.append("## Verified Metrics")
        lines.append("")
        lines.append("CRITICAL: These values are reconciled against source systems.")
        lines.append("A computed result that diverges materially is likely wrong.")
        lines.append("")

        # Include key verified metrics
        for metric_id in ['grr', 'nrr', 'churn', 'week3_conversion']:
            if metric_id in metrics:
                m = metrics[metric_id]
                label = m.get('label', metric_id.upper())
                formula = m.get('formula', '')
                verified = m.get('verified', {})

                lines.append(f"**{label}**")
                if formula:
                    lines.append(f"  Formula: {formula}")

                # Include verified value if present
                for key, value in verified.items():
                    if key not in ['reconciled_against', 'reconciled_on', 'tolerance', 'note',
                                   'excluded_quarter', 'q2_measured_rate', 'q2_exclusion_reason',
                                   'measured_date', 'scope_fix_applied', 'scope_fix_commit']:
                        if value is not None:
                            lines.append(f"  {key}: {value}")

                # Include tolerance if present
                if 'tolerance' in verified:
                    lines.append(f"  Tolerance: {verified['tolerance']}")

                lines.append("")

    # ========================================================================
    # 9. SALES TARGETS AND GAP TO PLAN
    # ========================================================================
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    if targets_path.exists():
        with open(targets_path) as f:
            targets_config = yaml.safe_load(f)

        lines.append("## Sales Targets")
        lines.append("")

        # Get current fiscal quarter to show relevant target
        today = date.today()
        if today.month >= fy_start_month:
            current_fy = today.year + 1
        else:
            current_fy = today.year

        # Determine which quarter we're in
        month_in_fy = (today.month - fy_start_month) % 12
        current_q = (month_in_fy // 3) + 1

        current_quarter_key = f"fy{current_fy}_q{current_q}"

        targets = targets_config.get('targets', {})

        # Show current quarter targets first
        if current_quarter_key in targets:
            qt = targets[current_quarter_key]
            lines.append(f"**FY{current_fy} Q{current_q} Targets** (basis: {qt.get('basis', 'incremental_arr')})")
            lines.append(f"  Team total: ${qt['team_total']:,}")
            lines.append("")

            # Rep targets
            lines.append("  Individual quotas:")
            reps = qt.get('reps', {})
            for email, rep_data in reps.items():
                target = rep_data['target'] if isinstance(rep_data, dict) else rep_data
                note = ""
                if isinstance(rep_data, dict):
                    if rep_data.get('ramp'):
                        note = " (ramp quota)"
                    elif rep_data.get('note'):
                        note = f" — {rep_data['note']}"
                lines.append(f"    {email}: ${target:,}{note}")
            lines.append("")

            # Non-quota roles
            if 'non_quota_roles' in qt:
                lines.append("  Account Managers (no individual quota):")
                for email in qt['non_quota_roles']:
                    lines.append(f"    {email}")
                lines.append("")
                if 'non_quota_note' in qt:
                    lines.append(f"  Note: {qt['non_quota_note']}")
                    lines.append("")

        lines.append("**Gap to Plan Frame:**")
        lines.append("  Default frame for forecast/pipeline/attainment questions:")
        lines.append("  ✓ 'Q3 forecast is $1.9M against $1.55M target — $350K headroom'")
        lines.append("  ✗ 'Q3 forecast is $1.9M' (no context)")
        lines.append("")

        lines.append("**Conversion Rate vs Coverage:**")
        lines.append("  CRITICAL: Conversion rate is MEASURED from outcomes, NEVER derived from coverage.")
        lines.append("  ✓ Conversion rate comes from metrics registry: 9.9% (trailing 3Q average)")
        lines.append("  ✗ DO NOT compute conversion by inverting coverage (e.g., 1/15.33 = 6.5%)")
        lines.append("  ✗ Coverage is observed (pipeline ÷ quota), conversion is historical (won ÷ qualified)")
        lines.append("")
        lines.append("**Required Pipeline:**")
        lines.append("  Formula: required_pipeline = target ÷ verified_conversion_rate")
        lines.append("  Example: At 9.9% conversion, $2.1M target needs $21.2M qualified pipeline")
        lines.append("  DO NOT use coverage multiples (2.5x, 3x, etc.) - use verified conversion rate")
        lines.append("")

    return "\n".join(lines)
