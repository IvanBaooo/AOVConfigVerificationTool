"""临时演示数据：仅供 Dashboard 热点图预览，写入独立临时库，不碰真实数据。"""
import hashlib
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from archive_backend.repository import ArchiveRepository

db_path = sys.argv[1]
repo = ArchiveRepository(db_path)  # 建表
repo.close() if hasattr(repo, "close") else None

random.seed(20260904)
regions = [("TW", "Taiwan"), ("TH", "Thailand"), ("VN", "Vietnam"), ("ID", "Indonesia")]
now = datetime.now(timezone.utc)
conn = sqlite3.connect(db_path)

rows = 0
for days_ago in range(90):
    # 模拟发布节奏：工作日概率高，周末少
    weekday = (now - timedelta(days=days_ago)).weekday()
    n = random.choices([0, 1, 2, 3], weights=[55 if weekday < 5 else 80, 25, 15, 5])[0]
    for i in range(n):
        region, region_dir = random.choice(regions)
        ts = now - timedelta(days=days_ago, hours=random.randint(0, 9), minutes=random.randint(0, 59))
        stamp = ts.strftime("%Y%m%d%H%M%S")
        warnings = random.choices([0, 1, 2, 5, 9], weights=[50, 25, 15, 7, 3])[0]
        package_id = f"sgame_{region}_Beta{54 + (90 - days_ago) // 30}_{stamp}"
        payload = {
            "schema_version": "1",
            "package_id": package_id,
            "release": {"region_code": region, "region_dir": region_dir, "package_version": f"Beta{54 + (90 - days_ago) // 30}"},
            "status": {
                "package_status": "success",
                "validation_status": "passed" if warnings == 0 else "warning",
            },
        }
        conn.execute(
            """INSERT INTO package_archives
               (package_id, schema_version, idempotency_key, payload_sha256, payload_json,
                created_at, received_at, region_code, region_dir, package_version,
                package_status, validation_status, file_count, warning_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                package_id, "1", f"demo-{package_id}",
                hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
                json.dumps(payload, ensure_ascii=False),
                ts.isoformat(), ts.isoformat(), region, region_dir,
                payload["release"]["package_version"],
                "success", payload["status"]["validation_status"],
                random.randint(3, 40), warnings,
            ),
        )
        rows += 1

# 两个规则版本发布点
for days_ago, version in ((42, "2026.08.15.1"), (10, "2026.09.01.1")):
    ts = now - timedelta(days=days_ago)
    body = json.dumps({"rule_set_id": "aov-main", "version": version}, ensure_ascii=False)
    conn.execute(
        """INSERT INTO validation_rule_sets (rule_set_id, version, published_at, created_at, payload_sha256, payload_json)
           VALUES (?,?,?,?,?,?)""",
        ("aov-main", version, ts.isoformat(), ts.isoformat(), hashlib.sha256(body.encode()).hexdigest(), body),
    )

# 基线变更
for days_ago, region in ((30, "TW"), (18, "TH"), (6, "TW")):
    ts = now - timedelta(days=days_ago)
    conn.execute(
        """INSERT INTO archive_admin_audit (package_id, action, actor, reason, created_at)
           VALUES (?,?,?,?,?)""",
        (f"sgame_{region}_demo", "baseline_set", "admin", "演示数据", ts.isoformat()),
    )

conn.commit()
conn.close()
print(f"seeded {rows} archives into {db_path}")
