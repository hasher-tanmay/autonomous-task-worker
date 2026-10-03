"""Measure real model + browser outcomes. No planner or browser mocks."""
import argparse
import json
import socket
import sys
import tempfile
import threading
import time
import os
from urllib.parse import urlparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn
from worker.engine import Engine, new_run
from worker.portal import register_portal
from worker.store import Store, SEED

CASES = [
    ("Natural wording + transient failure", "Find the newest bill from Company X and register it in the internal ledger.", "fail_once", "completed", 1),
    ("Lost acknowledgement", "Record the latest invoice from Company X.", "lost_ack", "completed", 1),
    ("Multiple invoices", "Enter all invoices from Company X into the ledger.", "none", "completed", 2),
    ("Read-only different vendor", "Summarize all invoices from Acme Supplies.", "none", "completed", 0),
    ("Approval and resume", "Record the latest invoice from Northstar Labs.", "none", "completed", 1),
    ("Approval declined", "Record the latest invoice from Northstar Labs.", "none", "cancelled", 0),
    ("Missing source fields", "Record the latest invoice from Broken Fields Ltd.", "none", "needs_clarification", 0),
    ("Permanent failure", "Record the latest invoice from Company X.", "always_fail", "failed", 0),
    ("Corrupted persistence", "Record the latest invoice from Company X.", "corrupt", "failed", 1),
    ("Unsupported request", "Pay the latest invoice from Company X.", "none", "needs_clarification", 0),
]
EXPECTED_IDS = {"Natural wording + transient failure": {"X-101"}, "Lost acknowledgement": {"X-101"},
    "Multiple invoices": {"X-100", "X-101"}, "Approval and resume": {"N-301"}, "Corrupted persistence": {"X-101"}}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/model-evaluation.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY in your ignored .env first.")
    with tempfile.TemporaryDirectory(prefix="harbor-eval-", dir=root / "work") as folder:
        store = Store(Path(folder) / "db.sqlite3")
        app = FastAPI()
        register_portal(app, store)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Evaluation portal failed to start")
        engine = Engine(f"http://127.0.0.1:{port}", Path(folder) / "runs")
        results = []
        try:
            for name, task, fault, expected, count in CASES:
                state = new_run(task, store.new_session(fault), "Model planner", fault)
                started = time.monotonic()
                list(engine.execute(state))
                before_approval = None
                if name in ("Approval and resume", "Approval declined"):
                    before_approval = len(store.list_records(state["sid"]))
                    if state["status"] == "needs_approval":
                        engine.approval(state, name == "Approval and resume")
                        list(engine.execute(state))
                rows = store.list_records(state["sid"])
                passed = state["status"] == expected and len(rows) == count
                passed = passed and {r["id"] for r in rows} == EXPECTED_IDS.get(name, set())
                if state["status"] == "completed":
                    sources = {r["id"]: r for r in SEED}
                    passed = passed and all(all(r[k] == sources[r["id"]][k] for k in ("vendor", "amount", "currency", "due")) for r in rows)
                if before_approval is not None:
                    passed = passed and before_approval == 0
                if name == "Natural wording + transient failure":
                    passed = passed and state["attempts"].get("X-101") == 2
                if name == "Lost acknowledgement":
                    passed = passed and state["attempts"].get("X-101") == 1
                if name == "Permanent failure":
                    passed = passed and state["attempts"].get("X-101") == 3
                if name == "Corrupted persistence":
                    passed = passed and "mismatch" in state["summary"] and not state["verified"]
                result = dict(name=name, task=task, fault=fault, expected_status=expected,
                    actual_status=state["status"], passed=passed, seconds=round(time.monotonic()-started, 2),
                    summary=state["summary"], save_attempts=state["attempts"], verified=state["verified"],
                    persisted_rows=rows, rows_before_approval=before_approval, trace=state["trace"])
                results.append(result)
                print(f"{'PASS' if passed else 'FAIL'} {name}: {state['status']} ({result['seconds']}s)", flush=True)
        finally:
            server.should_exit = True
            thread.join(5)
        report = dict(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            provider_host=urlparse(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).hostname,
            mode="Real API, real Chromium, real HTTP portal, real SQLite", passed=sum(r["passed"] for r in results), total=len(results), cases=results)
        target = root / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Result: {report['passed']}/{report['total']}; saved {args.output}", flush=True)
        if report["passed"] != report["total"]:
            raise SystemExit(1)

if __name__ == "__main__":
    (Path(__file__).resolve().parents[1] / "work").mkdir(exist_ok=True)
    main()
