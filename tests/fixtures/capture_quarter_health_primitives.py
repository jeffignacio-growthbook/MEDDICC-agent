#!/usr/bin/env python3
"""
Capture the REAL outputs of the four primitives the quarter-health composer
calls, in its fixed order, against live Supabase, plus the inputs its
downside calculation reads (the governed stage close-rate table and the
deals rows of the forecast cohort's high-risk deals). Read-only.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \\
        python tests/fixtures/capture_quarter_health_primitives.py > capture.log

The JSON goes to stdout as gzip+base64 lines ("CAPTURE i/n <chunk>") with
its md5, so it survives a CI log intact; decode with --decode capture.log.
"""
import asyncio
import base64
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "api", REPO / "scripts", REPO / "scripts" / "analytics"):
    sys.path.insert(0, str(p))

CHUNK = 3000


def _decode(log_path, out_path):
    chunks, md5 = {}, None
    for line in Path(log_path).read_text().splitlines():
        if "CAPTURE_MD5 " in line:
            md5 = line.split("CAPTURE_MD5 ", 1)[1].strip()
        elif "CAPTURE " in line:
            head, chunk = line.split("CAPTURE ", 1)[1].split(" ", 1)
            i, n = map(int, head.split("/"))
            chunks[i] = chunk.strip()
    raw = gzip.decompress(base64.b64decode("".join(chunks[i] for i in sorted(chunks))))
    assert hashlib.md5(raw).hexdigest() == md5, "md5 mismatch"
    Path(out_path).write_bytes(raw)
    print(f"decoded {len(chunks)} chunks, {len(raw)} bytes, md5 {md5}")


async def _capture():
    import api.handlers as h
    from db import get_supabase
    from forecast_analyses import query_stage_close_rate
    sb = get_supabase()
    out = {"captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out["query_forecast_trust"] = await h.query_forecast_trust({}, sb)
    out["query_pipeline"] = await h.query_pipeline({}, sb)
    out["query_high_priority_deal_risk"] = await h.query_high_priority_deal_risk({}, sb)
    out["query_loss_concentration"] = await h.query_loss_concentration({}, sb)
    out["stage_close_rate"] = query_stage_close_rate(sb)
    ids = [d["deal_id"] for d in out["query_forecast_trust"].get("assessed_deals", [])
           if d.get("overall_label") == "high_risk"]
    out["high_risk_deal_rows"] = (sb.table("deals").select(
        "deal_id,company_name,pipeline_id,new_arr,expansion_arr,highest_stage_order_reached,stage"
    ).in_("deal_id", ids).execute().data or []) if ids else []
    return out


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--decode":
        return _decode(sys.argv[2], sys.argv[3])
    data = asyncio.run(_capture())
    raw = json.dumps(data, default=str, sort_keys=False).encode()
    b64 = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)]
    for k in ("query_forecast_trust", "query_pipeline", "query_high_priority_deal_risk",
              "query_loss_concentration"):
        print(f"{k}: {len(json.dumps(data[k], default=str))} chars, status {data[k].get('status')}")
    print(f"high_risk_deal_rows: {len(data['high_risk_deal_rows'])}")
    for i, p in enumerate(parts, 1):
        print(f"CAPTURE {i}/{len(parts)} {p}")
    print(f"CAPTURE_MD5 {hashlib.md5(raw).hexdigest()}")


if __name__ == "__main__":
    main()
