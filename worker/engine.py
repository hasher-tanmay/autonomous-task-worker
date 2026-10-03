"""Observe -> decide -> execute -> verify. Success belongs to the host, not the model."""
import json
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4
from .browser import BrowserTools
from .planner import Clarification, ModelPlanner, offline_intent, offline_next

MAX_STEPS = 40
MAX_SAVES = 3
APPROVAL_LIMIT = Decimal("5000")
FIELDS = ("id", "vendor", "amount", "currency", "due")

def new_run(task, sid, mode="Offline demo", fault="none"):
    return dict(run_id=uuid4().hex, task=task, sid=sid, mode=mode, fault=fault,
                status="ready", intent=None, discovered=False, selected=[], sources={},
                verified={}, attempts={}, approved=[], pending=None, last_action="", last_id="",
                steps=0, trace=[], summary="Ready to start", screenshot=None)

def event(state, action, message, observation=None):
    state["trace"].append(dict(time=datetime.now(timezone.utc).isoformat(), action=action,
                               message=message, observation=observation))

def valid_source(source):
    try:
        amount = Decimal(source["amount"])
        if not amount.is_finite() or amount <= 0:
            return False
        date.fromisoformat(source["due"])
        return all(source.get(k) for k in FIELDS)
    except (KeyError, InvalidOperation, ValueError):
        return False

def select(inbox, intent):
    matches = [r for r in inbox if r["vendor"].casefold() == intent["vendor"].strip().casefold()]
    if not matches:
        raise Clarification(f"No invoices found for {intent['vendor']}. Choose a vendor visible in the inbox.")
    matches.sort(key=lambda r: r["issued"], reverse=True)
    if intent["scope"] == "latest":
        if len(matches) > 1 and matches[0]["issued"] == matches[1]["issued"]:
            raise Clarification("Two invoices have the latest issue date. Please specify the intended invoice.")
        matches = matches[:1]
    return [r["id"] for r in matches]

