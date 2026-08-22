"""
MEDDICC scoring rubric with bands and next steps.
Used for general coaching when deal-specific analysis unavailable.
"""

RUBRIC = {
    "metrics": {
        "bands": {
            "red": (0, 3, "No quantified business case"),
            "yellow": (4, 6, "Partial metrics identified"),
            "green": (7, 10, "Strong quantified value"),
        },
        "next_steps": {
            "red": "Ask: 'What specific metrics would you use to measure success?' Get quantified ROI.",
            "yellow": "Confirm: 'You mentioned [metric] — can you share the baseline and target?' Validate business case.",
            "green": "Verify: 'How will you track [metric] post-implementation?' Ensure alignment on success criteria.",
        }
    },
    "economic_buyer": {
        "bands": {
            "red": (0, 3, "Budget holder not identified"),
            "yellow": (4, 6, "Suspected but not confirmed"),
            "green": (7, 10, "Confirmed with access"),
        },
        "next_steps": {
            "red": "Ask: 'Who has final budget approval for [dollar amount] purchases?' Get introduced.",
            "yellow": "Confirm: 'Is [name] the final approver or does it need to go higher?' Validate authority.",
            "green": "Engage: 'What does [EB name] need to see to approve this?' Align on their success criteria.",
        }
    },
    "decision_criteria": {
        "bands": {
            "red": (0, 3, "Criteria unknown"),
            "yellow": (4, 6, "Some criteria surfaced"),
            "green": (7, 10, "Complete criteria documented"),
        },
        "next_steps": {
            "red": "Ask: 'What are the top 3 things you're evaluating solutions on?' Document criteria.",
            "yellow": "Confirm: 'Are there any other must-haves beyond [criteria]?' Complete the list.",
            "green": "Validate: 'How do we score on your criteria?' Ensure alignment and identify gaps.",
        }
    },
    "decision_process": {
        "bands": {
            "red": (0, 3, "Process undefined"),
            "yellow": (4, 6, "Partial timeline known"),
            "green": (7, 10, "Full process mapped"),
        },
        "next_steps": {
            "red": "Ask: 'What does your typical buying process look like for tools like this?' Map stakeholders.",
            "yellow": "Confirm: 'After [step], what happens next and who's involved?' Complete the map.",
            "green": "Align: 'What could slow down your [date] timeline?' Identify and mitigate risks.",
        }
    },
    "identify_pain": {
        "bands": {
            "red": (0, 3, "No business pain articulated"),
            "yellow": (4, 6, "Pain acknowledged but not urgent"),
            "green": (7, 10, "Critical pain with urgency"),
        },
        "next_steps": {
            "red": "Ask: 'What happens if you don't solve this problem?' Quantify impact.",
            "yellow": "Confirm: 'Why is this a priority now vs. 6 months from now?' Establish urgency.",
            "green": "Validate: 'What's the cost of delay on [pain]?' Reinforce urgency and timeline.",
        }
    },
    "champion": {
        "bands": {
            "red": (0, 3, "No internal advocate"),
            "yellow": (4, 6, "Engaged but not selling"),
            "green": (7, 10, "Actively selling internally"),
        },
        "next_steps": {
            "red": "Ask: 'Who internally would benefit most from this?' Identify potential champion.",
            "yellow": "Confirm: 'Would you be comfortable presenting this to [stakeholder]?' Test willingness.",
            "green": "Enable: 'What do you need from us to sell this internally?' Provide champion enablement.",
        }
    },
    "competition": {
        "bands": {
            "red": (0, 3, "Competitive landscape unknown"),
            "yellow": (4, 6, "Competitors identified"),
            "green": (7, 10, "Our position vs. competitors clear"),
        },
        "next_steps": {
            "red": "Ask: 'Are you evaluating any other solutions?' Surface competitors.",
            "yellow": "Confirm: 'How are you thinking about us vs. [competitor]?' Understand positioning.",
            "green": "Reinforce: 'Based on [criteria], here's why we're best fit.' Maintain differentiation.",
        }
    },
}


def get_band(component: str, score: int) -> str:
    """
    Return the band name (red/yellow/green) for a component score.

    Args:
        component: MEDDICC component name (metrics, economic_buyer, etc.)
        score: Numeric score 0-10

    Returns:
        Band name string ("red", "yellow", or "green")
    """
    component_key = _norm(component)
    if component_key not in RUBRIC:
        return "unknown"

    bands = RUBRIC[component_key]["bands"]
    for band_name, (min_score, max_score, _) in bands.items():
        if min_score <= score <= max_score:
            return band_name

    return "unknown"


def get_next_steps(component: str, score: int) -> str:
    """
    Return coaching next steps for a component score.

    Args:
        component: MEDDICC component name
        score: Numeric score 0-10

    Returns:
        Next steps guidance string
    """
    component_key = _norm(component)
    if component_key not in RUBRIC:
        return "No guidance available for this component."

    band = get_band(component, score)
    if band == "unknown":
        return "Score out of range."

    return RUBRIC[component_key]["next_steps"].get(
        band, "No next steps defined for this band."
    )


