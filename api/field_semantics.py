"""
AUTO-GENERATED from config/field_semantics.yaml by scripts/generate_field_semantics.py.
DO NOT EDIT BY HAND. Regenerate after changing the yaml.

Generated: 2026-08-20 15:39:07 UTC
"""

STAGE_MAP = {'appointmentscheduled': {'label': 'Discovery', 'bucket': 'discovery', 'transition': 'discovery_to_scoping'}, 'qualifiedtobuy': {'label': 'Scoping', 'bucket': 'scoping', 'transition': 'scoping_to_proposal'}, 'presentationscheduled': {'label': 'Technical Evaluation', 'bucket': 'proposal', 'transition': 'proposal_to_negotiating'}, 'decisionmakerboughtin': {'label': 'Review', 'bucket': 'proposal', 'transition': None}, 'contractsent': {'label': 'Contract Sent', 'bucket': 'proposal', 'transition': None, 'aliases': ['1297321622']}, 'closedwon': {'label': 'Closed Won', 'bucket': 'closed_won', 'transition': None, 'aliases': ['1297321623']}, 'closedlost': {'label': 'Closed Lost', 'bucket': 'closed_lost', 'transition': None, 'aliases': ['1297321624', '68509551'], 'alias_labels': ['Disqualified']}, '79653122': {'label': 'Meeting Set', 'bucket': 'discovery', 'transition': None}, '24682892': {'label': 'Negotiating', 'bucket': 'proposal', 'transition': None}, '43449439': {'label': 'Awaiting Signature', 'bucket': 'proposal', 'transition': None}, '1297321618': {'label': 'Upcoming Renewal', 'bucket': 'discovery', 'transition': None}, '1297321619': {'label': 'Renewal Engaged', 'bucket': 'scoping', 'transition': None}, '1297321620': {'label': 'Pricing Presented', 'bucket': 'proposal', 'transition': None}}

OUTCOME_BUCKETS = {'won': ['closed_won'], 'lost': ['closed_lost'], 'open': ['discovery', 'scoping', 'proposal']}

FIELD_UNITS = {'arr_usd': 'US dollars, annual recurring', 'deal_value': 'US dollars, total contract value', 'duration_minutes': 'minutes', 'champion_score': '0-10 MEDDICC component', 'economic_buyer_score': '0-10 MEDDICC component', 'metrics_score': '0-10 MEDDICC component', 'decision_criteria_score': '0-10 MEDDICC component', 'decision_process_score': '0-10 MEDDICC component', 'identify_pain_score': '0-10 MEDDICC component', 'compelling_event_score': '0-10 MEDDICC component', 'overall_score': '0-70 MEDDICC total'}

# Hard-deleted stage ids seen only in property history. Acknowledged, but
# deliberately NOT classified — see config/field_semantics.yaml.
RETIRED_STAGES = {'24682891': {'last_seen': '2023-04-14', 'first_seen': '2022-06-03', 'entries': 15, 'deals': 14, 'reason': 'Hard-deleted custom stage from the pre-2023 default pipeline. Numerically adjacent to 24682892 (Negotiating), so created alongside it. Was the first history entry for 13 of 14 deals, and led to Negotiating, Review or Scoping. Bucket left unassigned: the transition evidence is ambiguous between an early and a mid stage, and a wrong bucket would stop erroring and start lying.\n'}, '43746397': {'last_seen': '2022-11-21', 'first_seen': '2022-11-21', 'entries': 3, 'deals': 3, 'reason': 'Hard-deleted custom stage. Always preceded by 24682891 or Closed Won and always followed by Review. Three entries on a single day across three deals, which reads like a one-off pipeline edit rather than a stage deals genuinely worked through.\n'}}

# Reverse lookup: alias -> canonical stage_id
_ALIAS_TO_CANONICAL = {'appointmentscheduled': 'appointmentscheduled', 'qualifiedtobuy': 'qualifiedtobuy', 'presentationscheduled': 'presentationscheduled', 'decisionmakerboughtin': 'decisionmakerboughtin', 'contractsent': 'contractsent', '1297321622': 'contractsent', 'closedwon': 'closedwon', '1297321623': 'closedwon', 'closedlost': 'closedlost', '1297321624': 'closedlost', '68509551': 'closedlost', '79653122': '79653122', '24682892': '24682892', '43449439': '43449439', '1297321618': '1297321618', '1297321619': '1297321619', '1297321620': '1297321620'}

# Reverse lookup: display label -> stage_id (for CSV imports with display names)
_LABEL_TO_STAGE_ID = {'Discovery': 'appointmentscheduled', 'Scoping': 'qualifiedtobuy', 'Technical Evaluation': 'presentationscheduled', 'Review': 'decisionmakerboughtin', 'Contract Sent': 'contractsent', 'Closed Won': 'closedwon', 'Closed Lost': 'closedlost', 'Disqualified': 'closedlost', 'Meeting Set': '79653122', 'Negotiating': '24682892', 'Awaiting Signature': '43449439', 'Upcoming Renewal': '1297321618', 'Renewal Engaged': '1297321619', 'Pricing Presented': '1297321620'}

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
