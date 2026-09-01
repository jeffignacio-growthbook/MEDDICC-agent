# Add User to Personas

**User:** U07B3Q0TRGR (Jeff Ignacio from different Slack workspace)

Every request since yesterday has been un-personalized because this Slack ID isn't in `user_personas`.

---

## Add to Supabase

Connect to your Supabase project and run:

```sql
INSERT INTO user_personas (
    slack_user_id,
    name,
    email,
    role,
    title,
    role_group
) VALUES (
    'U07B3Q0TRGR',
    'Jeff Ignacio',
    'jeff@example.com',  -- Replace with actual email
    'RevOps',            -- Or actual role
    'CRO',               -- Or actual title
    'executive'          -- One of: executive, sales_leadership, operations, ic, other
);
```

**role_group options:**
- `executive` — C-level, strategic view
- `sales_leadership` — VP/Director of Sales, metric-driven
- `operations` — RevOps/Ops, process/data focus
- `ic` — Individual contributor (AE/AM), deal-level detail
- `other` — Default, balanced voice

---

## Or Via Slack DM

If DM intake is set up (`/slack/dm-intake` endpoint), send a DM to the bot:

```
My name is Jeff Ignacio
My role is CRO
My email is jeff@example.com
```

This will auto-register and bind the Slack ID.

---

## Verify

After adding, re-run a test question and check log:

```
[PERSONA] Jeff Ignacio (CRO) — jeff@example.com
```

Should no longer see "Unknown user U07B3Q0TRGR".

---

## Why This Matters

Persona determines voice adaptation:
- **Executive:** Strategic framing, year-over-year context
- **Sales Leadership:** Metric-driven, team performance focus
- **Operations:** Process-oriented, data quality emphasis
- **IC:** Deal-level detail, tactical next steps

Without persona, every answer is un-personalized (default voice block).