class Engine:
    def __init__(self, origin, artifacts):
        self.origin = origin
        self.artifacts = Path(artifacts)

    def persist(self, state):
        folder = self.artifacts / state["run_id"]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "evidence.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(target)
        return str(target)

    def approval(self, state, approve):
        if state["status"] != "needs_approval" or not state["pending"]:
            return state
        if not approve:
            state["status"] = "cancelled"
            state["summary"] = "Approval declined. No further records were entered; earlier verified records remain in the ledger."
            event(state, "approval", "User declined the pending record.")
        else:
            iid = state["pending"]
            state["approved"].append(iid)
            state["pending"] = None
            state["status"] = "ready"
            event(state, "approval", f"User approved {iid} for this run only.")
        self.persist(state)
        return state

    def execute(self, state):
        if state["status"] in ("completed", "failed", "cancelled", "needs_clarification", "needs_approval"):
            yield state
            return
        state["status"] = "running"
        started = time.monotonic()
        planner = None
        try:
            if state["mode"] == "Model planner":
                planner = ModelPlanner()
            if state["intent"] is None:
                intent = planner.intent(state["task"]) if planner else offline_intent(state["task"])
                if intent.vendor == "NEEDS_CLARIFICATION":
                    raise Clarification("The request exceeds the supported invoice scope. Specify record/report, one vendor, and latest/all.")
                state["intent"] = intent.model_dump()
                event(state, "plan", f"{intent.operation.title()} {intent.scope} invoices for {intent.vendor}.", state["intent"])
                self.persist(state)
                yield state
            with BrowserTools(self.origin, state["sid"], self.artifacts/state["run_id"]) as tools:
                while state["steps"] < MAX_STEPS and time.monotonic()-started < 180:
                    state["steps"] += 1
                    decision = planner.next(state) if planner else offline_next(state)
                    action, iid = decision.action, decision.invoice_id
                    if action == "ask":
                        raise Clarification(decision.message or "Please clarify the invoice goal.")
                    if action == "finish":
                        required = state["verified"] if state["intent"]["operation"] == "record" else state["sources"]
                        if not state["selected"] or not all(x in required for x in state["selected"]):
                            event(state, "guard", "Completion rejected: required evidence is missing.")
                            self.persist(state)
                            yield state
                            continue
                        state["status"] = "completed"
                        verb = "Verified in the ledger" if state["intent"]["operation"] == "record" else "Read from source documents"
                        lines = [f"{x}: {state['sources'][x]['currency']} {state['sources'][x]['amount']}, due {state['sources'][x]['due']}" for x in state["selected"]]
                        state["summary"] = verb+":\n"+"\n".join(lines)
                        event(state, "finish", "Outcome verified. Evidence saved.")
                        break
                    if action == "discover":
                        inbox = tools.discover()
                        state["selected"] = select(inbox, state["intent"])
                        state["discovered"] = True
                        observation = {"inbox": inbox, "selected": state["selected"]}
                    elif iid not in state["selected"]:
                        event(state, "guard", "Rejected an action on an unselected invoice.")
                        self.persist(state)
                        yield state
                        continue
                    elif action == "read":
                        observation = tools.read(iid)
                        if not valid_source(observation):
                            raise Clarification(f"Invoice {iid} has missing or invalid source fields. No record was entered. Fix the source and start a new task.")
                        state["sources"][iid] = observation
                    elif action == "save":
                        if state["intent"]["operation"] != "record" or iid not in state["sources"]:
                            event(state, "guard", "Save rejected: write goal and a validated source are required.")
                            self.persist(state)
                            yield state
                            continue
                        source = state["sources"][iid]
                        if iid in state["verified"]:
                            event(state, "guard", "Already verified; do not write again.")
                            self.persist(state)
                            yield state
                            continue
                        if Decimal(source["amount"]) > APPROVAL_LIMIT and iid not in state["approved"]:
                            state["pending"] = iid
                            state["status"] = "needs_approval"
                            state["summary"] = f"Approve recording {iid}: {source['currency']} {source['amount']}, due {source['due']}? The sandbox requires approval above USD 5,000."
                            event(state, "approval", state["summary"])
                            break
                        # Reconcile before any repeated write, even if the model tries to skip it.
                        if state["attempts"].get(iid, 0):
                            existing = tools.verify(iid)
                            if existing:
                                if any(existing[k] != source[k] for k in FIELDS):
                                    event(state, "verify", "Persisted fields conflict with the source.", existing)
                                    state["screenshot"] = tools.screenshot(state["steps"])
                                    raise RuntimeError(f"Verification mismatch for {iid}. A conflicting row remains; manual review required.")
                                state["verified"][iid] = existing
                                event(state, "verify", "Existing row matched; avoided another write.", existing)
                                state["last_action"], state["last_id"] = "verify", iid
                                self.persist(state)
                                yield state
                                continue
                            if state["attempts"][iid] >= MAX_SAVES:
                                raise RuntimeError(f"Save failed for {iid} after {MAX_SAVES} attempts. No matching record found.")
                            time.sleep(min(0.4*2**(state["attempts"][iid]-1), 1.6))
                        state["attempts"][iid] = state["attempts"].get(iid, 0)+1
                        try:
                            observation = tools.save(source)
                        except Exception as exc:
                            # A browser timeout after clicking has an uncertain outcome.
                            observation = {"notice": "Save outcome unknown", "error_type": type(exc).__name__}
                    elif action == "verify":
                        if iid not in state["sources"]:
                            raise RuntimeError("Cannot verify without a source document")
                        observation = tools.verify(iid)
                        if observation is None and state["attempts"].get(iid, 0) >= MAX_SAVES:
                            event(state, "verify", "No matching row after the maximum save attempts.")
                            state["screenshot"] = tools.screenshot(state["steps"])
                            raise RuntimeError(f"Save failed for {iid} after {MAX_SAVES} attempts. No matching record found.")
                        if observation:
                            if any(observation[k] != state["sources"][iid][k] for k in FIELDS):
                                event(state, "verify", "Persisted fields conflict with the source.", observation)
                                state["screenshot"] = tools.screenshot(state["steps"])
                                raise RuntimeError(f"Verification mismatch for {iid}. A conflicting row remains; manual review required.")
                            state["verified"][iid] = observation
                    else:
                        raise RuntimeError("Unsupported action")
                    state["last_action"], state["last_id"] = action, iid
                    event(state, action, decision.message, observation)
                    state["screenshot"] = tools.screenshot(state["steps"])
                    state["summary"] = f"Working: {action} {iid}. {len(state['verified'])} record(s) verified."
                    self.persist(state)
                    yield state
                if state["status"] == "running":
                    raise RuntimeError("Execution budget reached. Review the trace; completion was not established.")
        except Clarification as exc:
            state["status"] = "needs_clarification"
            state["summary"] = str(exc)
            event(state, "clarification", str(exc))
        except Exception as exc:
            state["status"] = "failed"
            # Never expose API response bodies or secrets to the public interface.
            state["summary"] = str(exc) if isinstance(exc, RuntimeError) else f"Execution stopped ({type(exc).__name__}). Check local logs and retry."
            event(state, "failure", state["summary"])
        self.persist(state)
        yield state
