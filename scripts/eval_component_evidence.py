#!/usr/bin/env python3
"""
Eval: per-component evidence is fetched and cited, not fabricated.

query_rubric_scores_bulk returned scores+bands with no evidence, so synthesis
filled the gap with generic template language ("identify who has a personal
stake") — the same sentence for any deal. Two-part fix, both locked here:

  * the handler now selects analyses.component_details and exposes a clean
    per-component `evidence` map (string or null);
  * the synthesis guard makes evidence mandatory: cite a specific fact when
    evidence is present, or say "no supporting evidence on record for X" — never
    infer a plausible-sounding gap from the score alone.
"""
import sys
import types
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub_if_missing("supabase", create_client=lambda *a, **k: None,
                 Client=type("Client", (), {}))
_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}),
                 APIError=type("APIError", (Exception,), {}))

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


# Supabase stand-in: one deal, one analysis row carrying component_details.
class _Q:
    def __init__(self, table, data):
        self.table_name = table
        self.data = data
        self._ilike = None
        self._in = None

    def select(self, *a, **k):
        return self

    def ilike(self, col, pat):
        self._ilike = pat.strip("%").lower()
        return self

    def in_(self, col, vals):
        self._in = list(vals)
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        rows = self.data.get(self.table_name, [])
        if self._ilike is not None:
            rows = [r for r in rows
                    if self._ilike in (r.get("company_name") or "").lower()]
        if self._in is not None:
            rows = [r for r in rows if r.get("deal_id") in self._in]
        return types.SimpleNamespace(data=rows)

    def __getattr__(self, _n):
        return lambda *a, **k: self


class _SB:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Q(name, self.data)


def _handler_payload(component_details):
    import json
    from api import handlers
    # The handler reads bands from the score COLUMNS and evidence from
    # component_details — so a realistic row keeps them consistent. Derive each
    # *_score column from the component's score in component_details (default 5).
    _COLS = {"metrics": "metrics_score", "economic_buyer": "economic_buyer_score",
             "decision_criteria": "decision_criteria_score",
             "decision_process": "decision_process_score", "pain": "pain_score",
             "champion": "champion_score", "competition": "competition_score"}
    row = {
        "deal_id": "62620904729", "company_name": "Zalando - Outbound",
        "overall_score": 46, "analyzed_at": "2026-08-24T00:00:00Z",
        "component_details": json.dumps(component_details),
    }
    for c, col in _COLS.items():
        cell = component_details.get(c) if isinstance(component_details.get(c), dict) else None
        row[col] = (cell or {}).get("score", 5)
    data = {
        "deals": [{"deal_id": "62620904729", "company_name": "Zalando - Outbound"}],
        "analyses": [row],
    }
    res = asyncio.run(handlers.query_rubric_scores_bulk(
        {"company": "Zalando"}, _SB(data)))
    return res["scores"][0]


def test_handler_attaches_component_evidence():
    """The handler exposes per-component evidence from component_details."""
    s = _handler_payload({
        "champion": {"score": 3, "evidence": "Only contact is a junior PM; "
                     "no exec sponsor identified on the Aug 12 call."},
        "economic_buyer": {"score": 3, "evidence": ""},  # present-but-empty
        # decision_process omitted entirely -> null
    })
    check("scores carry an 'evidence' map", isinstance(s.get("evidence"), dict))
    check("champion evidence is the recorded fact (cited, not templated)",
          "junior PM" in (s["evidence"]["champion"] or ""))
    check("empty-string evidence normalizes to null",
          s["evidence"]["economic_buyer"] is None)
    check("omitted component -> null evidence",
          s["evidence"]["decision_process"] is None)
    check("raw component_details blob is dropped from the payload",
          "component_details" not in s)
    check("bands still present", isinstance(s.get("bands"), dict))