# ── Bands as the surfaced signal ────────────────────────────────────────────
# Characterization finding (FIX_MEDDICC_SCORING_PIPELINE follow-up): given the
# full call set, the generator reproduces a component's BAND run-to-run but not
# its exact 0-10 integer — 6 of 7 components moved by ±1 across runs at
# temperature 0, and every move sat on a band line. The 0-10 integer is finer
# precision than the instrument can reproduce, so it is kept INTERNAL (for the
# hygiene comparison and trending) and the BAND is what we surface to a rep.
# "Champion: yellow" is honest at the precision we have; "Champion: 5/10" claims
# a resolution the generator can't reproduce.

_BAND_ORDER = {"red": 0, "yellow": 1, "green": 2}

# The rest of the system keys the pain component as "pain" (pain_score column,
# handler dicts, hygiene gates); RUBRIC keys it "identify_pain". Normalise so a
# band lookup for "pain" doesn't silently fall through to "unknown" (which made
# band_meets("pain", …) accidentally always-true).
_ALIASES = {"pain": "identify_pain", "identified_pain": "identify_pain"}


def _norm(component: str) -> str:
    key = str(component).lower().replace(" ", "_")
    return _ALIASES.get(key, key)


def _coerce_score(score) -> int:
    """A missing/garbage score is red-equivalent for gate comparison (an
    un-evidenced component does not clear a yellow/green bar)."""
    try:
        return int(score)
    except (TypeError, ValueError):
        return 0


def _bands_for(component: str):
    """[(band_name, lo, hi)] for a component, ascending by lo."""
    key = _norm(component)
    bands = RUBRIC.get(key, {}).get("bands", {})
    return sorted(((n, lo, hi) for n, (lo, hi, _d) in bands.items()),
                  key=lambda x: x[1])


def band_rank(component: str, score) -> int:
    """Ordinal of the score's band (red<yellow<green), or -1 if unknown."""
    return _BAND_ORDER.get(get_band(component, _coerce_score(score)), -1)


def band_meets(component: str, score, threshold) -> bool:
    """True if the score's band is at least the threshold's band.

    Gate comparison at the precision we can actually reproduce: an integer gate
    of 6 vs a score of 5 is a distinction the generator can't hold run-to-run
    (both yellow), so compare BANDS, not integers. A gate of 4 becomes
    "yellow-or-better", a gate of 7 "green-or-better". This keeps the
    comparison as stable as the underlying measurement — only a score genuinely
    on a band boundary can flip it, and that flip is surfaced (borderline), not
    hidden."""
    return band_rank(component, _coerce_score(score)) >= \
        band_rank(component, _coerce_score(threshold))


def band_label(component: str, score) -> dict:
    """Surface-ready band for a component score.

    Returns {band, borderline, near, score, text}. A score adjacent to a band
    boundary (e.g. 6 at the top of yellow, 7 at the bottom of green) is flagged
    borderline with the neighbouring band named — turning the run-to-run flip
    into information ("yellow, near the green boundary") instead of a hidden
    coin-flip. A None/blank score is UNREAD (we don't have the data), which is
    different from weak."""
    if score is None or (isinstance(score, str) and not score.strip()):
        return {"band": "unread", "borderline": False, "near": None,
                "score": None, "text": "unread (no score)"}
    s = _coerce_score(score)
    band = get_band(component, s)
    bands = _bands_for(component)
    borderline, near = False, None
    idx = next((i for i, (n, _lo, _hi) in enumerate(bands) if n == band), None)
    if idx is not None:
        _n, lo, hi = bands[idx]
        if s == hi and idx + 1 < len(bands):
            borderline, near = True, bands[idx + 1][0]
        elif s == lo and idx - 1 >= 0:
            borderline, near = True, bands[idx - 1][0]
    text = f"{band}, near the {near} boundary" if borderline else band
    return {"band": band, "borderline": borderline, "near": near,
            "score": s, "text": text}


def meddicc_bands(scores: dict) -> dict:
    """{component: score} → {component_key: band_label(...)}. Unknown
    components are dropped; None scores surface as unread."""
    out = {}
    for comp, sc in (scores or {}).items():
        # Preserve the caller's key (the rest of the system uses "pain", not
        # "identify_pain"); only normalise for the RUBRIC membership check.
        key = str(comp).lower().replace(" ", "_")
        if _norm(key) in RUBRIC:
            out[key] = band_label(key, sc)
    return out


def get_band_description(component: str, score: int) -> str:
    """
    Return the band description for a component score.

    Args:
        component: MEDDICC component name
        score: Numeric score 0-10

    Returns:
        Band description string
    """
    component_key = _norm(component)
    if component_key not in RUBRIC:
        return "Unknown component"

    bands = RUBRIC[component_key]["bands"]
    for band_name, (min_score, max_score, description) in bands.items():
        if min_score <= score <= max_score:
            return description

    return "Score out of range"
