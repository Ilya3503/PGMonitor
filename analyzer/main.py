import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape

import psycopg2
from fastapi import FastAPI
from fastapi.responses import Response, HTMLResponse, JSONResponse

import config
import checks
import exporter


class State:
    lock = threading.Lock()
    recommendations: list[dict] = []
    last_run_at: datetime | None = None
    last_run_duration_sec: float = 0.0
    last_run_errors: list[str] = []
    is_running: bool = False


def _connect():
    conn = psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        connect_timeout=10,
    )
    # Don't let a runaway monitoring query hang the connection.
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {config.STATEMENT_TIMEOUT_MS}")
    conn.commit()
    return conn


def run_analysis() -> dict:
    if State.is_running:
        return {"status": "skipped", "reason": "analysis already in progress"}

    State.is_running = True
    started = time.time()
    started_dt = datetime.now(timezone.utc)
    recs: list = []
    errors: list[str] = []

    try:
        conn = _connect()
        try:
            results, errors = checks.run_all_checks(conn)
            recs = [r.to_dict() for r in results]
        finally:
            conn.close()
    except Exception as e:
        errors.append(f"connection: {e}")
        traceback.print_exc()

    duration = time.time() - started

    with State.lock:
        State.recommendations = recs
        State.last_run_at = started_dt
        State.last_run_duration_sec = duration
        State.last_run_errors = errors

    exporter.update_metrics(
        recommendations=recs,
        last_run_ts=started,
        last_run_duration=duration,
        errors=len(errors),
    )

    State.is_running = False
    print(
        f"[advisor] cycle done in {duration:.2f}s — "
        f"{len(recs)} recommendations, {len(errors)} errors"
    )
    return {
        "status": "ok",
        "duration_sec": round(duration, 2),
        "recommendations": len(recs),
        "errors": errors,
    }


# ── Scheduler ────────────────────────────────────────────────────────────────

def scheduler_loop():
    """Run immediately, then sleep & repeat."""
    while True:
        try:
            run_analysis()
        except Exception:
            traceback.print_exc()
        time.sleep(config.ANALYSIS_INTERVAL_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="pg-advisor", lifespan=lifespan)


# ── API ──────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "last_run_at": State.last_run_at.isoformat() if State.last_run_at else None,
        "recommendations": len(State.recommendations),
        "errors": State.last_run_errors,
    }


@app.get("/recommendations")
def recommendations():
    with State.lock:
        return JSONResponse({
            "generated_at": State.last_run_at.isoformat() if State.last_run_at else None,
            "duration_sec": round(State.last_run_duration_sec, 2),
            "errors": State.last_run_errors,
            "count": len(State.recommendations),
            "items": list(State.recommendations),
        })


@app.post("/recompute")
def recompute():
    # Run synchronously so the caller sees the fresh result on next page load.
    result = run_analysis()
    return result


@app.get("/metrics")
def metrics():
    data, content_type = exporter.metrics_output()
    return Response(content=data, media_type=content_type)


# ── HTML UI ──────────────────────────────────────────────────────────────────

SEVERITY_COLOR = {"critical": "#e74c3c", "warning": "#f39c12", "info": "#3498db"}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
CATEGORY_ICON = {"index": "📊", "bloat": "🗑️", "query": "🐢", "config": "⚙️"}


