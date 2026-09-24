"""
A strict in-memory Supabase fake: it answers a query the way PostgREST would.

Why: a fake that returns every field of every row, whatever was selected or
filtered, hides a whole class of bug. Twice on 2026-09-24 a handler was
correct against a generous fake and wrong against the database:
  - assess_forecast_trust selected `amount`, a column `deals` never had
    (every production call failed);
  - query_pipeline filtered on deal_status but never selected it, so the
    COMMIT close-date check saw 0 deals.
This fake:
  - returns only the columns a query selected (a real select projects);
  - applies every filter the query applied (eq/neq/gt/gte/lt/lte/like/
    ilike/is_/in_ and their not_ forms) with SQL NULL semantics (NULL
    matches nothing but IS NULL);
  - honours order, limit, range, single / maybe_single;
  - refuses a table or column that is not in the real schema
    (tests/fixtures/db_schema_columns.json), like Postgres would;
  - refuses a query shape it does not model (aliases, casts, embedded
    resources) instead of guessing, so a test can't pass on a misread.
Writes (insert/upsert/update/delete) are recorded in .writes, not applied;
a write naming a column the real table doesn't have raises (PGRST204).

Use with the REAL supabase_client.select_all, so its filter translation is
exercised too:
    sb = StrictSupabase({"deals": rows})
    handlers.select_all is left alone; call the handler with sb.
"""
import json
import re
from pathlib import Path

SCHEMA = json.loads((Path(__file__).parent / "fixtures" / "db_schema_columns.json").read_text())["tables"]


class StrictSupabaseError(AssertionError):
    pass


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _cmp_key(a, b):
    """Coerce a stored value and a filter value the way Postgres casts the
    filter literal to the column type: numbers compare as numbers, anything
    else as text (ISO dates and timestamps order correctly as text)."""
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na, nb
    return str(a), str(b)


def _sortable(v):
    if v is None:
        return (0, 0)
    n = _num(v)
    return (0, n) if n is not None else (1, str(v))


def _like(value, pattern, flags=0):
    rx = "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in str(pattern)) + "$"
    return re.match(rx, str(value), flags | re.S) is not None


def _pred(op, col, arg):
    def test(row):
        v = row.get(col)
        if op == "is":
            want = {"null": None, "true": True, "false": False}.get(str(arg).lower(), arg) \
                if isinstance(arg, str) or arg is None else arg
            return v is want if want in (None, True, False) else v == want
        if v is None:
            return False                                   # NULL = x is never true
        if op == "in":
            return any(_cmp_key(v, a)[0] == _cmp_key(v, a)[1] for a in arg if a is not None)
        if op == "like":
            return _like(v, arg)
        if op == "ilike":
            return _like(v, arg, re.I)
        if arg is None:
            return False
        x, y = _cmp_key(v, arg)
        return {"eq": x == y, "neq": x != y, "gt": x > y, "gte": x >= y,
                "lt": x < y, "lte": x <= y}[op]
    return test


class _Not:
    def __init__(self, q):
        self._q = q

    def __getattr__(self, name):
        op = {"is_": "is", "in_": "in"}.get(name, name)
        if op not in ("eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in"):
            raise StrictSupabaseError(f"not_.{name}() is not modelled by StrictSupabase")

        def f(col, arg):
            self._q._check_col(col)
            p = _pred(op, col, list(arg) if op == "in" else arg)
            # NOT (NULL = x) is still NULL: a NULL row never passes a negated
            # comparison, except NOT IS NULL, which is plainly true for non-null
            self._q._filters.append(
                (f"not.{op}", col, arg,
                 (lambda r: r.get(col) is not None and not p(r)) if op != "is" else (lambda r: not p(r))))
            return self._q
        return f


