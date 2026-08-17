"""
Stage-aware MEDDICC requirements for deal risk assessment.

Loads stage progression requirements from config/client.yaml and provides
helpers to determine which components are expected at each stage.
"""
import yaml
from pathlib import Path
from typing import Dict, Optional

# Cache the config to avoid repeated file reads
_config_cache = None

def _load_config() -> dict:
    """Load config from client.yaml (cached)."""
    global _config_cache
    if _config_cache is None:
        config_path = Path(__file__).parent.parent / "config" / "client.yaml"
        with open(config_path) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def _get_stage_by_id(stage_id: str) -> Optional[dict]:
    """Get stage metadata by ID from config."""
    config = _load_config()
    for pipeline in config.get("pipeline", {}).get("pipelines", []):
        for stage in pipeline.get("stages", []):
            if stage.get("id") == stage_id:
                return {
                    "id": stage["id"],
                    "name": stage["name"],
                    "order": stage["order"],
                    "exclude_from_analysis": stage.get("exclude_from_analysis", False),
                    "is_won": stage.get("is_won", False),
                    "is_lost": stage.get("is_lost", False),
                }
    return None


def get_requirements_for_stage(stage_id: str) -> Dict[str, int]:
    """
    Returns the component score requirements a deal at this stage needs
    to meet to ADVANCE to the next stage.

    For example, a Discovery-stage deal returns {"pain": 5, "champion": 4}
    — the requirements to reach Scoping. Components not in this dict are
    not yet expected to be strong.

    Returns {} for terminal stages (Closed Won/Lost) or stages with
    exclude_from_analysis=true.

    Mapping from config stage_progression keys to stage IDs:
    - discovery_to_scoping: from appointmentscheduled (Discovery)
    - scoping_to_proposal: from qualifiedtobuy (Scoping)
    - proposal_to_negotiating: from presentationscheduled (Tech Eval)
    - negotiating_to_closed_won: from 24682892 (Negotiating)
    """
    config = _load_config()
    stage_prog = config.get("stage_progression", {})

    # Get stage metadata
    stage = _get_stage_by_id(stage_id)
    if not stage:
        return {}

    # Terminal or excluded stages have no requirements
    if stage.get("exclude_from_analysis") or stage.get("is_won") or stage.get("is_lost"):
        return {}

    # Map stage IDs to progression keys
    stage_to_progression = {
        "appointmentscheduled": "discovery_to_scoping",  # Discovery
        "qualifiedtobuy": "scoping_to_proposal",  # Scoping
        "presentationscheduled": "proposal_to_negotiating",  # Tech Eval
        "24682892": "negotiating_to_closed_won",  # Negotiating
    }

    progression_key = stage_to_progression.get(stage_id)
    if not progression_key:
        # Stage not in requirements table (e.g., Review, Awaiting Signature)
        # Default: no specific requirements
        return {}

    # Load requirements for this progression
    reqs = stage_prog.get(progression_key, {})

    # Convert config keys to MEDDICC component names
    component_mapping = {
        "identified_pain": "pain",
        "champion": "champion",
        "metrics": "metrics",
        "economic_buyer": "economic_buyer",
        "decision_criteria": "decision_criteria",
        "decision_process": "decision_process",
        "competition": "competition",
        "all_components_minimum": "__all__",  # Special marker for all components
    }

    requirements = {}
    for config_key, threshold in reqs.items():
        if config_key == "minimum_stakeholders":
            # Not a MEDDICC component score, skip
            continue

        component = component_mapping.get(config_key)
        if component and component != "__all__":
            requirements[component] = threshold
        elif component == "__all__":
            # All components must meet this threshold
            for comp in ["metrics", "economic_buyer", "decision_criteria",
                        "decision_process", "champion", "pain", "competition"]:
                if comp not in requirements:  # Don't override specific higher requirements
                    requirements[comp] = threshold

    return requirements


def get_component_risk_level(stage_id: str, component: str, score: int) -> Optional[str]:
    """
    Returns "at_risk" if this component's score is below what's required
    to advance FROM the deal's current stage.

    Returns None if this component isn't part of the current stage's
    requirements (i.e. not yet due — NOT a risk signal, regardless of
    how low the score is).

    Args:
        stage_id: Deal's current HubSpot stage ID
        component: MEDDICC component name (e.g., "champion", "economic_buyer")
        score: Current score for this component (0-10)

    Returns:
        "at_risk" if below requirement, None if not required or score is sufficient
    """
    requirements = get_requirements_for_stage(stage_id)

    # Component not required at this stage
    if component not in requirements:
        return None

    required_threshold = requirements[component]

    # Score is below requirement
    if score < required_threshold:
        return "at_risk"

    # Score meets or exceeds requirement
    return None