def test_component_writeup_cites_evidence_when_present():
    """A component with recorded evidence must reference a specific fact, not a
    generic template. The synthesis guard makes that mandatory and bans the
    stock phrasings."""
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "sales_leadership", "name": "Ryan"}).lower()
    check("guard makes evidence mandatory per component",
          "evidence is mandatory" in p)
    check("guard tells synthesis to use the evidence map",
          "`evidence`" in p or "evidence[component]" in p or "evidence map" in p)
    check("guard bans the generic 'personal stake' template",
          "personal stake" in p)
    check("guard forbids a sentence that fits any company",
          "read identically for a different company" in p
          or "fits any deal and names nothing" in p)


def test_component_writeup_admits_absence_when_evidence_missing():
    """A component with no evidence says so plainly, never infers a
    plausible-sounding gap from the score alone."""
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "operational", "name": "Ryan"}).lower()
    check("guard requires the plain no-evidence admission",
          "no supporting evidence on record" in p)
    check("guard forbids inferring the reason from the score",
          "not the reason" in p or "score alone" in p or "band, not the reason" in p)
    # the handler's null-evidence output is what triggers that admission
    s = _handler_payload({"champion": {"score": 3, "evidence": None}})
    check("null evidence reaches synthesis as null (drives the admission)",
          s["evidence"]["champion"] is None)


def test_unread_is_distinct_from_red():
    """A component at 0 with NO evidence is UNREAD (never discussed), not red.
    A component at 0 WITH evidence is a real red (discussed, found absent).
    The handler must separate them; the band must not read as red for unread."""
    s = _handler_payload({
        # champion 0 + no evidence  -> unread (never came up)
        "champion": {"score": 0, "evidence": None},
        # economic_buyer 0 WITH evidence -> real red (discussed, absent)
        "economic_buyer": {"score": 0,
                           "evidence": "Nils said there is no budget owner "
                                       "identified for this yet on the Aug 12 call."},
        # decision_criteria 5 with evidence -> assessed yellow
        "decision_criteria": {"score": 5, "evidence": "Warehouse-native required."},
    })
    check("never-discussed 0 → status unread", s["status"]["champion"] == "unread")
    check("never-discussed 0 → band is 'unread', not red",
          "unread" in s["bands"]["champion"] and "red" not in s["bands"]["champion"])
    check("champion in unread_components list", "champion" in s["unread_components"])
    check("0-WITH-evidence stays a real red (assessed)",
          s["status"]["economic_buyer"] == "assessed"
          and s["bands"]["economic_buyer"] == "red")
    check("EB NOT in unread_components", "economic_buyer" not in s["unread_components"])
    check("a scored component is assessed, not unread",
          s["status"]["decision_criteria"] == "assessed")


def test_guard_separates_unread_structurally():
    """The synthesis guard must give unread its own section + neutral marker and
    keep it out of 'weakest, sorted first' — not just reword it."""
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "sales_leadership", "name": "Ryan"}).lower()
    check("guard leads with worst KNOWN (assessed), not a 0",
          "worst known" in p and "status: assessed" in p)
    check("guard gives unread its own section",
          "not yet assessed" in p or "haven't come up yet" in p)
    check("guard mandates a neutral marker, not a colour circle",
          ":white_circle:" in p and "never a red/yellow/green circle" in p)
    check("guard says a 0 must not sort unread to the top",
          "sort the unread one to the top" in p or "sort them to the top" in p)


def run():
    print("=" * 72)
    print("COMPONENT EVIDENCE — fetched + cited, not fabricated")
    print("=" * 72)
    for title, fn in (
        ("handler attaches per-component evidence", test_handler_attaches_component_evidence),
        ("write-up cites evidence when present", test_component_writeup_cites_evidence_when_present),
        ("write-up admits absence when missing", test_component_writeup_admits_absence_when_evidence_missing),
        ("unread is distinct from red (handler)", test_unread_is_distinct_from_red),
        ("guard separates unread structurally", test_guard_separates_unread_structurally),
    ):
        print(f"\n[{title}]")
        fn()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("PASS — evidence is fetched, cited when present, admitted when absent.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