@app.get("/", response_class=HTMLResponse)
def ui():
    with State.lock:
        recs = sorted(
            State.recommendations,
            key=lambda r: (SEVERITY_ORDER.get(r["severity"], 99), r["category"]),
        )
        last_run = State.last_run_at
        duration = State.last_run_duration_sec
        errors = State.last_run_errors

    by_severity = {"critical": 0, "warning": 0, "info": 0}
    by_category = {"index": 0, "bloat": 0, "query": 0, "config": 0}
    for r in recs:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1

    cards = ""
    for r in recs:
        sev = r["severity"]
        cat = r["category"]
        sev_color = SEVERITY_COLOR.get(sev, "#999")
        icon = CATEGORY_ICON.get(cat, "•")
        sql_block = ""
        if r.get("sql"):
            sql_id = f"sql-{abs(hash(r['title']))}"
            sql_block = f"""
            <div class="sql-wrap">
              <div class="sql-header">
                <span class="sql-label">SQL</span>
                <button class="copy-btn" onclick="copySql('{sql_id}', this)">Copy</button>
              </div>
              <pre id="{sql_id}">{escape(r['sql'])}</pre>
            </div>"""
        cards += f"""
        <article class="rec">
          <header>
            <span class="sev" style="background:{sev_color}">{sev.upper()}</span>
            <span class="cat">{icon} {cat}</span>
            <h2>{escape(r['title'])}</h2>
          </header>
          <p class="desc">{escape(r['description']).replace(chr(10), '<br>')}</p>
          <p class="action"><strong>Action:</strong> {escape(r['action'])}</p>
          {sql_block}
        </article>"""

    last_run_str = last_run.strftime("%Y-%m-%d %H:%M:%S UTC") if last_run else "never"
    err_banner = ""
    if errors:
        err_list = "".join(f"<li>{escape(e)}</li>" for e in errors)
        err_banner = f"""<div class="errors">
            <strong>Analysis errors:</strong>
            <ul>{err_list}</ul>
        </div>"""

    empty_state = ""
    if not recs and not errors:
        empty_state = """<div class="empty">
            ✅ No issues detected. Your database is healthy.
        </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>pg-advisor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
      background: #0f1419; color: #d6deeb;
      margin: 0; padding: 24px; max-width: 1100px; margin: 0 auto;
    }}
    h1 {{ color: #82aaff; margin: 0 0 4px; }}
    .meta {{ color: #7e8a99; font-size: 14px; margin-bottom: 16px; }}
    .toolbar {{
      display: flex; gap: 12px; align-items: center;
      margin-bottom: 24px; flex-wrap: wrap;
    }}
    .recompute {{
      background: #82aaff; color: #0f1419; border: 0;
      padding: 10px 18px; font-weight: 600; font-size: 14px;
      border-radius: 6px; cursor: pointer;
    }}
    .recompute:hover {{ background: #a3c2ff; }}
    .recompute:disabled {{ opacity: 0.5; cursor: wait; }}
    .stats {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .stat {{
      background: #1d2733; padding: 8px 14px; border-radius: 6px;
      font-size: 13px;
    }}
    .stat b {{ color: #82aaff; font-size: 15px; margin-left: 4px; }}
    .errors {{
      background: #3a1d1d; border-left: 4px solid #e74c3c;
      padding: 12px 16px; margin-bottom: 16px; border-radius: 4px;
    }}
    .errors ul {{ margin: 6px 0 0 20px; padding: 0; }}
    .empty {{
      background: #1d3324; padding: 32px; text-align: center;
      border-radius: 8px; font-size: 18px; color: #2ecc71;
    }}
    .rec {{
      background: #1d2733; border-radius: 8px; padding: 18px 20px;
      margin-bottom: 14px; border-left: 4px solid #444;
    }}
    .rec header {{
      display: flex; align-items: center; gap: 10px;
      flex-wrap: wrap; margin-bottom: 10px;
    }}
    .rec h2 {{ font-size: 16px; margin: 0; flex: 1; min-width: 200px; color: #d6deeb; }}
    .sev {{
      color: white; padding: 3px 10px; border-radius: 3px;
      font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
    }}
    .cat {{ color: #7e8a99; font-size: 12px; }}
    .desc {{ color: #c5cdd9; margin: 8px 0; line-height: 1.5; font-size: 14px; }}
    .action {{ color: #ffcb6b; margin: 8px 0; font-size: 14px; line-height: 1.5; }}
    .sql-wrap {{ margin-top: 10px; }}
    .sql-header {{
      display: flex; justify-content: space-between; align-items: center;
      background: #0d1117; padding: 6px 12px;
      border-radius: 4px 4px 0 0; border-bottom: 1px solid #2a3340;
    }}
    .sql-label {{ color: #7e8a99; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
    .copy-btn {{
      background: #2a3340; color: #82aaff; border: 0;
      padding: 4px 12px; font-size: 12px; cursor: pointer; border-radius: 3px;
    }}
    .copy-btn:hover {{ background: #3a4350; }}
    .copy-btn.copied {{ background: #1d3324; color: #2ecc71; }}
    pre {{
      background: #0d1117; padding: 12px 14px; border-radius: 0 0 4px 4px;
      overflow-x: auto; margin: 0; font-size: 13px; line-height: 1.45;
      color: #c5cdd9; font-family: "JetBrains Mono", monospace;
    }}
  </style>
</head>
<body>
  <h1>pg-advisor</h1>
  <div class="meta">
    Database: <b>{escape(config.DB_NAME)}</b> @ {escape(config.DB_HOST)}:{config.DB_PORT}
    &nbsp;·&nbsp; Last run: <b>{last_run_str}</b>
    &nbsp;·&nbsp; Duration: <b>{duration:.2f}s</b>
    &nbsp;·&nbsp; Auto-refresh every {config.ANALYSIS_INTERVAL_SEC}s
  </div>

  <div class="toolbar">
    <button class="recompute" onclick="recompute(this)">↻ Recompute now</button>
    <div class="stats">
      <span class="stat">Total <b>{len(recs)}</b></span>
      <span class="stat" style="color:#e74c3c">Critical <b>{by_severity['critical']}</b></span>
      <span class="stat" style="color:#f39c12">Warning <b>{by_severity['warning']}</b></span>
      <span class="stat" style="color:#3498db">Info <b>{by_severity['info']}</b></span>
      <span class="stat">Indexes <b>{by_category['index']}</b></span>
      <span class="stat">Bloat <b>{by_category['bloat']}</b></span>
      <span class="stat">Queries <b>{by_category['query']}</b></span>
      <span class="stat">Config <b>{by_category['config']}</b></span>
    </div>
  </div>

  {err_banner}
  {empty_state}
  {cards}

  <script>
    async function recompute(btn) {{
      btn.disabled = true;
      btn.textContent = '⏳ Running analysis...';
      try {{
        const r = await fetch('/recompute', {{method: 'POST'}});
        await r.json();
      }} catch (e) {{
        alert('Recompute failed: ' + e);
      }}
      location.reload();
    }}
    async function copySql(id, btn) {{
      const text = document.getElementById(id).textContent;
      await navigator.clipboard.writeText(text);
      btn.textContent = '✓ Copied';
      btn.classList.add('copied');
      setTimeout(() => {{
        btn.textContent = 'Copy';
        btn.classList.remove('copied');
      }}, 1500);
    }}
  </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=config.ADVISOR_PORT, reload=False)
