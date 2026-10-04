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
CSS = """
.gradio-container{max-width:1240px!important;font-family:Inter,ui-sans-serif,system-ui!important;padding:clamp(14px,3vw,28px)!important}
.gradio-container .main{padding:0!important}#workspace-tabs table{min-width:580px;font-family:ui-sans-serif,system-ui!important}#workspace-tabs td,#workspace-tabs th{font-family:ui-sans-serif,system-ui!important}
body{background:#f6f8fb!important}footer{display:none!important}
#brand{display:flex;align-items:center;justify-content:space-between;padding:4px 0 26px;border-bottom:1px solid #e2e8f0;margin-bottom:24px}
.brand-name{font-size:25px;font-weight:750;letter-spacing:-1px;color:#163c3a}.brand-mark{display:inline-flex;align-items:center;justify-content:center;background:#163c3a;color:white;width:38px;height:38px;border-radius:12px;margin-right:11px;font-size:22px}
.brand-sub{font-size:13px;color:#718096;margin-left:18px;letter-spacing:0;font-weight:400}.sandbox{border:1px solid #dce5e4;border-radius:20px;padding:6px 12px;font-size:12px;color:#52736c;background:#eef5f2}
#composer,#result-panel{background:white;border:1px solid #e2e8f0;border-radius:20px;padding:24px!important}
#composer h2{font-size:25px;letter-spacing:-.7px;color:#172d35;margin:0 0 8px}#composer textarea{font-size:16px!important;line-height:1.65!important}
#run-button{background:#17685b!important;border:0!important;color:white!important;min-height:46px;font-weight:650}
#new-workspace{min-height:46px}#workspace-tabs{margin-top:18px}
#status-card{min-height:198px}.status-tag{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:650;color:#64748b;text-transform:uppercase;letter-spacing:1px}.status-dot{width:8px;height:8px;border-radius:50%;background:currentColor}
#status-card h3{font-size:27px;letter-spacing:-.7px;line-height:1.25;color:#182e36;margin:18px 0 12px}.status-copy{color:#586878;font-size:14px;line-height:1.7;white-space:pre-line;margin:0}
.status-completed .status-tag{color:#168268}.status-running .status-tag{color:#2563eb}.status-needs_approval .status-tag,.status-needs_clarification .status-tag{color:#ad6a12}.status-failed .status-tag{color:#c53e4e}
.run-meta{border-top:1px solid #edf0f3;margin-top:20px;padding-top:13px;font-size:12px;color:#788493}
#workspace-summary{display:flex;gap:30px;align-items:center;padding:8px 2px 18px;color:#6b7c88;font-size:13px}#workspace-summary strong{color:#193d36;font-size:20px;margin-right:7px}
#quick-actions button{font-size:12px!important;min-height:34px!important;background:#f4f7f7!important;border:1px solid #e4ece9!important;color:#486259!important}
#activity{max-height:420px;overflow:auto}.activity-empty{text-align:center;padding:52px 20px;color:#83919b;font-size:14px}.activity-item{display:flex;gap:14px;padding:14px 8px;border-bottom:1px solid #edf0f3}.activity-number{flex:0 0 26px;height:26px;border-radius:8px;background:#eef5f2;color:#347567;text-align:center;font-size:12px;line-height:26px}.activity-title{font-size:13px;font-weight:600;color:#354957}.activity-detail{font-size:12px;color:#778592;line-height:1.5;margin-top:4px}
@media(max-width:700px){.gradio-container{padding:14px!important}.brand-sub{display:none}#composer,#result-panel{padding:18px!important}#status-card{min-height:140px}}
"""


def status_card(state=None):
    from html import escape
    status = state["status"] if state else "ready"
    titles = {"ready": "Ready when you are", "running": "Working on it", "completed": "Task complete",
              "needs_approval": "Your approval is needed", "needs_clarification": "A little more detail needed",
              "failed": "Task couldn't be completed", "cancelled": "Task cancelled"}
    labels = {"ready": "Ready", "running": "In progress", "completed": "Completed",
              "needs_approval": "Approval", "needs_clarification": "Needs input", "failed": "Failed", "cancelled": "Cancelled"}
    message = state["summary"] if state else "Your results will appear here."
    if status == "running":
        message = state["trace"][-1]["message"] if state["trace"] else "Getting started…"
    if status == "needs_clarification":
        message += "\nUpdate your task and run it again."
    meta = f'<div class="run-meta">{len(state["trace"])} actions · {len(state["verified"])} verified records</div>' if state else ""
    return f'<div id="status-card" class="status-{status}"><div class="status-tag"><span class="status-dot"></span>{labels[status]}</div><h3>{titles[status]}</h3><p class="status-copy">{escape(message)}</p>{meta}</div>'


def activity_view(state=None):
    from html import escape
    if not state or not state["trace"]:
        return '<div class="activity-empty">No activity yet</div>'
    rows = []
    for i, event in reversed(list(enumerate(state["trace"], 1))):
        observation = event["observation"]
        detail = ""
        if isinstance(observation, dict):
            if "amount" in observation:
                detail = f'{observation["id"]} · {observation["currency"]} {observation["amount"]} · Due {observation["due"]}'
            elif "notice" in observation:
                detail = observation["notice"]
        rows.append(f'<div class="activity-item"><span class="activity-number">{i}</span><div><div class="activity-title">{escape(event["message"])}</div><div class="activity-detail">{escape(str(detail))}</div></div></div>')
    return "".join(rows)


