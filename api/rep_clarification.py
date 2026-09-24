"""
Settle every person named in a question in code, before anything runs.

2026-09-24 (clarifying-question audit): three things went wrong with names.
  - A first name two people share ("Jake": Jake H, 54 active deals, and
    Jake Stangl, 5) was left to the model. The dynamic loop was handed a
    prompt directive asking it to say "did you mean...?"
    (dimension_resolver.format_ambiguous_dimension_note); the classifier,
    meanwhile, had already picked one Jake's email from the roster.
  - handlers._resolve_owner_email took the first unordered substring match
    across all 54 personas, external contacts included: "Scott" could be
    Scott Bailey (no deals), "an" matched Dan.
  - A name that matched nobody ("Mike") got model-written suggestions that
    differed between two runs of the same question.

rep_gate() decides all three in code, on the question text:
  1. Mentions. A full name in the question ("Jake Stangl", "Jake H")
     settles its first name: that "Jake" is not a first-name mention. A
     token is a first-name mention only when someone in the handler's
     population has that first name (so "August" the month is not August
     Allard). The classifier's rep_name, the name exactly as written, adds
     a mention for a name nobody has ("Mike"), provided the question
     actually contains it.
  2. Population. SDR handlers consider SDRs (user_personas.role 'sdr' or an
     sdr_users row); every other handler considers people who own at least
     one deal.
  3. Count of candidates left: 0 -> decline, with a code-written list;
     1 -> answer, with a disclosure line when the cut removed someone
     ("Scott" -> Scott Keller, not Scott Bailey); 2-4 -> ask; >4 -> decline
     with the list. A full name that matches one person is settled.
An ask computes nothing. It returns a pending clarification that
db.save_thread stores in the thread history (role PENDING_ROLE, never sent
to the model). The next message in the thread is matched against it in code
(match_reply): "1", "Jake H", "stangl" or an email picks a candidate and the
original question reruns with the full name in place (apply_choice); any
other message is a new question and the pending ask lapses.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PENDING_ROLE = "pending_clarification"
PENDING_TTL = timedelta(hours=24)          # the thread itself expires after 24h (db.save_thread)
ASK_MAX = 4

SDR_HANDLERS = {"query_sdr_metrics", "query_sdr_leaderboard", "query_sdr_pipeline_sourced"}

_ROLE_LABELS = {"ae": "AE", "sdr": "SDR", "am": "AM", "ceo": "CEO", "cto": "CTO", "cro": "CRO",
                "vp_revops": "VP RevOps", "revops": "RevOps"}
_COUNT_WORDS = {2: "Two", 3: "Three", 4: "Four"}
_TOKEN = re.compile(r"[^\W\d_][\w'’\-]*")


def _norm(tok: str) -> str:
    t = tok.strip().lower().replace("’", "'")
    t = re.sub(r"'s$", "", t)
    return t.rstrip("'-")


def _tokens(text: str):
    """[(normalized, start, end, possessive)] for each word in text."""
    out = []
    for m in _TOKEN.finditer(text or ""):
        raw = m.group(0)
        n = _norm(raw)
        if n:
            out.append((n, m.start(), m.end(), raw.lower().replace("’", "'").endswith("'s")))
    return out


def _name_tokens(name: str) -> List[str]:
    return [t[0] for t in _tokens(name)]


# ── who exists ──────────────────────────────────────────────────────────────

def load_people(sb, select_all=None) -> List[Dict[str, Any]]:
    """Everyone in user_personas with a name, each with their deal counts and
    whether they're an SDR. One entry per email. `select_all` lets a caller
    pass its own (handlers passes the one tests patch)."""
    if select_all is None:
        try:
            from supabase_client import select_all
        except ImportError:
            from scripts.supabase_client import select_all
    personas = select_all(sb, "user_personas", columns="name,display_name,email,role")
    try:
        deals = select_all(sb, "deals", columns="owner_email,deal_status")
    except Exception as e:
        logger.warning(f"[REP_GATE] deal counts unavailable ({e}); not cutting by deal ownership")
        deals = []
    try:
        sdr_emails = {(r.get("user_email") or "").lower()
                      for r in select_all(sb, "sdr_users", columns="user_email")}
    except Exception:
        sdr_emails = set()
    counts: Dict[str, List[int]] = {}
    for d in deals:
        e = (d.get("owner_email") or "").lower()
        if e:
            c = counts.setdefault(e, [0, 0])
            c[0] += 1
            c[1] += d.get("deal_status") == "active"
    people, seen = [], set()
    known = bool(counts)
    for p in personas:
        email = (p.get("email") or "").strip().lower()
        name = (p.get("name") or p.get("display_name") or "").strip()
        if not email or not name or email in seen:
            continue
        seen.add(email)
        n, a = counts.get(email, [0, 0])
        people.append({"name": name, "email": email, "role": p.get("role") or "",
                       "deals": n, "active": a, "deal_counts_known": known,
                       "is_sdr": (p.get("role") or "").lower() == "sdr" or email in sdr_emails})
    return people


def might_name_someone(question: str, names: List[str], extracted_name: Optional[str]) -> bool:
    """Cheap pre-check (no deals read): could any word of the question be
    one of these people's first names, or did the classifier extract a
    name? When not, rep_gate() would proceed anyway."""
    if (extracted_name or "").strip():
        return True
    firsts = {nt[0] for nt in (_name_tokens(n or "") for n in names) if nt}
    return any(t[0] in firsts for t in _tokens(question))


def population_for(handler: str) -> str:
    return "sdr" if handler in SDR_HANDLERS else "deal_owner"


def _in_population(person: dict, population: str) -> bool:
    if population == "sdr":
        return person["is_sdr"]
    # no deal counts at all (the deals read failed): nobody is cut, rather
    # than everybody
    return person["deals"] > 0 or not person.get("deal_counts_known", True)


# ── what the question names ─────────────────────────────────────────────────

def _find_mentions(question: str, people: List[dict], population: str,
                   extracted_name: Optional[str]) -> List[dict]:
    toks = _tokens(question)
    norms = [t[0] for t in toks]
    covered = set()
    mentions = []

    # full names first (two or more words), longest first
    by_full: Dict[tuple, List[dict]] = {}
    for p in people:
        nt = tuple(_name_tokens(p["name"]))
        if len(nt) >= 2:
            by_full.setdefault(nt, []).append(p)
    for nt in sorted(by_full, key=len, reverse=True):
        k = len(nt)
        for i in range(len(norms) - k + 1):
            if tuple(norms[i:i + k]) == nt and not covered & set(range(i, i + k)):
                covered |= set(range(i, i + k))
                mentions.append({"kind": "full", "term": question[toks[i][1]:toks[i + k - 1][2]],
                                 "start": toks[i][1], "end": toks[i + k - 1][2],
                                 "possessive": toks[i + k - 1][3], "candidates": by_full[nt]})

    by_first: Dict[str, List[dict]] = {}
    for p in people:
        nt = _name_tokens(p["name"])
        if nt:
            by_first.setdefault(nt[0], []).append(p)

    ext = _tokens(extracted_name or "")
    ext_norms = [t[0] for t in ext]
    ext_at = None
    if ext_norms:
        k = len(ext_norms)
        for i in range(len(norms) - k + 1):
            if norms[i:i + k] == ext_norms:
                ext_at = i
                break

    for i, (n, s, e, poss) in enumerate(toks):
        if i in covered:
            continue
        cands = by_first.get(n, [])
        is_ext = ext_at == i and len(ext_norms) == 1
        if not is_ext and not any(_in_population(p, population) for p in cands):
            continue
        covered.add(i)
        mentions.append({"kind": "first", "term": question[s:e], "start": s, "end": e,
                         "possessive": poss, "candidates": cands})

    # the classifier's name-as-written, when it is more than one word and no
    # full name matched it ("Sarah Johnson")
    if ext_at is not None and len(ext_norms) > 1 and not covered & set(range(ext_at, ext_at + len(ext_norms))):
        j = ext_at + len(ext_norms) - 1
        mentions.append({"kind": "full", "term": question[toks[ext_at][1]:toks[j][2]],
                         "start": toks[ext_at][1], "end": toks[j][2], "possessive": toks[j][3],
                         "candidates": by_full.get(tuple(ext_norms), [])})
    return sorted(mentions, key=lambda m: m["start"])


# ── wording (all code-written) ──────────────────────────────────────────────

def _bare(term: str) -> str:
    t = re.sub(r"['’]s$", "", term.strip())
    return t[:1].upper() + t[1:]


def _describe(p: dict, show_email: bool) -> str:
    bits = [b for b in (_ROLE_LABELS.get(p["role"].lower()),) if b]
    bits.append(f"{p['active']} active deal{'s' if p['active'] != 1 else ''}")
    if show_email:
        bits.append(p["email"])
    return f"{p['name']} ({', '.join(bits)})"


def _pop_names(people: List[dict], population: str) -> List[str]:
    return sorted({p["name"] for p in people if _in_population(p, population)}, key=str.lower)


def _join(names: List[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _decline_none(m: dict, people: List[dict], population: str) -> str:
    term = _bare(m["term"])
    outside = sorted({p["name"] for p in m["candidates"]}, key=str.lower)
    if population == "sdr":
        head = f"I don't see an SDR named {term}, so I haven't guessed. SDRs: "
        why = " aren't SDRs" if len(outside) > 1 else " isn't an SDR"
    else:
        head = f"I don't see anyone named {term} who owns deals, so I haven't guessed. People who own deals: "
        why = " own no deals" if len(outside) > 1 else " owns no deals"
    msg = head + ", ".join(_pop_names(people, population)) + "."
    if outside:
        msg += f" ({_join(outside)} {'are' if len(outside) > 1 else 'is'} in the directory but{why}.)"
    return msg + " Ask again with one of those names."


def _pop_phrase(population: str) -> str:
    return "are SDRs" if population == "sdr" else "own deals"


# ── the gate ────────────────────────────────────────────────────────────────

def rep_gate(question: str, handler: str, people: List[dict],
             extracted_name: Optional[str] = None) -> Dict[str, Any]:
    """Decide, in code, what to do about the people this question names.

    Returns {"action": "proceed" | "disclose" | "ask" | "decline",
             "question": the question to run (full names in place of any
                         disclosed first name),
             "pin": params to set, e.g. {"owner_email": ...}, when the
                    question names exactly one person,
             "disclosure": line to prefix to the answer (disclose),
             "message": the whole reply (ask / decline),
             "pending": what to save in the thread (ask)}."""
    population = population_for(handler)
    mentions = _find_mentions(question, people, population, extracted_name)
    decisions = []
    for m in mentions:
        # most active first, so the likelier reading is option 1
        left = sorted((p for p in m["candidates"] if _in_population(p, population)),
                      key=lambda p: (-p["active"], -p["deals"], p["name"].lower(), p["email"]))
        cut = {p["name"] for p in m["candidates"]} - {p["name"] for p in left}
        if not left:
            decisions.append(("decline", m, left))
        elif len(left) == 1:
            decisions.append(("disclose" if cut and m["kind"] == "first" else "settled", m, left))
        elif len(left) <= ASK_MAX:
            decisions.append(("ask", m, left))
        else:
            decisions.append(("decline_many", m, left))

    out = {"action": "proceed", "question": question, "pin": {}, "population": population,
           "mentions": [{"term": m["term"], "decision": d, "emails": [p["email"] for p in left]}
                        for d, m, left in decisions]}

    for d, m, left in decisions:
        if d == "decline":
            out.update(action="decline", message=_decline_none(m, people, population))
            return out
        if d == "decline_many":
            names = [p["name"] for p in left]
            out.update(action="decline", message=(
                f"“{_bare(m['term'])}” matches {len(left)} people who {_pop_phrase(population)}: "
                f"{', '.join(names)}. Ask again with a full name."))
            return out

    for d, m, left in decisions:
        if d == "ask":
            same_name = len({p["name"] for p in left}) < len(left)
            opts = "\n".join(f"{i}) {_describe(p, same_name)}" for i, p in enumerate(left, 1))
            nums = " or ".join([", ".join(str(i) for i in range(1, len(left))), str(len(left))])
            now = datetime.now(timezone.utc)
            out.update(action="ask", message=(
                f"{_COUNT_WORDS[len(left)]} people named {_bare(m['term'])} {_pop_phrase(population)} "
                f"— reply {nums}:\n{opts}\n\n"
                "I haven't run anything yet; I'll answer as soon as you pick."),
                pending={"question": question, "term": _bare(m["term"]),
                         "start": m["start"], "end": m["end"], "possessive": m["possessive"],
                         "candidates": [{"name": p["name"], "email": p["email"]} for p in left],
                         "handler": handler, "created_at": now.isoformat(),
                         "expires_at": (now + PENDING_TTL).isoformat()})
            return out

    # proceed / disclose: put full names in place of disclosed first names
    q = question
    lines = []
    for d, m, left in sorted(decisions, key=lambda x: -x[1]["start"]):
        if d == "disclose":
            p = left[0]
            q = q[:m["start"]] + p["name"] + ("'s" if m["possessive"] else "") + q[m["end"]:]
            who = (f"the only SDR named {_bare(m['term'])}" if population == "sdr"
                   else f"the only person named {_bare(m['term'])} who owns deals")
            lines.insert(0, f"_Taking “{_bare(m['term'])}” to mean {p['name']}, {who}._")
    people_named = {left[0]["email"] for d, m, left in decisions if d in ("settled", "disclose")}
    if len(people_named) == 1:
        email = people_named.pop()
        out["pin"] = ({"sdr_email": email} if population == "sdr"
                      else {"owner_email": email, "rep_email": email})
    out["question"] = q
    if lines:
        out.update(action="disclose", disclosure="\n".join(lines))
    return out


# ── the pending clarification ───────────────────────────────────────────────

def find_pending(history: list, now: Optional[datetime] = None) -> Optional[dict]:
    """The pending clarification saved by the last turn, if the user hasn't
    asked anything since and it hasn't expired."""
    now = now or datetime.now(timezone.utc)
    for msg in reversed(history or []):
        role = msg.get("role") if isinstance(msg, dict) else None
        if role == "user":
            return None
        if role == PENDING_ROLE:
            try:
                p = msg["content"]
                p = json.loads(p) if isinstance(p, str) else p
                if datetime.fromisoformat(p["expires_at"]) < now:
                    return None
                return p
            except Exception:
                return None
    return None


