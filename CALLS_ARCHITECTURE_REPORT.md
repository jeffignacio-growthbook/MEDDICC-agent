# CALLS DATA ARCHITECTURE — GROUND TRUTH REPORT

## EXECUTIVE SUMMARY

**Data Flow**: File cache (memory/calls/*.json) → Supabase calls table
- **Source of Truth**: File cache (memory/calls/*.json) - 985 files, 2,084 call records
- **Enrichment Metadata Store**: Supabase calls table - 35 rows
- **Enrichment Scripts**: Read from file cache, write enrichment status to Supabase

---

## 1. SUPABASE CALLS TABLE

### Table Structure
```
Table: calls
Rows: 35
```

### Columns (15 total)
- call_date
- call_id (primary key)
- company_name
- company_slug
- competitors_mentioned
- created_at
- duration_minutes
- feature_gaps_scanned_at
- formatted_summary
- has_feature_gap
- has_objection
- objections_scanned_at
- source
- title
- updated_at

### Key Observations
✗ NO deal_id column
✗ NO participants column (neither count nor email roster)
✓ Has enrichment tracking fields:
  - objections_scanned_at
  - feature_gaps_scanned_at
  - has_objection (34.3% of rows)
  - has_feature_gap (8.6% of rows)

### Linkage Statistics
- Total rows: 35
- With company_name: 35/35 (100%)
- With company_slug: 35/35 (100%)
- Distinct companies: 33
- Enrichment coverage: 14.3% scanned for objections/gaps

### Sample Data
company_name                             | company_slug
---------------------------------------- | -------------------------
Demo Call with                           | demo-call-with
Customer Success Overview                | customer-success-overview
Growthbook Contracts Discussion          | growthbook-contracts-discussion
Google Ads                               | google-ads
KBYG                                     | kbyg

---

## 2. FILE CACHE (memory/calls/*.json)

### Structure
```
Total files: 985
Files with calls: 984
Total call records: 2,084
```

### File Format
Each JSON file contains:
```json
{
  "company": "Company Name + GrowthBook",
  "slug": "company-name-growthbook",
  "last_etl_date": "2026-08-08T17:33:40.689991",
  "calls": [
    {
      "id": "01KYQK1Q6JJAHNJKY44HJMKP8F",
      "source": "fireflies",
      "title": "Meeting Title",
      "date": "2026-07-31",
      "duration_minutes": 33.63,
      "summary": "...",
      "organizer": "email@growthbook.io",
      "participants": 2,                    // INTEGER COUNT ONLY
      "keywords": "...",
      "action_items": "...",
      "participant_domains": ["domain.com"] // OPTIONAL
    }
  ]
}
```

### Key Observations
✗ NO deal_id field in cache records
✗ NO participant email addresses
✓ participants = integer count (not a roster)
✓ participant_domains = list of domains (optional, often null)
~ Some files have additional fields, but structure is inconsistent

### Sample Analysis (first 100 files, 169 calls)
- Calls with 'participants' field: 169/169 (100%)
- Calls with 'deal_id' field: 0/169 (0%)
- Calls with participant emails: 0/169 (0%)
- Participant field type: integer (100%)

---

## 3. ETL DATA FLOW

### Read Source: FILE CACHE
```python
# scripts/enrichment/extract_objections.py (line 145, 164)
data = json.load(open(cache_file))
for call in data.get('calls', []):
    # Process call
```

### Write Destination: SUPABASE
```python
# scripts/supabase_client.py (line 189-205)
self.client.table('calls').upsert({
    'call_id': str(call['id']),
    'company_slug': call.get('company_slug', ''),
    'company_name': company_name,
    'source': call.get('source', ''),
    'call_date': _safe_date(call.get('date')),
    'duration_minutes': _safe_numeric(call.get('duration_minutes')),
    'title': call.get('title', ''),
    'formatted_summary': summary,
    'competitors_mentioned': call.get('competitors_mentioned'),
    'has_feature_gap': _has_keyword(summary, FEATURE_GAP_KEYWORDS),
    'has_objection': _has_keyword(summary, OBJECTION_KEYWORDS),
    'updated_at': datetime.now().isoformat(),
}, on_conflict='call_id').execute()
```

### Key Scripts
**scripts/enrichment/extract_objections.py**
- Reads: memory/calls/*.json (cache files)
- Matches: cache slug → deal records via slugify()
- Resolves deal_id: using slug + call_date
- Sets participants: [] (empty list, because cache only has count)

**scripts/enrichment/extract_feature_gaps.py**
- Same pattern as extract_objections.py

**scripts/enrichment/extract_sales_signals.py** (Phase E.2)
- Same pattern, but runs on INTENT_SALES_REVIEW calls

**scripts/enrichment/call_intent_classifier.py** (Phase E.2)
- Docstring explicitly states:
  > "memory/calls/*.json stores `participants` as an integer
  > count, never a list of {email: ...} dicts"

---

## 4. ANSWERS TO SPECIFIC QUESTIONS

**Q: How many rows in Supabase calls table?**
A: 35 rows

**Q: How many call records in the file cache?**
A: 2,084 call records across 985 files (984 with calls, 1 empty)

**Q: Does the Supabase calls table have deal_id and participant emails?**
A: NO. The calls table has:
   - NO deal_id column
   - NO participants column at all

**Q: Do the file cache records have deal_id and participant emails?**
A: NO. Cache records have:
   - NO deal_id field
   - participants = integer count only (no email roster)
   - Optional participant_domains array (often null)

**Q: Which source does extract_objections.py actually read from?**
A: File cache (memory/calls/*.json)
   - Reads call data from cache files
   - Matches to deals by company slug
   - Resolves deal_id using slug + call_date
   - Writes enrichment results to Supabase (objections, feature_gaps tables)
   - Updates Supabase calls table with scan timestamps

---

## 5. DISCREPANCY ANALYSIS

### Why 35 rows in Supabase vs 2,084 in cache?

The Supabase calls table is NOT a mirror of the file cache. It serves as:
1. **Enrichment metadata store** - tracks which calls have been scanned
2. **Keyword detection cache** - pre-flags calls with objection/gap keywords
3. **Partial index** - only calls that have been processed or flagged

**Evidence:**
- Only 14.3% (5/35) of Supabase rows have objections_scanned_at
- The 35 rows are likely calls that were:
  - Recently written by supabase_client.py upsert_call()
  - Flagged with has_objection/has_feature_gap keywords
  - Manually inserted for testing/monitoring

The file cache is the source of truth for all call data.

---

## 6. CRITICAL DESIGN NOTES

### deal_id Resolution
- **File cache**: NO deal_id stored
- **Enrichment ETL**: Resolves deal_id dynamically:
  ```python
  # extract_objections.py line 201
  'deal_id': resolve_deal_id(normalized_slug, call_date)
  ```
- **Resolution logic**: Match company_slug + temporal proximity to deal
- **Implication**: Same call can resolve to different deal_ids over time

### Participant Data
- **File cache**: Integer count + optional domains array
- **call_intent_classifier.py**: Explicitly handles missing email data
  ```python
  # Line 199: "Cache stores a participant count, not a roster"
  'participants': [],  # Empty list so classifier treats as unknown
  ```
- **Implication**: Intent classification relies on keywords/summary, not emails

### Enrichment Flow
```
memory/calls/*.json (source)
    ↓
extract_objections.py / extract_feature_gaps.py
    ↓ (reads cache, matches to deals)
    ↓
Supabase objections/feature_gaps tables (enrichment results)
    +
Supabase calls table (enrichment metadata: scanned_at timestamps)
```

---

## 7. PHASE E.2 IMPACT

Phase E.2 added call_intent_classifier.py which:
- Classifies calls as: prospect | sales_review | skip
- Routes to appropriate enrichment:
  - prospect → objections + feature_gaps
  - sales_review → deal_risks + competitive_signals + pipeline_signals
  - skip → no enrichment

**Key constraint from documentation:**
> "memory/calls/*.json stores participants as an integer count,
> never a list of {email: ...} dicts, and carries no tags key at all.
> The participant/tag rules are only exercised by callers that supply
> richer metadata."

This means intent classification must rely on:
- Call title keywords
- Summary content
- participant_domains (when present)
- NOT participant emails (not available)

