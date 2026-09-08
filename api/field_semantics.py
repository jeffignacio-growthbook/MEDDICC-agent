"""
AUTO-GENERATED from config/field_semantics.yaml by scripts/generate_field_semantics.py.
DO NOT EDIT BY HAND. Regenerate after changing the yaml.

Generated: 2026-09-06 05:14:42 UTC
"""

STAGE_MAP = {'appointmentscheduled': {'label': 'Discovery', 'bucket': 'discovery', 'transition': 'discovery_to_scoping'}, 'qualifiedtobuy': {'label': 'Scoping', 'bucket': 'scoping', 'transition': 'scoping_to_proposal'}, 'presentationscheduled': {'label': 'Technical Evaluation', 'bucket': 'proposal', 'transition': 'proposal_to_negotiating'}, 'decisionmakerboughtin': {'label': 'Review', 'bucket': 'proposal', 'transition': None, 'exclude_from_analysis': True}, 'contractsent': {'label': 'Contract Sent', 'bucket': 'proposal', 'transition': None, 'historical': True}, 'closedwon': {'label': 'Closed Won', 'bucket': 'closed_won', 'transition': None, 'aliases': ['1297321623']}, 'closedlost': {'label': 'Closed Lost', 'bucket': 'closed_lost', 'transition': None, 'aliases': ['1297321624', '68509551'], 'alias_labels': ['Disqualified']}, '79653122': {'label': 'Meeting Set', 'bucket': 'discovery', 'transition': None}, '24682892': {'label': 'Negotiating', 'bucket': 'proposal', 'transition': None}, '43449439': {'label': 'Awaiting Signature', 'bucket': 'proposal', 'transition': None}, '1297321618': {'label': 'Upcoming Renewal', 'bucket': 'discovery', 'transition': None}, '1297321619': {'label': 'Renewal Engaged', 'bucket': 'scoping', 'transition': None}, '1297321620': {'label': 'Pricing Presented', 'bucket': 'proposal', 'transition': None}, '1297321622': {'label': 'Contract Sent (Renewal)', 'bucket': 'proposal', 'transition': None}}

OUTCOME_BUCKETS = {'won': ['closed_won'], 'lost': ['closed_lost'], 'open': ['discovery', 'scoping', 'proposal']}

FIELD_UNITS = {'arr_usd': 'US dollars, annual recurring', 'deal_value': 'US dollars, incremental ARR (new + expansion)', 'duration_minutes': 'minutes', 'champion_score': '0-10 MEDDICC component', 'economic_buyer_score': '0-10 MEDDICC component', 'metrics_score': '0-10 MEDDICC component', 'decision_criteria_score': '0-10 MEDDICC component', 'decision_process_score': '0-10 MEDDICC component', 'identify_pain_score': '0-10 MEDDICC component', 'compelling_event_score': '0-10 MEDDICC component', 'overall_score': '0-70 MEDDICC total'}

# Hard-deleted stage ids seen only in property history. Acknowledged, but
# deliberately NOT classified — see config/field_semantics.yaml.
RETIRED_STAGES = {'24682891': {'last_seen': '2023-04-14', 'first_seen': '2022-06-03', 'entries': 15, 'deals': 14, 'reason': 'Hard-deleted custom stage from the pre-2023 default pipeline. Numerically adjacent to 24682892 (Negotiating), so created alongside it. Was the first history entry for 13 of 14 deals, and led to Negotiating, Review or Scoping. Bucket left unassigned: the transition evidence is ambiguous between an early and a mid stage, and a wrong bucket would stop erroring and start lying.\n'}, '43746397': {'last_seen': '2022-11-21', 'first_seen': '2022-11-21', 'entries': 3, 'deals': 3, 'reason': 'Hard-deleted custom stage. Always preceded by 24682891 or Closed Won and always followed by Review. Three entries on a single day across three deals, which reads like a one-off pipeline edit rather than a stage deals genuinely worked through.\n'}}

# Reverse lookup: alias -> canonical stage_id
_ALIAS_TO_CANONICAL = {'appointmentscheduled': 'appointmentscheduled', 'qualifiedtobuy': 'qualifiedtobuy', 'presentationscheduled': 'presentationscheduled', 'decisionmakerboughtin': 'decisionmakerboughtin', 'contractsent': 'contractsent', 'closedwon': 'closedwon', '1297321623': 'closedwon', 'closedlost': 'closedlost', '1297321624': 'closedlost', '68509551': 'closedlost', '79653122': '79653122', '24682892': '24682892', '43449439': '43449439', '1297321618': '1297321618', '1297321619': '1297321619', '1297321620': '1297321620', '1297321622': '1297321622'}