class _Query:
    def __init__(self, sb, table):
        self.sb, self.table, self._cols = sb, table, None
        self._filters, self._order, self._limit, self._range = [], [], None, None
        self._single, self._write = None, None

    # --- shape -------------------------------------------------------------
    def _check_col(self, col):
        if col not in SCHEMA[self.table]:
            raise StrictSupabaseError(
                f"column {self.table}.{col} does not exist (tests/fixtures/db_schema_columns.json)")

    def select(self, *columns, **kw):
        cols = []
        for c in ",".join(columns).split(","):
            c = c.strip()
            if not c:
                continue
            if c == "*":
                cols = None
                break
            if re.search(r"[:()!.\s>-]", c):
                raise StrictSupabaseError(f"StrictSupabase does not model the select item {c!r}")
            self._check_col(c)
            cols.append(c)
        self._cols = cols
        return self

    # --- filters -------------------------------------------------------------
    def _add(self, op, col, arg):
        self._check_col(col)
        self._filters.append((op, col, arg, _pred(op, col, arg)))
        return self

    def eq(self, c, v): return self._add("eq", c, v)
    def neq(self, c, v): return self._add("neq", c, v)
    def gt(self, c, v): return self._add("gt", c, v)
    def gte(self, c, v): return self._add("gte", c, v)
    def lt(self, c, v): return self._add("lt", c, v)
    def lte(self, c, v): return self._add("lte", c, v)
    def like(self, c, v): return self._add("like", c, v)
    def ilike(self, c, v): return self._add("ilike", c, v)
    def is_(self, c, v): return self._add("is", c, v)

    def in_(self, c, values):
        if isinstance(values, str):
            raise StrictSupabaseError(f"in_({c!r}, {values!r}): a bare string, not a list")
        return self._add("in", c, list(values))

    @property
    def not_(self):
        return _Not(self)

    # --- modifiers -------------------------------------------------------------
    def order(self, col, desc=False, **kw):
        self._check_col(col)
        self._order.append((col, desc))
        return self

    def limit(self, n, **kw):
        self._limit = n
        return self

    def range(self, a, b, **kw):
        self._range = (a, b)
        return self

    def single(self):
        self._single = "single"
        return self

    def maybe_single(self):
        self._single = "maybe"
        return self

    # --- writes (recorded, not applied) ----------------------------------------
    def _w(self, kind, payload=None, **kw):
        # PostgREST rejects a write naming a column the table doesn't have (PGRST204)
        for row in (payload if isinstance(payload, list) else [payload] if payload else []):
            for col in row:
                self._check_col(col)
        self._write = (kind, payload, kw)
        return self

    def insert(self, payload, **kw): return self._w("insert", payload, **kw)
    def upsert(self, payload, **kw): return self._w("upsert", payload, **kw)
    def update(self, payload, **kw): return self._w("update", payload, **kw)
    def delete(self, **kw): return self._w("delete", None, **kw)

    def __getattr__(self, name):
        raise StrictSupabaseError(f"StrictSupabase does not model .{name}()")

    # --- run ---------------------------------------------------------------------
    def execute(self):
        self.sb.queries.append({"table": self.table, "columns": self._cols,
                                "filters": [f[:3] for f in self._filters],
                                "order": self._order, "limit": self._limit,
                                "range": self._range, "write": self._write})
        if self._write:
            kind, payload, kw = self._write
            self.sb.writes.append({"table": self.table, "kind": kind, "payload": payload,
                                   "filters": [f[:3] for f in self._filters], **kw})
            data = payload if isinstance(payload, list) else ([payload] if payload else [])
            return _Result(data)
        rows = [r for r in self.sb.tables.get(self.table, []) if all(f[3](r) for f in self._filters)]
        for col, desc in reversed(self._order):
            # Postgres: NULLS LAST ascending, NULLS FIRST descending
            rows.sort(key=lambda r, c=col: (r.get(c) is None, _sortable(r.get(c))), reverse=desc)
        if self._range:
            rows = rows[self._range[0]:self._range[1] + 1]
        if self._limit is not None:
            rows = rows[:self._limit]
        rows = [dict(r) if self._cols is None else {c: r.get(c) for c in self._cols} for r in rows]
        if self._single:
            if len(rows) > 1 or (self._single == "single" and not rows):
                raise StrictSupabaseError(f"{self._single}(): {len(rows)} rows from {self.table}")
            return _Result(rows[0] if rows else None)
        return _Result(rows)


class _Result:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if isinstance(data, list) else (1 if data else 0)


def parse_select(table, *columns):
    """Validate a select list against the real schema; None means '*'.
    For stateful fakes that keep their own storage but must read like
    Postgres (only selected columns, only real columns)."""
    return _Query(StrictSupabase({}), table).select(*columns)._cols


def check_column(table, col):
    _Query(StrictSupabase({}), table)._check_col(col)


def check_write(table, row):
    """A write naming a column the real table doesn't have fails (PGRST204)."""
    for col in row:
        check_column(table, col)


def project(row, cols):
    return dict(row) if cols is None else {c: row.get(c) for c in cols}


class StrictSupabase:
    def __init__(self, tables):
        for t in tables:
            if t not in SCHEMA:
                raise StrictSupabaseError(f"table {t!r} does not exist (db_schema_columns.json)")
        self.tables = {t: [dict(r) for r in rows] for t, rows in tables.items()}
        self.queries, self.writes = [], []

    def table(self, name):
        if name not in SCHEMA:
            raise StrictSupabaseError(f"table {name!r} does not exist (db_schema_columns.json)")
        return _Query(self, name)

    def selected(self, table):
        """Column lists selected from `table`, in order (None = '*')."""
        return [q["columns"] for q in self.queries if q["table"] == table and not q["write"]]
