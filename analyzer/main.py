import threading
import time
import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, HTMLResponse
from pydantic import BaseModel

import config
import storage
import analyzer
import exporter

os.makedirs("/app/data", exist_ok=True)
storage.init_db()


# ── Scheduler ─────────────────────────────────────────────────────────────────

def analysis_loop():
    """Run analysis immediately, then repeat every ANALYSIS_INTERVAL_SEC."""
    while True:
        print(f"[advisor] Running analysis at {datetime.utcnow().isoformat()}")
        recs = analyzer.run_analysis()
        if recs:
            storage.upsert_recommendations(recs)
            print(f"[advisor] {len(recs)} recommendations generated")
        open_recs = storage.get_recommendations(status="open")
        exporter.update_metrics(open_recs)
        print(f"[advisor] {len(open_recs)} open recommendations exported to Prometheus")
        time.sleep(config.ANALYSIS_INTERVAL_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=analysis_loop, daemon=True)
    t.start()
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="pg-advisor", lifespan=lifespan)


# ── Prometheus endpoint ───────────────────────────────────────────────────────

@app.get("/metrics")
def metrics():
    data, content_type = exporter.metrics_output()
    return Response(content=data, media_type=content_type)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/recommendations")
def list_recommendations(status: str = None):
    """
    GET /recommendations          — all recommendations
    GET /recommendations?status=open
    GET /recommendations?status=dismissed
    GET /recommendations?status=resolved
    """
    return storage.get_recommendations(status=status)


class StatusUpdate(BaseModel):
    status: str  # open | dismissed | resolved


@app.patch("/recommendations/{rec_id}")
def update_recommendation(rec_id: int, body: StatusUpdate):
    allowed = {"open", "dismissed", "resolved"}
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")
    ok = storage.update_status(rec_id, body.status)
    if not ok:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return {"id": rec_id, "status": body.status}


# ── Simple HTML UI ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def ui():
    recs = storage.get_recommendations()

    SEVERITY_COLOR = {
        "critical": "#e74c3c",
        "warning":  "#f39c12",
        "info":     "#3498db",
    }
    STATUS_COLOR = {
        "open":      "#e74c3c",
        "dismissed": "#95a5a6",
        "resolved":  "#2ecc71",
    }

    rows = ""
    for r in recs:
        sql_block = f"<pre>{r['sql']}</pre>" if r["sql"] else ""
        sev_color = SEVERITY_COLOR.get(r["severity"], "#999")
        sta_color = STATUS_COLOR.get(r["status"], "#999")
        rows += f"""
        <tr>
          <td>{r['id']}</td>
          <td style="color:{sev_color};font-weight:bold">{r['severity']}</td>
          <td>{r['category']}</td>
          <td><b>{r['title']}</b><br>
              <small>{r['description']}</small><br>
              <em>{r['action']}</em>
              {sql_block}
          </td>
          <td style="color:{sta_color};font-weight:bold">{r['status']}</td>
          <td>{r['created_at'][:16]}</td>
          <td>
            <button onclick="setStatus({r['id']},'resolved')">✓ Resolved</button>
            <button onclick="setStatus({r['id']},'dismissed')">✗ Dismiss</button>
            <button onclick="setStatus({r['id']},'open')">↺ Reopen</button>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <title>pg-advisor</title>
  <meta charset="utf-8">
  <style>
    body {{ font-family: monospace; background: #1a1a2e; color: #eee; padding: 20px; }}
    h1   {{ color: #4fc3f7; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th   {{ background: #16213e; padding: 8px; text-align: left; }}
    td   {{ border-bottom: 1px solid #333; padding: 8px; vertical-align: top; }}
    pre  {{ background: #0d1117; padding: 8px; border-radius: 4px;
             overflow-x: auto; font-size: 12px; }}
    button {{ margin: 2px; padding: 4px 8px; cursor: pointer;
               background: #16213e; color: #eee; border: 1px solid #444;
               border-radius: 4px; }}
    button:hover {{ background: #0f3460; }}
  </style>
</head>
<body>
  <h1>pg-advisor — PostgreSQL Recommendations</h1>
  <p>Analysis interval: {config.ANALYSIS_INTERVAL_SEC}s &nbsp;|&nbsp;
     Database: {config.DB_NAME}@{config.DB_HOST}</p>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Severity</th><th>Category</th>
        <th>Details</th><th>Status</th><th>Created</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <script>
    async function setStatus(id, status) {{
      await fetch('/recommendations/' + id, {{
        method: 'PATCH',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{status}})
      }});
      location.reload();
    }}
  </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=config.ADVISOR_PORT, reload=False)