# Reverse lookup: display label -> stage_id (for CSV imports with display names)
_LABEL_TO_STAGE_ID = {'Discovery': 'appointmentscheduled', 'Scoping': 'qualifiedtobuy', 'Technical Evaluation': 'presentationscheduled', 'Review': 'decisionmakerboughtin', 'Contract Sent': 'contractsent', 'Closed Won': 'closedwon', 'Closed Lost': 'closedlost', 'Disqualified': 'closedlost', 'Meeting Set': '79653122', 'Negotiating': '24682892', 'Awaiting Signature': '43449439', 'Upcoming Renewal': '1297321618', 'Renewal Engaged': '1297321619', 'Pricing Presented': '1297321620', 'Contract Sent (Renewal)': '1297321622'}

def canonical_stage(stage_id: str) -> str:
    """
    Resolve a raw stage id (including numeric aliases) to its canonical stage key.
    Unknown ids return the input unchanged.

    Examples:
        canonical_stage('1297321623') -> 'closedwon'
        canonical_stage('closedwon') -> 'closedwon'
        canonical_stage('unknown_stage') -> 'unknown_stage'
    """
    if not stage_id:
        return stage_id
    return _ALIAS_TO_CANONICAL.get(stage_id, stage_id)

def stage_bucket(stage_id: str) -> str:
    """
    Return the pipeline bucket for a stage id:
    'discovery'|'scoping'|'proposal'|'closed_won'|'closed_lost'|'unknown'.

    Resolves aliases first. This REPLACES the _stage_bucket() helper
    currently inline in handlers.py.

    Examples:
        stage_bucket('appointmentscheduled') -> 'discovery'
        stage_bucket('presentationscheduled') -> 'proposal'
        stage_bucket('1297321623') -> 'closed_won'
        stage_bucket('68509551') -> 'closed_lost'
    """
    if not stage_id:
        return 'unknown'
    canonical = canonical_stage(stage_id)
    stage_info = STAGE_MAP.get(canonical)
    if not stage_info:
        return 'unknown'
    return stage_info.get('bucket', 'unknown')

def stage_label(stage_id: str) -> str:
    """
    Human label for a stage id, e.g. 'Technical Evaluation'.
    Returns the stage_id if not found.

    Examples:
        stage_label('presentationscheduled') -> 'Technical Evaluation'
        stage_label('1297321623') -> 'Closed Won'
    """
    if not stage_id:
        return stage_id
    canonical = canonical_stage(stage_id)
    stage_info = STAGE_MAP.get(canonical)
    if not stage_info:
        return stage_id
    return stage_info.get('label', stage_id)

def is_won(stage_id: str) -> bool:
    """
    True if this stage id (or alias) means closed won.

    Examples:
        is_won('closedwon') -> True
        is_won('1297321623') -> True
        is_won('closedlost') -> False
    """
    if not stage_id:
        return False
    bucket = stage_bucket(stage_id)
    return bucket in OUTCOME_BUCKETS['won']

def is_lost(stage_id: str) -> bool:
    """
    True if this stage id (or alias) means closed lost.

    Examples:
        is_lost('closedlost') -> True
        is_lost('68509551') -> True  # Disqualified alias
        is_lost('closedwon') -> False
    """
    if not stage_id:
        return False
    bucket = stage_bucket(stage_id)
    return bucket in OUTCOME_BUCKETS['lost']

def is_open(stage_id: str) -> bool:
    """
    True if the deal is still open (not won/lost).

    Examples:
        is_open('appointmentscheduled') -> True
        is_open('presentationscheduled') -> True
        is_open('closedwon') -> False
        is_open('1297321623') -> False
        is_open('unknown_stage') -> True  # Unknown stages default to open
    """
    if not stage_id:
        return True  # Unknown stages treated as open for safety
    bucket = stage_bucket(stage_id)
    # Unknown bucket also treated as open for safety
    return bucket in OUTCOME_BUCKETS['open'] or bucket == 'unknown'

def stage_transition(stage_id: str) -> str | None:
    """
    The transition key for a stage, e.g. 'discovery_to_scoping'.
    Returns None if no transition defined.

    Examples:
        stage_transition('appointmentscheduled') -> 'discovery_to_scoping'
        stage_transition('closedwon') -> None
    """
    if not stage_id:
        return None
    canonical = canonical_stage(stage_id)
    stage_info = STAGE_MAP.get(canonical)
    if not stage_info:
        return None
    return stage_info.get('transition')

