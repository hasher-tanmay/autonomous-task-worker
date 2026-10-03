"""Record real UI outcomes, with captions mapping them to the criteria."""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

def clock(seconds):
    ms = int(seconds*1000)
    return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:7860")
    p.add_argument("--mode", choices=["offline", "model"], default="offline")
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    video_dir = root / "work" / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    chapters = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width":1280,"height":960},
            record_video_dir=str(video_dir), record_video_size={"width":1280,"height":960})
        page = context.new_page()
        started = time.monotonic()

        def chapter(title, caption):
            chapters.append(dict(seconds=round(time.monotonic()-started,2), title=title, caption=caption))
            print(title, flush=True)

        def choose(label, value):
            page.get_by_role("combobox", name=label, exact=True).click()
            page.get_by_role("option", name=value, exact=True).click()

        def tab(name):
            page.get_by_role("tab", name=name, exact=True).click()

        def run_task(task, scenario="No failure", expected="Completed"):
            choose("Reliability scenario", scenario)
            page.get_by_role("button", name="New sandbox", exact=True).click()
            tab("Execution trace")
            page.get_by_role("textbox", name="What should the worker accomplish?", exact=True).fill(task)
            page.wait_for_timeout(1200)
            page.get_by_role("button", name="Run task", exact=True).click()
            page.locator("#status h3").filter(has_text=re.compile(r"^(Completed|Failed|Needs Approval|Needs Clarification|Cancelled)$")).wait_for(timeout=240000)
            actual = page.locator("#status h3").inner_text()
            if actual != expected:
                raise RuntimeError(f"Demo outcome was {actual}, expected {expected}: " + page.locator("#status").inner_text())
            page.wait_for_timeout(2500)

        page.goto(args.url)
        page.get_by_role("button", name="Run task", exact=True).wait_for()
        choose("Planner", "Model planner" if args.mode == "model" else "Offline demo")
        chapter("Autonomy and execution", "A goal in plain English. The real model chooses actions; Chromium performs the work." if args.mode == "model" else "Offline baseline: rules choose actions; Chromium performs real browser work.")
        page.wait_for_timeout(2500)
        task = "Find the newest bill from Company X and register it in the internal ledger." if args.mode == "model" else "Record the latest invoice from Company X."
        run_task(task, "Save fails once")
        page.screenshot(path=str(docs / "app-preview.png"), full_page=True)
        chapter("Reliability: observe, then retry", "The first save failed. The worker checked the ledger, retried, and verified the exact fields.")
        page.get_by_text("Outcome verified. Evidence saved.", exact=True).filter(visible=True).first.scroll_into_view_if_needed()
        page.wait_for_timeout(6500)
        chapter("Verification: saved row and browser evidence", "The persisted record matches the source: X-101, USD 1,240.50, due 2026-10-31.")
        tab("Saved records")
        page.get_by_text("X-101", exact=True).filter(visible=True).first.wait_for()
        page.wait_for_timeout(4000)
        tab("Browser evidence")
        page.get_by_text("Latest worker browser screenshot", exact=True).scroll_into_view_if_needed()
        page.wait_for_timeout(4500)

        chapter("Generalization: a read-only task", "A different vendor and objective use the same engine. Reporting makes no ledger write.")
        run_task("Summarize all invoices from Acme Supplies.")
        page.wait_for_timeout(4000)
        tab("Saved records")
        page.wait_for_timeout(3000)

        chapter("Generalization: multiple documents", "The same worker records all Company X invoices instead of only the latest one.")
        run_task("Enter all invoices from Company X into the ledger.")
        tab("Saved records")
        for iid in ("X-100", "X-101"):
            page.get_by_text(iid, exact=True).filter(visible=True).first.wait_for()
        page.wait_for_timeout(4500)

        chapter("Product thinking: approval before a high-value write", "Northstar's USD 7,800 record requires a human decision. The worker pauses before writing.")
        run_task("Record the latest invoice from Northstar Labs.", expected="Needs Approval")
        page.wait_for_timeout(4500)
        page.get_by_role("button", name="Approve this record and continue", exact=True).click()
        page.get_by_role("heading", name="Completed", exact=True).wait_for(timeout=240000)
        page.wait_for_timeout(3500)

        chapter("Reliability: uncertain acknowledgement", "The save commits but its acknowledgement is lost. Checking the ledger prevents a duplicate.")
        run_task("Record the latest invoice from Company X.", "Save succeeds, acknowledgement lost")
        page.get_by_text("Outcome verified. Evidence saved.", exact=True).filter(visible=True).first.scroll_into_view_if_needed()
        page.wait_for_timeout(4500)

        chapter("Reliability: bounded failure", "A permanent outage stops after three save attempts. No false completion claim is made.")
        run_task("Record the latest invoice from Company X.", "Save always fails", "Failed")
        page.wait_for_timeout(4500)

        chapter("Verification: reject corrupted persistence", "A corrupted amount fails exact-field verification. The conflicting record needs manual review.")
        run_task("Record the latest invoice from Company X.", "Saved amount is corrupted", "Failed")
        page.wait_for_timeout(4000)

        chapter("Product thinking: ask instead of guessing", "A missing source due date stops the task. The worker does not invent a value.")
        run_task("Record the latest invoice from Broken Fields Ltd.", expected="Needs Clarification")
        page.wait_for_timeout(4000)

        chapter("Engineering quality and technical understanding", "A small planner, executor and verifier. Each component has one job; limitations are explicit.")
        tab("How it works")
        page.get_by_role("heading", name="A small loop with clear responsibilities", exact=True).scroll_into_view_if_needed()
        page.wait_for_timeout(9000)
        page.get_by_role("heading", name="Limits we can explain", exact=True).scroll_into_view_if_needed()
        page.wait_for_timeout(6500)
        chapter("Measured evaluation evidence", "Review real API and browser test results. These are observed results in a narrow sandbox, not a universal guarantee.")
        tab("Evaluation evidence")
        page.get_by_role("heading", name="Evaluation evidence", exact=True).scroll_into_view_if_needed()
        page.wait_for_timeout(9000)
        video = page.video
        context.close()
        path = video.path()
        browser.close()
    duration = time.monotonic()-started
    srt = []
    for i, item in enumerate(chapters):
        end = chapters[i+1]["seconds"] if i+1 < len(chapters) else duration
        srt.append(f"{i+1}\n{clock(item['seconds'])} --> {clock(end)}\n{item['title']}\n{item['caption']}\n")
    (docs / "demo-captions.srt").write_text("\n".join(srt), encoding="utf-8")
    (docs / "demo-chapters.json").write_text(json.dumps(dict(planner=args.mode, chapters=chapters), indent=2), encoding="utf-8")
    import imageio_ffmpeg
    # Relative subtitle path avoids Windows drive-letter escaping in filters.
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", path,
        "-vf", "pad=iw:ih+160:0:0:black,subtitles=demo-captions.srt:force_style='FontSize=9,Outline=1,MarginV=12'",
        "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(docs / "demo.mp4")],
        cwd=docs, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Video conversion failed: " + result.stderr[-1000:])
    print("Recorded actual UI: docs/demo.mp4 (planner: " + args.mode + ")", flush=True)

if __name__ == "__main__":
    main()
