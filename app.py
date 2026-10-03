"""Run: python app.py [--share]. The company portal is private localhost-only."""
import argparse
import os
import threading
import time
from pathlib import Path
import gradio as gr
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from worker.engine import Engine, new_run
from worker.portal import register_portal
from worker.store import Store

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
FAULTS = {"No failure": "none", "Save fails once": "fail_once", "Save succeeds, acknowledgement lost": "lost_ack",
          "Save always fails": "always_fail", "Saved amount is corrupted": "corrupt"}
CSS = """
.gradio-container{max-width:1320px!important;font-family:Inter,system-ui!important}
#hero{background:#14243c;color:#fff;padding:28px 32px;border-radius:16px;margin-bottom:22px}
#hero h1{color:#fff;font-size:34px;margin:10px 0}#hero p{color:#c3d2e7;max-width:800px}
#hero .eyebrow{color:#83b8fa;font-size:12px;letter-spacing:2px;font-weight:700}
#status{border-left:4px solid #3575da;padding:12px 20px;background:#edf4ff;border-radius:8px}
"""

def build_ui(store, engine, public=False):
    def describe(e):
        value = e["observation"]
        if e["action"] == "verify" and value is None:
            return "No matching saved record found."
        if not isinstance(value, dict):
            return ""
        if "selected" in value:
            return f"Read {len(value['inbox'])} inbox rows; selected {', '.join(value['selected'])}."
        if "notice" in value:
            return value["notice"]
        if "amount" in value:
            return f"{value['id']}: {value['currency']} {value['amount']}; due {value['due']}."
        if "operation" in value:
            return f"{value['operation'].title()} {value['scope']} for {value['vendor']}."
        return ""

    def present(state):
        status = f"### {state['status'].replace('_',' ').title()}\n\n{state['summary']}"
        trace = [[i+1, e["action"], e["message"], describe(e)] for i,e in enumerate(state["trace"])]
        ledger = [[r[k] for k in ("id", "vendor", "amount", "currency", "due")] for r in store.list_records(state["sid"])]
        approval = state["status"] == "needs_approval"
        return (state, status, trace, ledger, state["screenshot"], engine.persist(state),
                gr.update(visible=approval), gr.update(visible=approval))

    def start(task, mode, fault_label, previous):
        if not task or not task.strip():
            raise gr.Error("Enter a task first.")
        if len(task) > 2000:
            raise gr.Error("Keep the task under 2,000 characters.")
        if public and mode == "Model planner" and os.getenv("ALLOW_PUBLIC_MODEL", "false").lower() != "true":
            raise gr.Error("Model mode is disabled on this public demo. Run locally with your own API key.")
        # One isolated sandbox per visitor; repeated tasks reuse its ledger.
        sid = previous["sid"] if previous else store.new_session(FAULTS[fault_label])
        state = new_run(task.strip(), sid, mode, FAULTS[fault_label])
        for update in engine.execute(state):
            yield present(update)

    def resume(state):
        if state:
            engine.approval(state, True)
            for update in engine.execute(state):
                yield present(update)

    def decline(state):
        if state:
            return present(engine.approval(state, False))
        return (None, "Ready", [], [], None, None, gr.update(visible=False), gr.update(visible=False))

    def reset():
        return (None, "### Ready\nEnter a goal to start a fresh sandbox.", [], [], None, None,
                gr.update(visible=False), gr.update(visible=False))

    with gr.Blocks(title="Harbor | Autonomous Task Worker") as ui:
        state = gr.State(None)
        gr.HTML('<div id="hero"><span class="eyebrow">AUTONOMOUS TASK WORKER / WORKING PROTOTYPE</span><h1>You set the goal. Harbor does the work.</h1><p>A small invoice worker that reads a company portal, enters records through a browser, and verifies the outcome.</p></div>')
        with gr.Row():
            with gr.Column(scale=4):
                task = gr.Textbox(label="What should the worker accomplish?", lines=3,
                    value="Find the latest invoice from Company X, enter it into our internal system, and tell me once it is done.")
                with gr.Row():
                    mode = gr.Dropdown(["Offline demo", "Model planner"], value="Offline demo", label="Planner")
                    fault = gr.Dropdown(list(FAULTS), value="Save fails once", label="Reliability scenario")
                gr.Markdown("**Offline demo uses rules, not an AI model.** Model planner chooses each action using an API key configured on the server. Both use real Chromium and SQLite.")
                gr.Markdown(f"Configured API model: **{os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')}**. Select Model planner to use it.")
                with gr.Row():
                    run = gr.Button("Run task", variant="primary")
                    fresh = gr.Button("New sandbox")
                gr.Examples([["Record all invoices from Company X."], ["Summarize all invoices from Acme Supplies."],
                    ["Record the latest invoice from Northstar Labs."], ["Record the latest invoice from Broken Fields Ltd."]], inputs=[task])
                gr.Markdown("Each visitor gets a separate synthetic sandbox. Repeated tasks reuse its ledger. **New sandbox** starts fresh and applies the selected failure scenario. The sandbox clock is fixed at October 4, 2026.")
            with gr.Column(scale=3):
                status = gr.Markdown("### Ready\nA completion claim requires observed evidence.", elem_id="status")
                approve = gr.Button("Approve this record and continue", variant="primary", visible=False)
                reject = gr.Button("Decline this record", visible=False)
                evidence = gr.File(label="Download run evidence (JSON)")
        with gr.Tabs():
            with gr.Tab("Execution trace"):
                trace = gr.Dataframe(headers=["Step", "Action", "Reason", "Observed result"], interactive=False, wrap=True,
                    column_widths=["65px", "110px", "46%", "40%"])
            with gr.Tab("Saved records"):
                ledger = gr.Dataframe(headers=["Invoice", "Vendor", "Amount", "Currency", "Due date"], interactive=False)
            with gr.Tab("Browser evidence"):
                screenshot = gr.Image(label="Latest worker browser screenshot", type="filepath", interactive=False)
            with gr.Tab("How it works"):
                gr.Markdown("""### A small loop with clear responsibilities

**Goal → planner → action guard → browser tool → observation → verifier.** Repeat until the goal is verified, needs human input, or fails.

The API model interprets the goal and chooses each next action. The Python engine checks permissions, remembers observed fields, limits retries and controls completion. Playwright reads the inbox and fills the form. FastAPI owns the company portal; SQLite owns persisted records.

### Why this design

- **Autonomy:** choose next actions from observations, with no user-supplied click sequence.
- **Execution:** operate real Chromium and submit an actual form.
- **Reliability:** reconcile uncertain saves before retrying; at most three save attempts.
- **Verification:** reload persisted rows and compare ID, vendor, amount, currency and due date.
- **Generalization:** latest/all, record/report and different vendors reuse the same engine and tools.
- **Engineering quality:** a small planner/executor/verifier boundary with real browser integration tests.
- **Product thinking:** return the requested outcome and evidence; pause for high-value approval or missing data.
- **Technical understanding:** each file has one job; no agent framework or vector database is needed for this scope.

### Limits we can explain

One synthetic invoice portal, one vendor per task, latest/all scope, USD only. No payments, arbitrary websites, email sending or production credentials. A batch can partly complete before failure. Offline mode is rules; live model behavior is measured separately. Guards constrain actions but do not guarantee correct intent interpretation.
""")
            with gr.Tab("Evaluation evidence"):
                path = ROOT / "docs" / "EVALUATION.md"
                gr.Markdown(path.read_text(encoding="utf-8") if path.exists() else "Real-model evaluation is in progress. Results will be saved with the submission.")
        outputs = [state, status, trace, ledger, screenshot, evidence, approve, reject]
        run.click(start, [task, mode, fault, state], outputs, concurrency_limit=1, concurrency_id="worker")
        approve.click(resume, [state], outputs, concurrency_limit=1, concurrency_id="worker")
        reject.click(decline, [state], outputs, concurrency_limit=1, concurrency_id="worker")
        fresh.click(reset, [], outputs, concurrency_limit=1, concurrency_id="worker")
        gr.Markdown("Built for a narrow, explainable workflow. No real inboxes, payments or company credentials. Public model mode is off by default.")
    return ui

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--share", action="store_true", help="Create a temporary Gradio public link")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--portal-port", type=int, default=8765)
    args = parser.parse_args()
    store = Store(ROOT / "data" / "sandbox.sqlite3")
    portal = FastAPI(title="Harbor sandbox")
    register_portal(portal, store)
    origin = f"http://127.0.0.1:{args.portal_port}"
    server = uvicorn.Server(uvicorn.Config(portal, host="127.0.0.1", port=args.portal_port, log_level="warning"))
    # Windows asyncio's Proactor loop supports Playwright subprocesses. Gradio callbacks
    # execute synchronously in worker threads, separate from the portal server thread.
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(60):
        if server.started:
            break
        if not thread.is_alive():
            raise RuntimeError("Portal failed to start. Check the portal port.")
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("Portal startup timed out")
    try:
        ui = build_ui(store, Engine(origin, ROOT / "artifacts" / "runs"), public=args.share)
        ui.queue(max_size=12).launch(server_name="127.0.0.1", server_port=args.port, share=args.share,
            theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"), css=CSS,
            allowed_paths=[str(ROOT / "artifacts" / "runs")])
    finally:
        server.should_exit = True

if __name__ == "__main__":
    main()
