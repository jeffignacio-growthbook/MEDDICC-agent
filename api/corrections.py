"""
Wave 5a — Corrections become proposals

When someone says the agent got something wrong, ask whether the correction
is general or specific to this question. A one-off and a rule are different
artifacts and the agent can't tell them apart without asking.

General corrections write to the proposal queue with the conversation as evidence.
"""
import re
import json
from typing import Optional, Dict, Tuple
from datetime import datetime


CORRECTION_PATTERNS = [
    # Direct corrections
    r"(?:that'?s|this is)\s+(?:wrong|incorrect|not right)",
    r"(?:you'?re|agent is)\s+(?:wrong|incorrect|mistaken)",
    r"(?:actually|no,?)\s+(?:it'?s|the)",

    # Negations
    r"that'?s not (?:right|correct|true)",
    r"not (?:true|correct|right|accurate)",

    # Corrections with values
    r"(?:should be|is actually|really is)\s+\d",
    r"(?:not|isn't|aren't)\s+\$?\d",

    # Field/definition corrections
    r"(?:use|uses|should use|value on)\s+\w+",
    r"(?:not|don't|doesn't)\s+(?:use|include|count)",

    # Examples from debugging session
    r"renewals?\s+(?:value|should|uses?)\s+on\s+\w+",
    r"reps?\s+(?:forecast|measure|track)\s+\w+\s+(?:ARR|only|not)",
    r"Review\s+is\s+(?:a\s+)?(?:parking\s+lot|stage)",
    r"targets?\s+use\s+\w+(?:'s)?\s+email",
]

CORRECTION_REGEX = re.compile(
    '|'.join(f'({p})' for p in CORRECTION_PATTERNS),
    re.IGNORECASE
)


def detect_correction(user_message: str) -> bool:
    """
    Detect if user message contains a correction.
    Returns True if correction language is present.
    """
    return bool(CORRECTION_REGEX.search(user_message))


def ask_correction_scope(user_message: str) -> str:
    """
    Generate prompt asking if correction is general or specific.

    Returns a question that Claude can ask the user to determine
    whether this correction should become a proposal or is one-off.
    """
    return (
        "I see you're correcting something. Quick question: "
        "is this correction general (applies to all future questions like this) "
        "or specific to this one question?\n\n"
        "• **General** → I'll create a proposal for review\n"
        "• **Specific** → I'll just fix this answer"
    )


def extract_correction_facts(
    user_message: str,
    agent_prior_response: str
) -> Dict:
    """
    Extract the key facts from a correction.

    Returns dict with:
        - what_was_wrong: What the agent said that was incorrect
        - what_is_right: The correct value/definition
        - correction_type: field_value | semantic_rule | stage_definition | calculation_method
    """
    facts = {
        'what_was_wrong': None,
        'what_is_right': None,
        'correction_type': 'unknown',
        'raw_correction': user_message,
        'raw_prior_response': agent_prior_response[:500]  # First 500 chars
    }

    # Try to extract specific patterns
    user_lower = user_message.lower()

    # Field value corrections (e.g., "renewals value on renewal_revenue")
    field_match = re.search(
        r'(\w+)\s+(?:value|uses?|should use|is on|on)\s+[\'"]?(\w+)[\'"]?',
        user_message,
        re.IGNORECASE
    )
    if field_match:
        facts['what_was_wrong'] = f"Using wrong field for {field_match.group(1)}"
        facts['what_is_right'] = f"Use field: {field_match.group(2)}"
        facts['correction_type'] = 'field_value'
        return facts

    # Measurement corrections (e.g., "reps forecast Incremental ARR only")
    if 'forecast' in user_lower or 'measure' in user_lower or 'track' in user_lower:
        facts['correction_type'] = 'calculation_method'
        if 'incremental arr' in user_lower and 'only' in user_lower:
            facts['what_is_right'] = 'Reps are measured on Incremental ARR only (new_arr + expansion_arr)'
        elif 'not' in user_lower or "don't" in user_lower:
            facts['what_is_right'] = f"Exclusion rule from user message"
        return facts

    # Stage semantic corrections (e.g., "Review is a parking lot")
    stage_match = re.search(
        r'(\w+)\s+(?:is|means|stage|called)\s+(?:a\s+)?(\w+(?:\s+\w+)?)',
        user_message,
        re.IGNORECASE
    )
    if stage_match:
        facts['correction_type'] = 'stage_definition'
        facts['what_was_wrong'] = f"Misunderstood stage: {stage_match.group(1)}"
        facts['what_is_right'] = f"{stage_match.group(1)} = {stage_match.group(2)}"
        return facts

    # Email/identity corrections
    if 'email' in user_lower or '@' in user_message:
        facts['correction_type'] = 'identity_mapping'
        facts['what_is_right'] = 'See user message for correct email pattern'
        return facts

    # Numeric corrections
    number_match = re.search(r'(?:actually|should be|is)\s+\$?([\d,]+(?:\.\d+)?)', user_message)
    if number_match:
        facts['what_is_right'] = f"Correct value: {number_match.group(1)}"
        facts['correction_type'] = 'numeric_value'

        # Try to find what was wrong in agent response
        agent_numbers = re.findall(r'\$?([\d,]+(?:\.\d+)?)', agent_prior_response)
        if agent_numbers:
            facts['what_was_wrong'] = f"Incorrect value: {agent_numbers[0]}"
        return facts

    return facts