def match_reply(text: str, pending: dict) -> Optional[dict]:
    """The candidate a reply picks, or None (a new question)."""
    cands = pending.get("candidates") or []
    t = (text or "").strip().lower().rstrip(".!)")
    m = re.fullmatch(r"(?:#|no\.?\s*|number\s*|option\s*)?(\d+)", t)
    if m:
        i = int(m.group(1))
        return cands[i - 1] if 1 <= i <= len(cands) else None
    for c in cands:
        if t == c["email"].lower():
            return c
    rn = _name_tokens(text)
    for c in cands:
        if rn and rn == _name_tokens(c["name"]):
            return c
    if len(rn) == 1 and len(rn[0]) >= 2:
        hits = [c for c in cands if rn[0] in _name_tokens(c["name"])]
        if len(hits) == 1:
            return hits[0]
    return None


def apply_choice(pending: dict, choice: dict) -> str:
    q = pending["question"]
    return (q[:pending["start"]] + choice["name"] + ("'s" if pending.get("possessive") else "")
            + q[pending["end"]:])


def owner_email_for_name(name: str, people: List[dict]) -> Dict[str, Any]:
    """handlers._resolve_owner_email's lookup: exact full or first name
    only, cut to people who own deals. {"email"} when exactly one is left,
    else {"email": None, "candidates": [names]} — never a guess."""
    nt = _name_tokens(name)
    if not nt:
        return {"email": None, "candidates": []}
    full = [p for p in people if _name_tokens(p["name"]) == nt]
    cands = full or ([p for p in people if _name_tokens(p["name"])[:1] == nt] if len(nt) == 1 else [])
    left = ([p for p in cands if _in_population(p, "deal_owner")]
            or (full if len(full) == 1 else []))
    if len(left) == 1:
        return {"email": left[0]["email"], "candidates": [left[0]["name"]]}
    return {"email": None, "candidates": sorted(p["name"] for p in (left or cands))}
