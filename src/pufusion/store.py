"""Fault history: a local SQLite log plus CSV and HTML report export (stdlib only)."""
from __future__ import annotations

import csv
import html
import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (
  id INTEGER PRIMARY KEY, ts REAL, asset TEXT, source TEXT, state TEXT,
  p_fault REAL, fault_type TEXT, confidence REAL,
  rel_vib REAL, rel_cur REAL, w_vib REAL, w_cur REAL,
  readings TEXT, explanation TEXT, recommendations TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts REAL, asset TEXT, source TEXT,
  from_state TEXT, to_state TEXT, rule TEXT, recommendations TEXT);
CREATE INDEX IF NOT EXISTS ix_w ON windows(asset, ts);
"""
_COLS = ["ts", "asset", "source", "state", "p_fault", "fault_type", "confidence",
         "rel_vib", "rel_cur", "w_vib", "w_cur", "readings", "explanation", "recommendations"]


class HealthStore:
    def __init__(self, path: str | Path = "health.db"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(_SCHEMA)

    def log_window(self, rec: dict):
        row = [rec.get(c) for c in _COLS]
        row[0] = row[0] or time.time()
        for i, c in enumerate(_COLS):
            if c in ("readings", "explanation", "recommendations") and row[i] is not None:
                row[i] = json.dumps(row[i])
        self.db.execute(f"INSERT INTO windows ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})", row)
        self.db.commit()

    def log_event(self, asset, source, from_state, to_state, rule, recommendations, ts=None):
        self.db.execute("INSERT INTO events (ts,asset,source,from_state,to_state,rule,recommendations) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (ts or time.time(), asset, source, from_state, to_state, rule, json.dumps(recommendations)))
        self.db.commit()

    def history(self, asset=None, limit=500) -> list[dict]:
        q = f"SELECT {','.join(_COLS)} FROM windows" + (" WHERE asset=?" if asset else "") + " ORDER BY ts DESC LIMIT ?"
        rows = self.db.execute(q, (asset, limit) if asset else (limit,)).fetchall()
        return [dict(zip(_COLS, r)) for r in reversed(rows)]

    def events(self, asset=None) -> list[dict]:
        cols = ["ts", "asset", "source", "from_state", "to_state", "rule", "recommendations"]
        q = f"SELECT {','.join(cols)} FROM events" + (" WHERE asset=?" if asset else "") + " ORDER BY ts"
        return [dict(zip(cols, r)) for r in self.db.execute(q, (asset,) if asset else ()).fetchall()]

    def export_csv(self, path, asset=None):
        rows = self.history(asset, limit=10 ** 9)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_COLS)
            w.writeheader(); w.writerows(rows)
        return path

    def export_html(self, path, asset=None):
        rows, ev = self.history(asset, limit=10 ** 9), self.events(asset)
        sources = sorted({r["source"] for r in rows})
        counts = {}
        for r in rows:
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        fmt_t = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
        e = html.escape
        ev_rows = "".join(
            f"<tr><td>{fmt_t(x['ts'])}</td><td>{e(x['from_state'])} → <b>{e(x['to_state'])}</b></td>"
            f"<td>{e(x['rule'])}</td><td>{'<br>'.join(e(s) for s in json.loads(x['recommendations']))}</td></tr>"
            for x in ev)
        doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Health report</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:.4rem;text-align:left;vertical-align:top}}
.note{{background:#fff6e0;padding:.6rem;border-left:4px solid #e0a000}}</style></head><body>
<h1>Bearing health report{(' - ' + e(asset)) if asset else ''}</h1>
<p class="note">Data source: <b>{e(', '.join(sources) or 'none')}</b>. Benchmark replay results are validated on held-out
Paderborn bearings; rig results are valid only for the rig they were trained on; simulated data is for demonstration.
No remaining-useful-life estimate is made.</p>
<p>Windows logged: {len(rows)}{(' from ' + fmt_t(rows[0]['ts']) + ' to ' + fmt_t(rows[-1]['ts'])) if rows else ''}</p>
<h2>Time in each state (windows)</h2><p>{', '.join(f'{e(k)}: {v}' for k, v in sorted(counts.items())) or '-'}</p>
<h2>State changes</h2><table><tr><th>Time</th><th>Change</th><th>Rule</th><th>Recommendation</th></tr>{ev_rows or '<tr><td colspan=4>none</td></tr>'}</table>
</body></html>"""
        Path(path).write_text(doc, encoding="utf-8")
        return path