def build_ui(store, engine, public=False):
    model_allowed = bool(os.getenv("OPENAI_API_KEY")) and (not public or os.getenv("ALLOW_PUBLIC_MODEL", "false").lower() == "true")
    modes = [("AI worker", "Model planner"), ("Offline rules", "Offline demo")] if model_allowed else [("Offline rules", "Offline demo")]

    def present(state):
        records = store.list_records(state["sid"]) if state else []
        ledger = [[r[k] for k in ("id", "vendor", "amount", "currency", "due")] for r in records]
        approval = bool(state and state["status"] == "needs_approval")
        busy = bool(state and state["status"] in ("running", "needs_approval"))
        if state:
            engine.persist(state)
        summary = f'<div id="workspace-summary"><span><strong>{len(records)}</strong> saved invoices</span><span>USD ledger</span></div>'
        return (state, status_card(state), activity_view(state), ledger, state["screenshot"] if state else None,
                gr.update(visible=approval), gr.update(visible=approval), summary,
                gr.update(interactive=not busy), gr.update(interactive=not busy), gr.update(interactive=not busy))

    def start(task, mode, previous):
        if not task or not task.strip():
            raise gr.Error("Enter a task first.")
        if len(task) > 2000:
            raise gr.Error("Keep the task under 2,000 characters.")
        if mode == "Model planner" and not model_allowed:
            raise gr.Error("AI mode is unavailable in this workspace.")
        if previous and previous["status"] == "needs_approval":
            raise gr.Error("Approve or decline the pending record first.")
        sid = previous["sid"] if previous else store.new_session("none")
        state = new_run(task.strip(), sid, mode, "none")
        state["status"] = "running"
        yield present(state)
        for update in engine.execute(state):
            yield present(update)

    def resume(state):
        if state:
            engine.approval(state, True)
            state["status"] = "running"
            yield present(state)
            for update in engine.execute(state):
                yield present(update)

    def decline(state):
        return present(engine.approval(state, False) if state else None)

    with gr.Blocks(title="Harbor | Invoice workspace") as ui:
        state = gr.State(None)
        gr.HTML('<div id="brand"><div class="brand-name"><span class="brand-mark">h</span>harbor<span class="brand-sub">Invoice workspace</span></div><span class="sandbox">Sandbox</span></div>')
        with gr.Row(equal_height=True):
            with gr.Column(scale=6, min_width=320, elem_id="composer"):
                gr.Markdown("## What needs doing?")
                task = gr.Textbox(label="Task", show_label=False, lines=3, max_lines=6,
                    placeholder="Ask Harbor to record or summarize invoices…",
                    value="Record the latest invoice from Company X.")
                with gr.Row(elem_id="quick-actions"):
                    latest = gr.Button("Latest invoice", size="sm")
                    batch = gr.Button("Record all", size="sm")
                    report = gr.Button("Summarize", size="sm")
                with gr.Row():
                    run = gr.Button("Run task", variant="primary", elem_id="run-button", scale=2)
                    fresh = gr.Button("New workspace", elem_id="new-workspace", scale=1)
                with gr.Accordion("Settings", open=False):
                    mode = gr.Dropdown(modes, value="Model planner" if model_allowed else "Offline demo", label="Execution mode", interactive=True)
            with gr.Column(scale=5, min_width=320, elem_id="result-panel"):
                status = gr.HTML(status_card())
                with gr.Row():
                    approve = gr.Button("Approve & continue", variant="primary", visible=False)
                    reject = gr.Button("Decline", visible=False)
        with gr.Tabs(elem_id="workspace-tabs"):
            with gr.Tab("Invoices"):
                summary = gr.HTML('<div id="workspace-summary"><span><strong>0</strong> saved invoices</span><span>USD ledger</span></div>')
                ledger = gr.Dataframe(headers=["Invoice", "Vendor", "Amount", "Currency", "Due date"],
                    datatype=["str"] * 5, interactive=False, wrap=True, label="Saved invoices", show_label=False)
            with gr.Tab("Activity"):
                activity = gr.HTML(activity_view(), elem_id="activity")
            with gr.Tab("Browser"):
                screenshot = gr.Image(label="Browser view", type="filepath", interactive=False)
        outputs = [state, status, activity, ledger, screenshot, approve, reject, summary, run, fresh, mode]
        run.click(start, [task, mode, state], outputs, concurrency_limit=1, concurrency_id="worker")
        approve.click(resume, [state], outputs, concurrency_limit=1, concurrency_id="worker")
        reject.click(decline, [state], outputs, concurrency_limit=1, concurrency_id="worker")
        fresh.click(lambda: present(None), [], outputs, concurrency_limit=1, concurrency_id="worker")
        latest.click(lambda: "Record the latest invoice from Company X.", outputs=task, queue=False)
        batch.click(lambda: "Record all invoices from Company X.", outputs=task, queue=False)
        report.click(lambda: "Summarize all invoices from Acme Supplies.", outputs=task, queue=False)
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
            theme=gr.themes.Soft(primary_hue="emerald", neutral_hue="slate"), css=CSS,
            allowed_paths=[str(ROOT / "artifacts" / "runs")])
    finally:
        server.should_exit = True

if __name__ == "__main__":
    main()