def is_historical_stage(stage_id: str) -> bool:
    """
    True if this stage is classified but is not a stage in any live pipeline.

    Such a stage must stay classified so reconstruction can read the history
    that contains it, while being legitimately absent from client.yaml. This
    is a third category, separate from retired_stages (which cannot be
    classified at all).
    """
    if not stage_id:
        return False
    info = STAGE_MAP.get(canonical_stage(stage_id))
    return bool(info and info.get('historical'))

def is_retired_stage(stage_id: str) -> bool:
    """
    True if this id is an acknowledged hard-deleted stage.

    Acknowledged is not classified: reconstruction still raises on these.
    This exists so the discovery gate can tell "known and unreachable" apart
    from "new and unknown", which is a genuine blocker.
    """
    if not stage_id:
        return False
    return str(stage_id) in RETIRED_STAGES

def label_to_stage_id(display_label: str) -> str:
    """
    Convert a display label to its stage ID.
    Used for CSV imports that return display names instead of stage IDs.

    Returns the input unchanged if not found (allowing passthrough for already-canonical IDs).

    Examples:
        label_to_stage_id('Closed Won') -> 'closedwon'
        label_to_stage_id('Disqualified') -> '68509551'
        label_to_stage_id('Discovery') -> 'appointmentscheduled'
        label_to_stage_id('appointmentscheduled') -> 'appointmentscheduled'  # passthrough
    """
    if not display_label:
        return display_label
    return _LABEL_TO_STAGE_ID.get(display_label, display_label)

def is_at_risk_quick(analysis: dict) -> bool:
    """
    Quick at-risk check for pipeline summaries (performance mode).

    Uses simple thresholds from field_semantics.yaml:
    - overall_score < 40 OR champion_score < 4

    This is NOT the canonical at-risk definition (that's stage-aware
    band checking in api/handlers.py). Use this only for lightweight
    checks where full stage-aware logic would be too expensive.

    Args:
        analysis: Dict with 'overall_score', 'champion_score' keys

    Returns:
        True if deal meets quick-check at-risk criteria

    Examples:
        is_at_risk_quick({"overall_score": 35, "champion_score": 6}) -> True (score < 40)
        is_at_risk_quick({"overall_score": 50, "champion_score": 3}) -> True (champ < 4)
        is_at_risk_quick({"overall_score": 50, "champion_score": 7}) -> False
        is_at_risk_quick({}) -> False (missing data not at-risk)

    Note:
        Consolidated in Wave 4 remediation from duplicate implementations:
        - query_waterfall used this logic inline
        - query_deals_at_risk uses stage-aware (canonical)
    """
    if not analysis:
        return False
    overall = analysis.get("overall_score", 0) or 0
    champion = analysis.get("champion_score", 0) or 0
    return overall < 40 or champion < 4


# ============================================================================
# PIPELINE CLASSIFICATION — HAND-WRITTEN BUSINESS LOGIC
# ============================================================================
# These helpers implement the PIPELINE SEMANTICS from config/field_semantics.yaml.
# They distinguish Incremental ARR (pipeline) from Renewal base ARR.
#
# DO NOT AUTO-GENERATE — these encode client-specific business definitions.
# ============================================================================

# Renewal pipeline ID from config/client.yaml
_RENEWAL_PIPELINE_ID = "866608541"

def is_incremental_pipeline(deal: dict) -> bool:
    """
    True if deal contributes to PIPELINE (Incremental ARR).

    Pipeline means expansion_arr + new_arr (excludes renewal base).

    A deal is in pipeline if:
      - It's in new business pipeline (pipeline_id != renewal), OR
      - It has expansion_arr > 0 OR new_arr > 0

    Args:
        deal: Dict with pipeline_id, expansion_arr, new_arr keys

    Returns:
        True if deal contributes to incremental ARR pipeline

    Examples:
        is_incremental_pipeline({"pipeline_id": "default", "new_arr": 100000}) -> True
        is_incremental_pipeline({"pipeline_id": "866608541", "expansion_arr": 50000}) -> True (renewal + expansion)
        is_incremental_pipeline({"pipeline_id": "866608541", "renewal_revenue": 200000}) -> False (pure renewal)

    Note:
        Per PIPELINE SEMANTICS in config/field_semantics.yaml:
        "Pipeline" = Incremental ARR only. Renewal base excluded and reported separately.
    """
    if not deal:
        return False

    pipeline_id = deal.get("pipeline_id", "")
    expansion_arr = deal.get("expansion_arr", 0) or 0
    new_arr = deal.get("new_arr", 0) or 0

    # New business pipeline always counts
    if pipeline_id != _RENEWAL_PIPELINE_ID:
        return True

    # Renewal pipeline: only counts if has incremental ARR
    return expansion_arr > 0 or new_arr > 0


