# Deal Risk Assessor — 3 Decisions Needed Before Build

We're building a new primitive (`assess_deal_risk()`) that gives a real,
structured risk read on any deal or set of deals — combining MEDDICC
scores, stage-vs-qualification gaps, time-in-stage, and deal value.
The design is scoped; three business calls are needed before code, so
the thresholds are calibrated decisions, not engineering guesses.

Each question below has a concrete default — reply "yes" to all three,
or adjust whichever number doesn't feel right. No response needed
beyond that.

---

## 1. How stale is too stale for a MEDDICC score?

**The decision:** how many days since a deal's last MEDDICC analysis
before we stop treating that score as current, and instead flag it as
"unknown / needs a fresh look" rather than showing it as if it's
today's truth.

**Why it matters:** analyses only run when a deal gets a new call since
its last score — so a 6-week-old score doesn't necessarily mean
something broke, it can just mean the deal's gone quiet. Either way,
showing a stale score with the same confidence as a fresh one risks a
false "this deal looks healthy" read on a deal nobody's actually
touched recently. Too aggressive a cutoff, on the other hand, marks
half the active pipeline "unknown" and the tool stops being useful.

**Suggested default: 14 days.** A deal with no new call (and therefore
no re-score) in two weeks is itself worth surfacing — whether that's
because the deal is quiet by design (waiting on the buyer) or because
it's been neglected, the assessment should say "score is 21 days old,
treat with caution" rather than presenting it as fresh either way.

**Confirm 14 days, or tell me the number you'd rather use.**

---

## 2. What counts as "too long" in a given stage?

**The decision:** the benchmark that turns "38 days in Technical
Evaluation" into an actual risk signal ("stalled") instead of just a
number with no judgment attached.

**Why it matters:** this is exactly the kind of threshold that should
be calibrated from real historical outcomes, not picked by feel — the
same principle already applied earlier tonight (e.g. deriving the
New Business/Expansion split from actual `renewal_revenue` data rather
than guessing a definition).

**Suggested default, using data that already exists:** `deals_snapshot`
has enough weekly history to compute, per stage, how long deals that
*successfully* advanced (or won) actually spent there before moving on.
Flag a deal as "stalled" once it exceeds the **75th percentile of
historical time-in-stage among deals that went on to advance from that
same stage** — recomputed periodically as more snapshot history
accumulates, the same "revisit once real data exists" treatment
already used for this system's provisional stage-probability numbers.
This gives every stage its own real, evidence-based bar instead of one
guessed number applied everywhere.

**Confirm this percentile-of-historical-advancers approach (and the
75th-percentile cut), or tell me what you'd rather calibrate against.**

---

## 3. How much should a deal's size raise the bar?

**The decision:** above what deal value should we hold a deal to a
*stricter* MEDDICC qualification bar — and how much stricter.

**Why it matters:** the whole point of using value as a risk *factor*
(not just a sort key) is that a $500K deal deserves more scrutiny at
the same qualification level than a $50K one — the cost of being wrong
is bigger. Skip this and either the "value as risk weighting"
requirement goes unmet, or a number gets picked without your input on
exactly the highest-stakes deals in the pipeline.

**Suggested default:** rather than a fixed dollar figure that goes
stale as ACVs shift, scale it to the current pipeline: deals in the
**top quartile of currently-open deal value** get held to one band
higher than their stage would otherwise require (e.g. a component that
would normally just need to be "Yellow" to advance now needs "Green").
Recomputed periodically against the live pipeline, not hardcoded.

*(Simpler alternative, if you'd rather have a fixed rule: "2x the
average open deal size" as the cutoff, same one-band-stricter effect.)*

**Confirm the top-quartile approach, the simpler 2x-average version, or
give me your own cutoff.**

---

Once these three are confirmed, `deal_risk_assessor.py` gets built
against real, agreed-upon thresholds rather than provisional
placeholders that would need revisiting later.
