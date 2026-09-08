"""一次性演示数据驱动：按指定 SVN 提交逐条打包并只同步归档后端（不走 FTP）。

用法：
    .venv/bin/python tools/pack_author_commits.py /tmp/xhh_commits.json /tmp/xhh_pack_results.json

commits JSON 形如 [{\"revision\": 1726469, \"date\": \"...Z\", \"regions\": [\"ID\"]}, ...]，
按列表顺序逐条 command_pack，然后用 ArchiveBackendClient.sync_report 直接入档。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from electron_bridge import ElectronBridgeService  # noqa: E402
from manual_publication import ArchiveBackendClient, BackendSettings  # noqa: E402
from package_region_filter import region_dir_for_code  # noqa: E402

BACKEND_URL = "http://127.0.0.1:8780"


def emit(event: str, data: dict) -> None:
    message = data.get("message")
    if message:
        print(f"    [{event}] {message}", flush=True)


def main() -> None:
    commits = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    results_path = Path(sys.argv[2])
    service = ElectronBridgeService()
    backend = BackendSettings(BACKEND_URL)
    results = []
    for commit in commits:
        revision = int(commit["revision"])
        regions = commit.get("regions") or []
        region = regions[0] if len(regions) == 1 else ""
        started = time.perf_counter()
        print(f"== r{revision} {region or regions} {commit.get('date')}", flush=True)
        if not region:
            print("    SKIP: 区域无法唯一确定", flush=True)
            results.append({**commit, "ok": False, "error": "region_ambiguous"})
            continue
        payload = {
            "region": region,
            "input_method": "revision_spec",
            "current_revision_spec": f"r{revision}",
            "svn_log_source": "auto",
            "use_auth_cache": True,
            "content_mode": "local_latest",
            "scope_roots": f"/{region_dir_for_code(region)}",
        }
        try:
            pack = service.dispatch("pack", payload, emit)
        except Exception as error:
            print(f"    PACK FAILED: {error}", flush=True)
            results.append({**commit, "ok": False, "error": str(error)})
            continue
        record = {
            **commit,
            "ok": True,
            "region": region,
            "package_id": pack["package_id"],
            "report_path": pack["report_path"],
            "file_count": pack["success_count"],
            "failure_count": pack["failure_count"],
            "validation": pack["validation"],
            "can_archive": pack["can_archive"],
            "seconds": round(time.perf_counter() - started, 1),
        }
        try:
            sync = ArchiveBackendClient().sync_report(pack["report_path"], backend)
            record["sync"] = sync.outcome
        except Exception as error:
            record["sync"] = "failed"
            record["sync_error"] = str(error)
            print(f"    SYNC FAILED: {error}", flush=True)
        print(
            f"    -> {record['package_id']} sync={record.get('sync')} "
            f"files={record['file_count']} validation={record['validation']} "
            f"({record['seconds']}s)",
            flush=True,
        )
        results.append(record)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = sum(1 for r in results if r.get("ok") and r.get("sync") in {"created", "replayed"})
    print(f"DONE: {ok}/{len(commits)} packed+synced -> {results_path}", flush=True)


if __name__ == "__main__":
    main()