def is_renewal_base(deal: dict) -> bool:
    """
    True if deal contributes to RENEWAL ARR (renewal base, not expansion).

    Renewal ARR is separate from pipeline and reported via query_upcoming_renewals.

    A deal is renewal base if:
      - It's in renewal pipeline (pipeline_id == renewal_pipeline_id), AND
      - It has renewal_revenue > 0

    Args:
        deal: Dict with pipeline_id, renewal_revenue keys

    Returns:
        True if deal contributes to renewal base ARR

    Examples:
        is_renewal_base({"pipeline_id": "866608541", "renewal_revenue": 200000}) -> True
        is_renewal_base({"pipeline_id": "default", "new_arr": 100000}) -> False
        is_renewal_base({"pipeline_id": "866608541", "expansion_arr": 50000, "renewal_revenue": 0}) -> False

    Note:
        Renewal base is excluded from "pipeline" and reported separately.
        See PIPELINE SEMANTICS in config/field_semantics.yaml.
    """
    if not deal:
        return False

    pipeline_id = deal.get("pipeline_id", "")
    renewal_revenue = deal.get("renewal_revenue", 0) or 0

    return pipeline_id == _RENEWAL_PIPELINE_ID and renewal_revenue > 0


# ============================================================================
# DATA INTEGRITY — UNIVERSAL RULES (NOT CLIENT-SPECIFIC)
# ============================================================================
# These rules apply to EVERY client and enforce baseline data hygiene.
# See DATA INTEGRITY RULES in config/field_semantics.yaml for rationale.
# ============================================================================

def is_valid_cycle_deal(deal: dict) -> bool:
    """
    True if deal has valid cycle time data (create_date and close_date exist, cycle >= 0).

    UNIVERSAL RULE: Negative cycle time is definitionally impossible and indicates
    CRM migration backfill, bulk import artifacts, or data entry error.

    A deal is valid for cycle time if:
      - It has both create_date and close_date (not NULL)
      - (close_date - create_date) >= 0 (non-negative cycle)

    This check is MANDATORY for ALL metrics using create_date/close_date:
      - cycle_time (median days from create to close)
      - win_rate (when computing with closed deals)
      - velocity_to_close (days in each stage)
      - conversion_rates (time-based funnel metrics)

    Args:
        deal: Dict with create_date, close_date keys (ISO format strings or datetime objects)

    Returns:
        True if deal has valid cycle time data, False otherwise

    Examples:
        is_valid_cycle_deal({"create_date": "2023-01-01", "close_date": "2023-02-01"}) -> True
        is_valid_cycle_deal({"create_date": "2025-08-09", "close_date": "2023-10-21"}) -> False (negative)
        is_valid_cycle_deal({"create_date": None, "close_date": "2023-02-01"}) -> False (missing create)
        is_valid_cycle_deal({"create_date": "2023-01-01", "close_date": None}) -> False (missing close)
        is_valid_cycle_deal({}) -> False (missing both)

    Template-portable:
        This is a DEFAULT, non-configurable rule. Every client gets this automatically.
        CRM migrations and backfills are common enough that this is baseline hygiene.

    Monitoring:
        Violations flagged by scripts/monitor_negative_cycle_times.py (Wave 6).

    Note:
        Deal exclusion example: deal_id=41609747117 (Netthandelsgruppen)
        create_date=2025-08-09, close_date=2023-10-21 → -658 days → excluded
    """
    if not deal:
        return False

    create_date_str = deal.get("create_date")
    close_date_str = deal.get("close_date")

    # Must have both dates
    if not create_date_str or not close_date_str:
        return False

    # Parse dates
    try:
        from datetime import datetime

        # Handle both ISO string and datetime object
        if isinstance(create_date_str, str):
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
        else:
            create_date = create_date_str

        if isinstance(close_date_str, str):
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
        else:
            close_date = close_date_str

        # Check for non-negative cycle time
        cycle_days = (close_date - create_date).days
        return cycle_days >= 0

    except (ValueError, AttributeError, TypeError):
        # Date parsing failed - exclude
        return False


