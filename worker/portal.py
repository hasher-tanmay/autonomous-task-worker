"""The simulated company portal. The worker reads and writes through its UI."""
import html
from datetime import date
from decimal import Decimal, InvalidOperation
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .store import SEED, Store

STYLE = """
body{font:16px system-ui;margin:0;background:#f5f6fa;color:#17233b}
header{background:#14243c;color:white;padding:22px 6%}main{max-width:1050px;margin:32px auto;padding:0 24px}
a{color:#2864cf}nav{display:flex;gap:24px;margin:25px 0}.card{background:white;border:1px solid #dce2ee;border-radius:14px;padding:28px;margin:20px 0}
table{border-collapse:collapse;width:100%}td,th{padding:14px 10px;text-align:left;border-bottom:1px solid #e2e8f0}
label{display:block;margin:14px 0}input{display:block;padding:11px;width:90%;border:1px solid #bdc9dc;border-radius:6px}
button{background:#2864cf;color:white;border:0;border-radius:6px;padding:12px 20px;cursor:pointer}
#notice{padding:14px;background:#edf3ff;margin-top:18px}.tag{font-size:12px;background:#d7ecf9;padding:5px 10px;border-radius:20px}
"""

def esc(value):
    return html.escape(str(value), quote=True)

def page(sid, body):
    return HTMLResponse(f"""<!doctype html><html><head><title>Harbor | Company sandbox</title><style>{STYLE}</style></head>
    <body><header><b>HARBOR</b> &nbsp; Company portal &nbsp; <span class="tag" style="color:#14243c">Synthetic data only</span></header>
    <main><nav><a href="/company/{sid}/inbox">Invoice inbox</a><a href="/company/{sid}/ledger">Internal ledger</a></nav>{body}</main></body></html>""")

class Record(BaseModel):
    id: str
    vendor: str
    amount: str
    currency: str
    due: str

def register_portal(app: FastAPI, store: Store):
    def require(sid):
        if not store.exists(sid):
            raise HTTPException(404, "Sandbox not found")

    @app.get("/company/{sid}/inbox", response_class=HTMLResponse)
    def inbox(sid: str):
        require(sid)
        rows = "".join(f'<tr data-invoice="{r["id"]}"><td><a href="/company/{sid}/invoice/{r["id"]}">{r["id"]}</a></td><td>{esc(r["vendor"])}</td><td>{r["issued"]}</td></tr>' for r in SEED)
        return page(sid, f'<h1>Invoice inbox</h1><p>Find source documents before entering a record.</p><div class="card"><table><thead><tr><th>Invoice</th><th>Vendor</th><th>Issued</th></tr></thead><tbody>{rows}</tbody></table></div>')

    @app.get("/company/{sid}/invoice/{invoice_id}", response_class=HTMLResponse)
    def invoice(sid: str, invoice_id: str):
        require(sid)
        r = next((x for x in SEED if x["id"] == invoice_id), None)
        if not r:
            raise HTTPException(404, "Invoice not found")
        fields = "".join(f'<p><b>{esc(k.title())}:</b> <span data-field="{k}">{esc(v)}</span></p>' for k,v in r.items())
        return page(sid, f'<h1>Source invoice</h1><div class="card">{fields}</div>')

    @app.get("/company/{sid}/ledger", response_class=HTMLResponse)
    def ledger(sid: str):
        require(sid)
        keys = ("id", "vendor", "amount", "currency", "due")
        rows = "".join('<tr data-record="'+esc(r["id"])+'">'+"".join(f'<td data-field="{k}">{esc(r[k])}</td>' for k in keys)+'</tr>' for r in store.list_records(sid))
        inputs = "".join(f'<label>{k.title()}<input id="{k}" name="{k}" required></label>' for k in keys)
        script = """<script>
        document.getElementById('entry').onsubmit=async e=>{
          e.preventDefault(); const data=Object.fromEntries(new FormData(e.target));
          const notice=document.getElementById('notice');
          try{ const res=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
          const result=await res.json(); notice.textContent=result.ok?'Saved. Reload the ledger to verify.':result.error||'Save rejected';
          notice.dataset.done='true'; }catch(err){notice.textContent='Network error: save outcome unknown';notice.dataset.done='true';}
        };</script>"""
        return page(sid, f'<h1>Internal ledger</h1><p>Records persist in SQLite. Duplicate invoice IDs are not inserted twice.</p><div class="card"><table><thead><tr>{"".join(f"<th>{k.title()}</th>" for k in keys)}</tr></thead><tbody>{rows}</tbody></table></div><div class="card"><h2>Enter invoice</h2><form id="entry">{inputs}<button type="submit">Save invoice</button></form><div id="notice" role="status">Ready</div></div>{script}')

    @app.post("/company/{sid}/ledger")
    def save(sid: str, record: Record):
        require(sid)
        source = next((r for r in SEED if r["id"] == record.id), None)
        if not source:
            return {"ok": False, "error": "Unknown invoice ID"}
        try:
            if Decimal(record.amount) <= 0 or not Decimal(record.amount).is_finite():
                raise ValueError("Invalid amount")
            date.fromisoformat(record.due)
        except (InvalidOperation, ValueError):
            return {"ok": False, "error": "Valid amount and due date required"}
        if any(getattr(record, k) != source[k] for k in ("vendor", "amount", "currency", "due")):
            return {"ok": False, "error": "Fields do not match the source invoice"}
        return store.save(sid, record.model_dump())
