"""一次性演示数据修正：把归档记录的录入时间改成对应 SVN 提交时间。

- package_archives.created_at  -> 提交时间的 +08:00 本地 ISO（秒精度）
- package_archives.received_at -> 提交时间的 UTC Z（秒精度）
- review_status='confirmed' 的 reviewed_at -> 同上 UTC Z
- release_baselines：每区域指向提交时间最新的包，updated_at -> 该提交 UTC Z

用法：
    .venv/bin/python tools/fix_archive_timestamps.py <results.json> [<results2.json> ...]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = "/Users/ivan/Desktop/Config /AOVConfigVerification/配置前端/_accept/backend/accept-archive.sqlite3"
LOCAL_TZ = timezone(timedelta(hours=8))


def parse_commit(date: str) -> datetime:
    return datetime.fromisoformat(date.replace("Z", "+00:00"))


def main() -> None:
    records = []
    for arg in sys.argv[1:]:
        records.extend(json.loads(Path(arg).read_text(encoding="utf-8")))
    ok = [r for r in records if r.get("ok") and r.get("sync") in {"created", "replayed"}]
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        for record in ok:
            commit_dt = parse_commit(record["date"]).replace(microsecond=0)
            created_local = commit_dt.astimezone(LOCAL_TZ).isoformat()
            received_utc = commit_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            cur = conn.execute(
                """
                UPDATE package_archives
                SET created_at = ?, received_at = ?,
                    reviewed_at = CASE WHEN review_status = 'confirmed' THEN ? ELSE reviewed_at END
                WHERE package_id = ?
                """,
                (created_local, received_utc, received_utc, record["package_id"]),
            )
            if cur.rowcount != 1:
                print(f"WARN: {record['package_id']} updated {cur.rowcount} rows")
        regions = sorted({r["region"] for r in ok})
        for region in regions:
            latest = max((r for r in ok if r["region"] == region), key=lambda r: r["date"])
            updated_utc = parse_commit(latest["date"]).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            cur = conn.execute(
                "UPDATE release_baselines SET package_id = ?, updated_at = ? WHERE region_code = ?",
                (latest["package_id"], updated_utc, region),
            )
            print(f"baseline {region}: {latest['package_id']} @ {updated_utc} ({cur.rowcount} row)")
        conn.commit()
        rows = conn.execute(
            """
            SELECT package_id, region_code, created_at, received_at, review_status, reviewed_at
            FROM package_archives ORDER BY received_at
            """
        ).fetchall()
        for row in rows:
            print(dict(row))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