def is_fresh_pipeline_deal(deal: dict, stale_threshold_days: int = 180) -> bool:
    """
    Check if a deal is "fresh" (not stale/abandoned).

    A deal is considered stale if it has been open for more than stale_threshold_days
    with no meaningful movement. Stale deals contaminate pipeline health metrics.

    Args:
        deal: Deal dict with stage and create_date
        stale_threshold_days: Days threshold (default 180, client-specific)

    Returns:
        True if deal is fresh (< threshold days old)
        False if deal is stale (>= threshold days old) or missing data

    Discovered: Phase 2b validation (2026-09-07)
    Evidence: 4 deals >180 days old ($155K, 2.2% of pipeline)
    """
    if not deal:
        return False

    # Must be an open deal
    stage = deal.get("stage")
    if not stage or not is_open(stage):
        # Only filter open pipeline - closed deals are fine
        return True

    create_date_str = deal.get("create_date")
    if not create_date_str:
        # No create date - can't determine age, exclude to be safe
        return False

    # Calculate age
    try:
        from datetime import datetime

        if isinstance(create_date_str, str):
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
        else:
            create_date = create_date_str

        now = datetime.now(create_date.tzinfo)
        age_days = (now - create_date).days

        return age_days <= stale_threshold_days

    except (ValueError, AttributeError, TypeError):
        # Date parsing failed - exclude to be safe
        return False


# ============================================================================
# REGION CLASSIFICATION
# ============================================================================
# Maps company geography to sales regions (NAM, EMEA, APAC, LATAM, ROW).
# Data source: HubSpot Company.country property (90.9% coverage)
# See config/regions.yaml for full country mappings.
# ============================================================================

# Country -> Region mapping (generated from config/regions.yaml)
_COUNTRY_TO_REGION = {
    "Algeria": "EMEA",
    "Argentina": "LATAM",
    "Australia": "APAC",
    "Austria": "EMEA",
    "Bahrain": "EMEA",
    "Bangladesh": "APAC",
    "Belarus": "EMEA",
    "Belgium": "EMEA",
    "Bolivia": "LATAM",
    "Brazil": "LATAM",
    "Bulgaria": "EMEA",
    "Canada": "NAM",
    "Chile": "LATAM",
    "China": "APAC",
    "Colombia": "LATAM",
    "Costa Rica": "LATAM",
    "Croatia": "EMEA",
    "Czech Republic": "EMEA",
    "Denmark": "EMEA",
    "Dominican Republic": "LATAM",
    "Ecuador": "LATAM",
    "Egypt": "EMEA",
    "El Salvador": "LATAM",
    "Estonia": "EMEA",
    "Finland": "EMEA",
    "France": "EMEA",
    "Germany": "EMEA",
    "Ghana": "EMEA",
    "Greece": "EMEA",
    "Guatemala": "LATAM",
    "Honduras": "LATAM",
    "Hong Kong": "APAC",
    "Hungary": "EMEA",
    "Iceland": "EMEA",
    "India": "APAC",
    "Indonesia": "APAC",
    "Ireland": "EMEA",
    "Israel": "EMEA",
    "Italy": "EMEA",
    "Japan": "APAC",
    "Jordan": "EMEA",
    "Kenya": "EMEA",
    "Kuwait": "EMEA",
    "Latvia": "EMEA",
    "Lebanon": "EMEA",
    "Lithuania": "EMEA",
    "Luxembourg": "EMEA",
    "Malaysia": "APAC",
    "Malta": "EMEA",
    "Mexico": "NAM",
    "Moldova": "EMEA",
    "Morocco": "EMEA",
    "Netherlands": "EMEA",
    "New Zealand": "APAC",
    "Nicaragua": "LATAM",
    "Nigeria": "EMEA",
    "Norway": "EMEA",
    "Oman": "EMEA",
    "Pakistan": "APAC",
    "Panama": "LATAM",
    "Paraguay": "LATAM",
    "Peru": "LATAM",
    "Philippines": "APAC",
    "Poland": "EMEA",
    "Portugal": "EMEA",
    "Puerto Rico": "LATAM",
    "Qatar": "EMEA",
    "Romania": "EMEA",
    "Saudi Arabia": "EMEA",
    "Serbia": "EMEA",
    "Singapore": "APAC",
    "Slovakia": "EMEA",
    "Slovenia": "EMEA",
    "South Africa": "EMEA",
    "South Korea": "APAC",
    "Spain": "EMEA",
    "Sweden": "EMEA",
    "Switzerland": "EMEA",
    "Taiwan": "APAC",
    "Thailand": "APAC",
    "The Netherlands": "EMEA",
    "Tunisia": "EMEA",
    "Turkey": "EMEA",
    "Ukraine": "EMEA",
    "United Arab Emirates": "EMEA",
    "United Kingdom": "EMEA",
    "United States": "NAM",
    "Uruguay": "LATAM",
    "Venezuela": "LATAM",
    "Vietnam": "APAC",
}

