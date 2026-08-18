# Known Issues

## Apollo Conversation Intelligence — Summary Extraction Failure

**Status:** Open
**Severity:** Medium — affects deals with Apollo-only recent calls
**Discovered:** 2026-08-18 during DeepSeek model comparison

### Symptom

Apollo calls are stored with `[Summary failed]` prefix followed by
raw speaker fragments instead of AI-generated summaries:

```
[Summary failed] [logan]: David.
[David Gregory]: Hey, Christian.
...
```

Fireflies calls for the same deals have full, rich summaries.

### Affected deals (examples)

- Skyscanner (55660576681): 5 Apollo calls corrupted, most recent
  call 2026-07-29 is Apollo-only with no Fireflies equivalent
- Stone (53500422798): 3 Apollo calls corrupted

### Impact

Context builder receives corrupted input for the most recent call
on Apollo-recorded deals. Evaluator correctly rejects the resulting
analysis. Deals with Apollo-only recent calls produce no MEDDICC
update until fixed.

### Root cause (suspected)

Apollo Conversation Intelligence summary API returns null or a
different field structure than expected by the ETL parser. A
try/except block catches the failure and writes raw speaker
fragments with the `[Summary failed]` prefix instead.

### Fix approach

1. Debug the Apollo API response for a failing call to confirm
   the actual field structure returned
2. Update `extract_apollo_summary()` in the Apollo adapter to
   handle null summary fields gracefully — fall back to transcript
   excerpt rather than raw fragments
3. Add Fireflies preference logic: when both Apollo and Fireflies
   have a call on the same date, prefer the Fireflies version
4. Re-ETL affected deals after fixing

### Workaround

Until fixed, the MEDDICC agent will produce lower-quality analyses
for deals where the most recent call is Apollo-only. Deals with
Fireflies coverage are unaffected.

### Files to investigate

- `scripts/adapters/calls/apollo.py` — summary extraction logic
- `scripts/etl_calls.py` — call merging and source priority