def create_correction_proposal(
    correction_facts: Dict,
    thread_ts: str,
    user_id: str,
    handler_name: str
) -> Dict:
    """
    Create a proposal record for a general correction.

    Returns dict ready to insert into proposals table.
    """
    # Map correction types to entity types
    correction_to_entity = {
        'field_value': 'field_definition',
        'calculation_method': 'calculation_methodology',
        'stage_definition': 'stage_semantics',
        'identity_mapping': 'identity_convention',
        'numeric_value': 'verified_metric'
    }

    entity_type = correction_to_entity.get(
        correction_facts['correction_type'],
        'general_correction'
    )

    # Generate entity_key from the correction
    entity_key = f"{handler_name}_{correction_facts['correction_type']}"

    # Build evidence
    evidence = {
        'thread_ts': thread_ts,
        'user_id': user_id,
        'handler_name': handler_name,
        'correction_type': correction_facts['correction_type'],
        'timestamp': datetime.utcnow().isoformat()
    }

    # Build rationale
    rationale_parts = []
    if correction_facts['what_was_wrong']:
        rationale_parts.append(f"**What was wrong:** {correction_facts['what_was_wrong']}")
    if correction_facts['what_is_right']:
        rationale_parts.append(f"**Correct approach:** {correction_facts['what_is_right']}")
    rationale_parts.append(f"\n**User correction:** {correction_facts['raw_correction'][:200]}")

    rationale = '\n\n'.join(rationale_parts)

    return {
        'entity_type': entity_type,
        'entity_key': entity_key,
        'current_value': None,  # Could extract from handler code
        'proposed_value': {
            'correction': correction_facts['what_is_right'],
            'type': correction_facts['correction_type']
        },
        'rationale': rationale,
        'evidence': evidence,
        'evidence_count': 1,  # Single user correction
        'conversation_evidence': {
            'thread_ts': thread_ts,
            'user_message': correction_facts['raw_correction'],
            'agent_response': correction_facts['raw_prior_response'],
            'correction': correction_facts['what_is_right']
        },
        'affects_handlers': correction_facts['correction_type'] in ['field_value', 'calculation_method'],
        'requires_regeneration': False,
        'proposed_by': f'user_{user_id}_via_agent'
    }


# Examples from the debugging session that should have become proposals
EXAMPLE_CORRECTIONS = [
    {
        'user_message': 'renewals value on renewal_revenue',
        'what_should_happen': 'Proposal: field_definition for renewals → use renewal_revenue field',
        'handler': 'query_renewals'
    },
    {
        'user_message': 'reps forecast Incremental ARR only',
        'what_should_happen': 'Proposal: calculation_methodology → new_arr + expansion_arr, exclude renewal base',
        'handler': 'query_rep_attainment'
    },
    {
        'user_message': 'Review is a parking lot',
        'what_should_happen': 'Proposal: stage_semantics → Review stage = deals on hold',
        'handler': 'query_pipeline'
    },
    {
        'user_message': "targets use HubSpot's email convention",
        'what_should_happen': 'Proposal: identity_convention → use HubSpot owner emails exactly',
        'handler': 'query_rep_attainment'
    }
]