def get_region(deal: dict) -> str:
    """
    Get region for a deal using company geography.

    Primary classification: Use company_country from HubSpot (90.9% coverage)
    Fallback: Return UNKNOWN for deals with no geography (9.1%)

    Args:
        deal: Deal dict with company_country field

    Returns:
        "NAM" | "EMEA" | "APAC" | "LATAM" | "ROW" | "UNKNOWN"

    Examples:
        get_region({"company_country": "United Kingdom"}) -> "EMEA"
        get_region({"company_country": "United States"}) -> "NAM"
        get_region({"company_country": "India"}) -> "APAC"
        get_region({"company_country": None}) -> "UNKNOWN"

    Note:
        UNKNOWN is returned explicitly for 172 deals (9.1%) with no Company.country.
        These deals are NOT defaulted to NAM or ROW - they must be surfaced
        explicitly in reporting (same pattern as no_signal_at_risk).

        Region classification is based on REAL company geography from HubSpot,
        not owner assumption. For 90.9% of deals, this is accurate.
    """
    company_country = deal.get('company_country')

    # Explicit UNKNOWN handling - NOT defaulted to NAM/ROW
    if not company_country:
        return "UNKNOWN"

    # Map country to region
    region = _COUNTRY_TO_REGION.get(company_country, "ROW")

    return region


def is_test_deal(deal: dict) -> bool:
    """
    True if deal appears to be test/demo data.

    Patterns matched:
    - Exact match: "Test", "Test Org"
    - Contains: "-test", "test-" (lowercase with hyphen)
    - Starts with: "test " (lowercase, space after)
    - Contains: "Teste" (Portuguese test pattern)

    Excludes legitimate companies:
    - TestGorilla (assessment platform)
    - User Testing Inc (UX research)
    - Testbirds (QA platform)

    Args:
        deal: Deal dict with company_name field

    Returns:
        True if deal matches test patterns, False otherwise

    Examples:
        is_test_deal({"company_name": "Test Org"}) -> True
        is_test_deal({"company_name": "sn-test"}) -> True
        is_test_deal({"company_name": "FahadTest"}) -> False (ambiguous)
        is_test_deal({"company_name": "SymplaTeste"}) -> True (Portuguese)
        is_test_deal({"company_name": "TestGorilla"}) -> False (legitimate)
        is_test_deal({"company_name": "User Testing Inc"}) -> False (legitimate)

    Note:
        This is a data hygiene rule (like is_valid_cycle_deal, is_fresh_pipeline_deal).
        Test deals should be excluded from production reports and metrics.

        Found 15 test deals in production HubSpot data (2026-09-08).
        Long-term fix: Add is_test_deal boolean property in HubSpot at source.
    """
    company_name = deal.get('company_name')
    if not company_name:
        return False

    company_name = company_name.strip()

    # Normalize for matching
    name_lower = company_name.lower()

    # Legitimate companies with "Test" in name - do NOT flag
    legitimate_test_companies = [
        'testgorilla',
        'user testing inc',
        'testbirds',
        'testim'
    ]

    if name_lower in legitimate_test_companies:
        return False

    # Exact matches
    if name_lower in ['test', 'test org']:
        return True

    # Hyphenated test patterns (e.g., "sn-test", "zoopla-test")
    if '-test' in name_lower or 'test-' in name_lower:
        return True

    # Starts with "test " (space after, e.g., "test company")
    if name_lower.startswith('test '):
        return True

    # Ends with " test" (space before, e.g., "Jusbrasil Test", "Orkes Test")
    if name_lower.endswith(' test'):
        return True

    # Portuguese test pattern (e.g., "SymplaTeste")
    if 'teste' in name_lower:
        return True

    return False
