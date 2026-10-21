"""SQLite history + CSV/HTML report export for the health layer."""
from __future__ import annotations
import html
import io
import json
import sqlite3
import time
import pandas as pd

SCHEMA = """CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, session TEXT, source TEXT, stream TEXT,
 window INTEGER, state TEXT, mode TEXT, evidence REAL, predicted TEXT,
 p_healthy REAL, p_outer REAL, p_inner REAL, w_vib REAL, w_cur REAL,
 vib_reliable INTEGER, cur_reliable INTEGER, injected TEXT, reasons TEXT, advice TEXT);
CREATE TABLE IF NOT EXISTS actions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, session TEXT, action TEXT, note TEXT);"""


class Store:
    def __init__(self, path):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.executescript(SCHEMA)

    def log(self, **r):
        r.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
        if isinstance(r.get("reasons"), (list, tuple)):
            r["reasons"] = json.dumps(r["reasons"])
        cols = ",".join(r)
        self.con.execute(f"INSERT INTO events({cols}) VALUES({','.join('?' * len(r))})",
                         list(r.values()))
        self.con.commit()

    def action(self, session, action, note=""):
        self.con.execute("INSERT INTO actions(ts,session,action,note) VALUES(?,?,?,?)",
                         (time.strftime("%Y-%m-%d %H:%M:%S"), session, action, note))
        self.con.commit()

    def events(self, session=None):
        q = "SELECT * FROM events" + (" WHERE session=?" if session else "") + " ORDER BY id"
        return pd.read_sql_query(q, self.con, params=(session,) if session else ())

    def actions(self, session=None):
        q = "SELECT * FROM actions" + (" WHERE session=?" if session else "") + " ORDER BY id"
        return pd.read_sql_query(q, self.con, params=(session,) if session else ())


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def html_report(ev: pd.DataFrame, acts: pd.DataFrame, title: str, provenance: str) -> str:
    counts = ev["state"].value_counts().to_dict() if len(ev) else {}
    first = {s: (int(ev[ev.state == s].window.iloc[0]) if (ev.state == s).any() else None)
             for s in ("WARNING", "INSPECT", "SENSOR_FAULT")} if len(ev) else {}
    last = ev.iloc[-1] if len(ev) else None
    reasons = ""
    if last is not None and last.reasons:
        try:
            rs = json.loads(last.reasons)
            reasons = "".join(f"<li>{html.escape(r[1])} (contribution {r[2]:+.2f})</li>" for r in rs)
        except Exception:
            reasons = ""
    tbl = ev[["window", "state", "mode", "evidence", "predicted", "w_vib", "w_cur", "injected"]] \
        .tail(60).to_html(index=False, float_format=lambda v: f"{v:.3f}", border=0) if len(ev) else ""
    act = acts.to_html(index=False, border=0) if len(acts) else "<p>No operator actions.</p>"
    css = ("body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#1b1b1b}"
           "table{border-collapse:collapse;font-size:12px}td,th{padding:4px 8px;border-bottom:1px solid #ddd}"
           ".k{display:inline-block;margin-right:18px;padding:8px 12px;background:#f3f5f8;border-radius:6px}"
           ".prov{font-size:12px;color:#555;border-left:3px solid #2a78d6;padding-left:8px}")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{css}</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="prov">{html.escape(provenance)}<br>Generated {time.strftime('%Y-%m-%d %H:%M:%S')}.
Advisory only - the system never controls the machine.</p>
<h2>Summary</h2>
<div class="k">Windows analysed: <b>{len(ev)}</b></div>
<div class="k">Final state: <b>{html.escape(str(last.state)) if last is not None else '-'}</b></div>
<div class="k">Windows per state: <b>{html.escape(json.dumps(counts))}</b></div>
<div class="k">First WARNING / INSPECT / SENSOR_FAULT at window: <b>{first.get('WARNING')} / {first.get('INSPECT')} / {first.get('SENSOR_FAULT')}</b></div>
<h2>Latest assessment</h2>
<p>Predicted: <b>{html.escape(str(last.predicted)) if last is not None else '-'}</b>;
evidence {last.evidence:.3f}; mode: {html.escape(str(last['mode'])) if last is not None else '-'}</p>
<p>Advice: {html.escape(str(last.advice)) if last is not None else '-'}</p>
<ul>{reasons}</ul>
<h2>Operator actions</h2>{act}
<h2>History (last 60 windows)</h2>{tbl}
</body></html>"""
