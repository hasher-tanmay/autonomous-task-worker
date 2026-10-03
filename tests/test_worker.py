"""Real browser + HTTP + SQLite tests. No browser tools are mocked here."""
import socket
import threading
import time
import pytest
import uvicorn
from fastapi import FastAPI
from worker.engine import Engine, new_run, select
from worker.planner import Clarification, offline_intent, Decision
from worker.portal import register_portal
from worker.store import Store

@pytest.fixture(scope="module")
def system(tmp_path_factory):
    root = tmp_path_factory.mktemp("sandbox")
    store = Store(root / "test.sqlite3")
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
    assert server.started
    yield store, Engine(f"http://127.0.0.1:{port}", root / "evidence")
    server.should_exit = True
    thread.join(5)

def run(system, task="Record the latest invoice from Company X.", fault="none", sid=None):
    store, engine = system
    state = new_run(task, sid or store.new_session(fault), fault=fault)
    list(engine.execute(state))
    return state

@pytest.mark.parametrize("fault,attempts", [("none", 1), ("fail_once", 2), ("lost_ack", 1)])
def test_real_save_recovery(system, fault, attempts):
    state = run(system, fault=fault)
    assert state["status"] == "completed", state["summary"]
    assert state["attempts"]["X-101"] == attempts
    assert state["verified"]["X-101"]["amount"] == "1240.50"
    assert len(system[0].list_records(state["sid"])) == 1

def test_no_duplicates_on_repeat(system):
    first = run(system)
    second = run(system, sid=first["sid"])
    assert second["status"] == "completed"
    assert len(system[0].list_records(first["sid"])) == 1

def test_all_scope_reuses_same_worker(system):
    state = run(system, "Record all invoices from Company X.")
    assert state["status"] == "completed"
    assert set(state["verified"]) == {"X-100", "X-101"}

def test_report_does_not_write(system):
    state = run(system, "Summarize all invoices from Acme Supplies.")
    assert state["status"] == "completed"
    assert state["sources"]["A-201"]["amount"] == "325.75"
    assert system[0].list_records(state["sid"]) == []

def test_approval_resume(system):
    state = run(system, "Record the latest invoice from Northstar Labs.")
    assert state["status"] == "needs_approval"
    assert system[0].list_records(state["sid"]) == []
    system[1].approval(state, True)
    list(system[1].execute(state))
    assert state["status"] == "completed"
    assert state["verified"]["N-301"]["amount"] == "7800.00"

def test_approval_decline(system):
    state = run(system, "Record the latest invoice from Northstar Labs.")
    system[1].approval(state, False)
    assert state["status"] == "cancelled"
    assert system[0].list_records(state["sid"]) == []

def test_missing_fields_no_write(system):
    state = run(system, "Record the latest invoice from Broken Fields Ltd.")
    assert state["status"] == "needs_clarification"
    assert system[0].list_records(state["sid"]) == []

def test_persistent_failure_is_bounded(system):
    state = run(system, fault="always_fail")
    assert state["status"] == "failed"
    assert state["attempts"]["X-101"] == 3
    assert system[0].list_records(state["sid"]) == []

def test_corrupt_save_not_success(system):
    state = run(system, fault="corrupt")
    assert state["status"] == "failed"
    assert "mismatch" in state["summary"]
    assert not state["verified"]

def test_session_isolation(system):
    state = run(system)
    other = system[0].new_session()
    assert system[0].list_records(other) == []
    assert len(system[0].list_records(state["sid"])) == 1

def test_ambiguous_task_stops(system):
    state = run(system, "Record the latest invoice.")
    assert state["status"] == "needs_clarification"
    assert not state["attempts"]

@pytest.mark.parametrize("task", ["Pay Company X invoice", "Record Company X invoice before September", "Record Company X and Acme Supplies invoices"])
def test_unsupported_requests_not_silently_changed(task):
    with pytest.raises(Clarification):
        offline_intent(task)

def test_tied_latest_requires_clarification():
    with pytest.raises(Clarification):
        select([{"id": "a", "vendor": "X", "issued": "2026-10-01"}, {"id": "b", "vendor": "X", "issued": "2026-10-01"}], {"vendor": "X", "scope": "latest"})

def test_planner_cannot_claim_unverified_success(system, monkeypatch):
    monkeypatch.setattr("worker.engine.offline_next", lambda _: Decision(action="finish"))
    state = run(system)
    assert state["status"] == "failed"
    assert state["steps"] == 40
    assert not system[0].list_records(state["sid"])
