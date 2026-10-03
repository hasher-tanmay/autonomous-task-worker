"""Only this layer knows page selectors. No arbitrary URLs or JavaScript tools."""
from pathlib import Path
from playwright.sync_api import sync_playwright

class BrowserTools:
    def __init__(self, origin, sid, artifact_dir):
        self.root = origin.rstrip("/")+"/company/"+sid
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.shot = None

    def __enter__(self):
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(headless=True)
            self.context = self.browser.new_context(viewport={"width": 1180, "height": 820})
            self.page = self.context.new_page()
            self.page.set_default_timeout(6000)
            # Defense in depth: the executor browser never requests another origin.
            self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.root+"/") else route.abort())
            return self
        except Exception:
            self.runtime.stop()
            raise

    def __exit__(self, *args):
        try:
            self.context.close()
            self.browser.close()
        finally:
            self.runtime.stop()

    def screenshot(self, step):
        self.shot = str(self.artifact_dir / f"step-{step:02}.png")
        self.page.screenshot(path=self.shot, full_page=True)
        return self.shot

    def discover(self):
        self.page.goto(self.root+"/inbox")
        return self.page.locator("tr[data-invoice]").evaluate_all("rows => rows.map(r => ({id:r.dataset.invoice,vendor:r.cells[1].innerText,issued:r.cells[2].innerText}))")

    def read(self, iid):
        # Navigate via an observed link, not a model-supplied URL.
        self.page.goto(self.root+"/inbox")
        self.page.get_by_role("link", name=iid, exact=True).click()
        return self.page.locator("[data-field]").evaluate_all("els => Object.fromEntries(els.map(e => [e.dataset.field,e.innerText]))")

    def save(self, source):
        self.page.goto(self.root+"/ledger")
        for key in ("id", "vendor", "amount", "currency", "due"):
            self.page.get_by_label(key.title(), exact=True).fill(source[key])
        self.page.get_by_role("button", name="Save invoice").click()
        self.page.locator('#notice[data-done="true"]').wait_for()
        return {"notice": self.page.locator("#notice").inner_text()}

    def verify(self, iid):
        self.page.goto(self.root+"/ledger")
        rows = self.page.locator("tr[data-record]").evaluate_all("rows => rows.map(r => Object.fromEntries([...r.querySelectorAll('[data-field]')].map(e => [e.dataset.field,e.innerText])))")
        return next((r for r in rows if r["id"] == iid), None)
