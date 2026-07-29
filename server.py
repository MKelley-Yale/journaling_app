"""Personal journaling app — FastAPI backend + static PWA frontend.

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
Then expose over Tailscale:  tailscale serve https / http://localhost:8000
"""
import os
import json
import random
import secrets
import hashlib
from datetime import datetime, timezone, timedelta

from typing import List

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature
from apscheduler.schedulers.background import BackgroundScheduler

import db
from db import get_conn, now_iso
import seed_data
from keys import ensure_vapid_keys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
# Personal data (journal.db, photos/) lives in the PARENT folder, not in journal-app/.
# Keep this in sync with DATA_DIR in db.py.
DATA_DIR = os.environ.get("JOURNAL_DATA_DIR", os.path.dirname(HERE))
PHOTOS_DIR = os.environ.get("JOURNAL_PHOTOS_DIR", os.path.join(DATA_DIR, "photos"))
os.makedirs(PHOTOS_DIR, exist_ok=True)
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif"}


# --- tiny .env loader (no extra dependency) ---------------------------------
def load_env():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


load_env()
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="journal-session")
COOKIE = "journal_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

VAPID_PUBLIC, VAPID_PRIVATE_PEM = ensure_vapid_keys()
VAPID_CONTACT = os.environ.get("VAPID_CONTACT", "mailto:you@example.com")

app = FastAPI(title="Journal")


# --- auth helpers -----------------------------------------------------------
def hash_pin(pin: str) -> str:
    salt = "journal-pin-v1"
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()


def is_authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    try:
        serializer.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except BadSignature:
        return False
    except Exception:
        return False


def require_auth(request: Request):
    # If no PIN has been set yet, allow through so the user can set one.
    if not db.get_setting("pin_hash"):
        return
    if not is_authed(request):
        raise HTTPException(status_code=401, detail="locked")


# --- weather ----------------------------------------------------------------
WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "snow showers", 95: "thunderstorm",
    96: "thunderstorm w/ hail", 99: "thunderstorm w/ hail",
}


async def fetch_weather(lat, lon):
    try:
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               "&current=temperature_2m,weather_code&temperature_unit=fahrenheit&timezone=auto")
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url)
            r.raise_for_status()
            cur = r.json().get("current", {})
            code = cur.get("weather_code")
            temp = cur.get("temperature_2m")
            desc = WEATHER_CODES.get(code, "")
            parts = []
            if desc:
                parts.append(desc)
            if temp is not None:
                parts.append(f"{round(temp)}°F")
            return ", ".join(parts) or None
    except Exception:
        return None


# --- AI ("go deeper") -------------------------------------------------------
async def ai_followup(question_text: str, answer_text: str) -> str:
    sys = ("You are a journaling companion. Given a journaling prompt and the person's "
           "answer, write ONE short, open follow-up question that invites them to go a "
           "layer deeper. Be warm and specific to what they wrote. Output only the question.")
    user = f"Prompt: {question_text}\n\nTheir answer: {answer_text}\n\nOne follow-up question:"

    anth = os.environ.get("ANTHROPIC_API_KEY")
    openai = os.environ.get("OPENAI_API_KEY")
    try:
        if anth:
            model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anth, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": model, "max_tokens": 120, "system": sys,
                          "messages": [{"role": "user", "content": user}]},
                )
                r.raise_for_status()
                return r.json()["content"][0]["text"].strip()
        if openai:
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai}",
                             "content-type": "application/json"},
                    json={"model": model, "max_tokens": 120,
                          "messages": [{"role": "system", "content": sys},
                                       {"role": "user", "content": user}]},
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    # rule-based fallback (no text leaves the machine)
    templates = [
        "What's underneath that? Try to say the part you usually leave out.",
        "If you sat with this a little longer, what else is true about it?",
        "What would change if you took this thought one step further?",
        "Why do you think this is on your mind right now?",
        "What's the most honest thing you could add to what you just wrote?",
    ]
    return random.choice(templates)


# --- push -------------------------------------------------------------------
def send_push(title, body):
    from pywebpush import webpush, WebPushException
    conn = get_conn()
    subs = conn.execute("SELECT * FROM push_subscriptions").fetchall()
    payload = json.dumps({"title": title, "body": body, "url": "/"})
    for s in subs:
        try:
            webpush(
                subscription_info=json.loads(s["data"]),
                data=payload,
                vapid_private_key=VAPID_PRIVATE_PEM,
                vapid_claims={"sub": VAPID_CONTACT},
            )
        except WebPushException as e:
            # 404/410 -> subscription gone; remove it
            if e.response is not None and e.response.status_code in (404, 410):
                conn.execute("DELETE FROM push_subscriptions WHERE id=?", (s["id"],))
                conn.commit()
        except Exception:
            pass
    conn.close()


# --- reminder scheduling ----------------------------------------------------
def _isetting(key):
    return int(db.get_setting(key))


def random_time_in_window(day: datetime) -> datetime:
    start = _isetting("window_start_hour")
    end = _isetting("window_end_hour")
    hour = random.randint(start, max(start, end - 1))
    minute = random.randint(0, 59)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def ensure_future_primary():
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) c FROM reminders WHERE kind='primary' AND sent_at IS NULL "
        "AND scheduled_for > ?", (datetime.now().isoformat(),)
    ).fetchone()
    if row["c"] == 0:
        gap = random.randint(_isetting("cadence_min_days"), _isetting("cadence_max_days"))
        day = datetime.now() + timedelta(days=gap)
        when = random_time_in_window(day)
        conn.execute("INSERT INTO reminders(scheduled_for, kind) VALUES (?, 'primary')",
                     (when.isoformat(),))
        conn.commit()
    conn.close()


def engaged_today() -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) c FROM entries WHERE substr(created_at,1,10)=?",
                       (today,)).fetchone()
    conn.close()
    return row["c"] > 0


def mark_engaged_today():
    today = datetime.now().date().isoformat()
    conn = get_conn()
    conn.execute("UPDATE reminders SET engaged=1 WHERE substr(scheduled_for,1,10)=?", (today,))
    conn.commit()
    conn.close()


def tick():
    """Runs every minute: fire due reminders, keep the future scheduled."""
    try:
        now = datetime.now()
        conn = get_conn()
        due = conn.execute(
            "SELECT * FROM reminders WHERE sent_at IS NULL AND scheduled_for <= ? "
            "ORDER BY scheduled_for", (now.isoformat(),)
        ).fetchall()
        for r in due:
            if r["kind"] == "followup" and engaged_today():
                conn.execute("UPDATE reminders SET sent_at=?, engaged=1 WHERE id=?",
                             (now_iso(), r["id"]))
                conn.commit()
                continue
            morning = now.hour < _isetting("morning_cutoff_hour")
            body = ("A few minutes for yesterday?" if morning
                    else "Time to journal — a few minutes for today?")
            send_push("Journal", body)
            conn.execute("UPDATE reminders SET sent_at=? WHERE id=?", (now_iso(), r["id"]))
            conn.commit()
            if r["kind"] == "primary":
                # schedule one follow-up later today if there's room in the window
                end = _isetting("window_end_hour")
                fu = now + timedelta(hours=random.randint(4, 6))
                if fu.hour < end and fu.date() == now.date():
                    conn.execute("INSERT INTO reminders(scheduled_for, kind) VALUES (?, 'followup')",
                                 (fu.isoformat(),))
                    conn.commit()
        conn.close()
        ensure_future_primary()
    except Exception:
        pass


scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup():
    db.init_db()
    db.seed_if_empty()
    ensure_future_primary()
    scheduler.add_job(tick, "interval", minutes=1, id="tick", replace_existing=True)
    scheduler.start()


@app.on_event("shutdown")
def shutdown():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass


# ============================ ROUTES ========================================

# ---- static / shell ----
NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
def index():
    # Never cache the shell: it carries the ?v= asset versions that bust old JS/CSS.
    return FileResponse(os.path.join(STATIC, "index.html"), headers=NO_STORE)


@app.get("/sw.js")
def sw():
    return FileResponse(os.path.join(STATIC, "sw.js"),
                        media_type="application/javascript", headers=NO_STORE)


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(STATIC, "manifest.webmanifest"),
                        media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---- auth ----
@app.get("/api/status")
def status(request: Request):
    return {"has_pin": bool(db.get_setting("pin_hash")), "authed": is_authed(request),
            "vapid_public": VAPID_PUBLIC}


@app.post("/api/setup-pin")
async def setup_pin(request: Request):
    body = await request.json()
    pin = str(body.get("pin", ""))
    if len(pin) < 4:
        raise HTTPException(400, "PIN must be at least 4 digits")
    if db.get_setting("pin_hash"):
        raise HTTPException(400, "PIN already set")
    db.set_setting("pin_hash", hash_pin(pin))
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, serializer.dumps({"ok": True}), max_age=SESSION_MAX_AGE,
                    httponly=True, samesite="lax")
    return resp


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    pin = str(body.get("pin", ""))
    if hash_pin(pin) != db.get_setting("pin_hash"):
        raise HTTPException(401, "Wrong PIN")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, serializer.dumps({"ok": True}), max_age=SESSION_MAX_AGE,
                    httponly=True, samesite="lax")
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


# ---- collections ----
@app.get("/api/collections")
def list_collections(request: Request, _=Depends(require_auth)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT c.*, "
        "(SELECT COUNT(*) FROM prompts p WHERE p.collection_id=c.id AND p.active=1) AS prompt_count, "
        "(SELECT COUNT(*) FROM entries e WHERE e.collection_id=c.id) AS entry_count "
        "FROM collections c ORDER BY c.is_daily DESC, c.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/collections/{cid}")
def get_collection(cid: int, _=Depends(require_auth)):
    conn = get_conn()
    c = conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
    if not c:
        conn.close()
        raise HTTPException(404, "not found")
    prompts = conn.execute(
        "SELECT * FROM prompts WHERE collection_id=? ORDER BY id", (cid,)).fetchall()
    conn.close()
    return {"collection": dict(c), "prompts": [dict(p) for p in prompts]}


@app.post("/api/collections")
async def create_collection(request: Request, _=Depends(require_auth)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    desc = body.get("description", "")
    from_template = body.get("from_template_id")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO collections(name, description, kind, is_daily, created_at) "
        "VALUES (?, ?, 'themed', 0, ?)", (name, desc, now_iso()))
    cid = cur.lastrowid
    if from_template:
        tps = conn.execute("SELECT text, kind FROM prompts WHERE collection_id=?",
                           (from_template,)).fetchall()
        for t in tps:
            conn.execute("INSERT INTO prompts(collection_id, text, kind, source, created_at) "
                         "VALUES (?, ?, ?, 'builtin', ?)", (cid, t["text"], t["kind"], now_iso()))
    conn.commit()
    row = conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
    conn.close()
    return dict(row)


@app.post("/api/collections/{cid}/prompts")
async def add_prompt(cid: int, request: Request, _=Depends(require_auth)):
    body = await request.json()
    text = (body.get("text") or "").strip()
    kind = body.get("kind", "reflective")
    if not text:
        raise HTTPException(400, "text required")
    conn = get_conn()
    conn.execute("INSERT INTO prompts(collection_id, text, kind, source, created_at) "
                 "VALUES (?, ?, ?, 'user', ?)", (cid, text, kind, now_iso()))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---- sessions / prompt selection ----
def _daily_id():
    conn = get_conn()
    row = conn.execute("SELECT id FROM collections WHERE is_daily=1 LIMIT 1").fetchone()
    conn.close()
    return row["id"] if row else None


def _pick_from_db(cid, kind, n, exclude_ids):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, text, kind FROM prompts WHERE collection_id=? AND kind=? AND active=1",
        (cid, kind)).fetchall()
    conn.close()
    pool = [dict(r) for r in rows if r["id"] not in exclude_ids]
    random.shuffle(pool)
    return pool[:n]


def _pick_morning_factual(n, exclude_texts):
    pool = [{"id": None, "text": t, "kind": "factual"}
            for t in seed_data.DAILY_MORNING_FACTUAL if t not in exclude_texts]
    random.shuffle(pool)
    return pool[:n]


@app.post("/api/session/start")
async def session_start(request: Request, _=Depends(require_auth)):
    body = await request.json()
    cid = body.get("collection_id") or _daily_id()
    morning = bool(body.get("morning", False))
    size = _isetting("session_size")
    n_fact = size // 2
    n_refl = size - n_fact

    conn = get_conn()
    is_daily = conn.execute("SELECT is_daily FROM collections WHERE id=?", (cid,)).fetchone()
    conn.close()
    is_daily = is_daily and is_daily["is_daily"]

    if is_daily and morning:
        factual = _pick_morning_factual(n_fact, set())
    else:
        factual = _pick_from_db(cid, "factual", n_fact, set())
    reflective = _pick_from_db(cid, "reflective", n_refl, set())
    prompts = factual + reflective
    random.shuffle(prompts)
    return {"collection_id": cid, "morning": morning, "prompts": prompts}


@app.post("/api/session/more")
async def session_more(request: Request, _=Depends(require_auth)):
    body = await request.json()
    cid = body.get("collection_id") or _daily_id()
    kind = body.get("kind", "reflective")
    morning = bool(body.get("morning", False))
    exclude_ids = set(body.get("exclude_ids", []))
    exclude_texts = set(body.get("exclude_texts", []))
    conn = get_conn()
    is_daily = conn.execute("SELECT is_daily FROM collections WHERE id=?", (cid,)).fetchone()
    conn.close()
    is_daily = is_daily and is_daily["is_daily"]
    if kind == "factual" and is_daily and morning:
        prompts = _pick_morning_factual(2, exclude_texts)
    else:
        prompts = _pick_from_db(cid, kind, 2, exclude_ids)
    return {"prompts": prompts}


@app.post("/api/prompts/swap")
async def prompt_swap(request: Request, _=Depends(require_auth)):
    body = await request.json()
    cid = body.get("collection_id") or _daily_id()
    kind = body.get("kind", "reflective")
    morning = bool(body.get("morning", False))
    exclude_ids = set(body.get("exclude_ids", []))
    exclude_texts = set(body.get("exclude_texts", []))
    conn = get_conn()
    is_daily = conn.execute("SELECT is_daily FROM collections WHERE id=?", (cid,)).fetchone()
    conn.close()
    is_daily = is_daily and is_daily["is_daily"]
    if kind == "factual" and is_daily and morning:
        prompts = _pick_morning_factual(1, exclude_texts)
    else:
        prompts = _pick_from_db(cid, kind, 1, exclude_ids)
    return {"prompt": prompts[0] if prompts else None}


# ---- entries ----
@app.post("/api/entries")
async def create_entry(request: Request, _=Depends(require_auth)):
    body = await request.json()
    cid = body.get("collection_id")
    is_freewrite = 1 if body.get("is_freewrite") else 0
    lat, lon = body.get("lat"), body.get("lon")
    location = body.get("location")
    answers = body.get("answers", [])
    freewrite_text = (body.get("freewrite_text") or "").strip()

    weather = await fetch_weather(lat, lon) if (lat is not None and lon is not None) else None

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO entries(collection_id, created_at, weather, location, is_freewrite) "
        "VALUES (?, ?, ?, ?, ?)", (cid, now_iso(), weather, location, is_freewrite))
    eid = cur.lastrowid
    if is_freewrite and freewrite_text:
        conn.execute("INSERT INTO answers(entry_id, prompt_id, question_text, kind, answer_text, created_at) "
                     "VALUES (?, NULL, ?, NULL, ?, ?)", (eid, "(free write)", freewrite_text, now_iso()))
    for a in answers:
        txt = (a.get("answer_text") or "").strip()
        if not txt:
            continue
        conn.execute(
            "INSERT INTO answers(entry_id, prompt_id, question_text, kind, answer_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, a.get("prompt_id"), a.get("question_text", ""), a.get("kind"), txt, now_iso()))
    conn.commit()
    conn.close()
    mark_engaged_today()
    return {"id": eid, "weather": weather}


@app.get("/api/entries")
def list_entries(request: Request, q: str = "", collection_id: int = 0, date: str = "",
                 _=Depends(require_auth)):
    conn = get_conn()
    sql = ("SELECT e.id, e.created_at, e.weather, e.collection_id, e.is_freewrite, "
           "c.name AS collection_name, "
           "(SELECT COUNT(*) FROM answers a WHERE a.entry_id=e.id) AS answer_count, "
           "(SELECT COUNT(*) FROM photos p WHERE p.entry_id=e.id) AS photo_count, "
           "(SELECT answer_text FROM answers a WHERE a.entry_id=e.id ORDER BY a.id LIMIT 1) AS preview "
           "FROM entries e LEFT JOIN collections c ON c.id=e.collection_id ")
    where, params = [], []
    if collection_id:
        where.append("e.collection_id=?")
        params.append(collection_id)
    if q:
        where.append("e.id IN (SELECT entry_id FROM answers WHERE answer_text LIKE ? OR question_text LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if date:
        try:
            y, m, d = (int(x) for x in date.split("-"))
            start, end = _local_day_bounds_utc(y, m, d)
        except (ValueError, TypeError):
            raise HTTPException(400, "date must be YYYY-MM-DD")
        where.append("e.created_at >= ? AND e.created_at < ?")
        params += [start, end]
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY e.created_at DESC LIMIT 200"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- edit window ----
EDIT_WINDOW_HOURS = 48


def _parse_iso(s):
    """Parse an ISO timestamp; treat naive values as UTC."""
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def entry_edit_state(created_at):
    """Return (editable, seconds_left) for an entry's created_at timestamp."""
    dt = _parse_iso(created_at)
    if dt is None:
        return False, 0
    deadline = dt + timedelta(hours=EDIT_WINDOW_HOURS)
    left = (deadline - datetime.now(timezone.utc)).total_seconds()
    return left > 0, max(0, int(left))


def require_editable(conn, eid):
    """Raise unless the entry exists and is still inside the edit window."""
    row = conn.execute("SELECT created_at FROM entries WHERE id=?", (eid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "entry not found")
    editable, _left = entry_edit_state(row["created_at"])
    if not editable:
        conn.close()
        raise HTTPException(
            403, f"This entry is older than {EDIT_WINDOW_HOURS} hours and can no longer be changed")


# ---- calendar ----
def _local_day_bounds_utc(year, month, day):
    """UTC ISO bounds [start, end) for a local calendar day."""
    start_local = datetime(year, month, day).astimezone()
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc).isoformat(),
            end_local.astimezone(timezone.utc).isoformat())


@app.get("/api/calendar")
def calendar_month(year: int, month: int, _=Depends(require_auth)):
    """Per-day entry counts for a month, grouped by the user's local date."""
    if not (1 <= month <= 12):
        raise HTTPException(400, "bad month")
    start, _ = _local_day_bounds_utc(year, month, 1)
    nxt_y, nxt_m = (year + 1, 1) if month == 12 else (year, month + 1)
    end, _ = _local_day_bounds_utc(nxt_y, nxt_m, 1)

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, created_at FROM entries WHERE created_at >= ? AND created_at < ?",
        (start, end)).fetchall()
    conn.close()

    counts = {}
    for r in rows:
        dt = _parse_iso(r["created_at"])
        if dt is None:
            continue
        key = dt.astimezone().date().isoformat()  # local date
        counts[key] = counts.get(key, 0) + 1
    return {"year": year, "month": month, "days": counts}


@app.get("/api/entries/{eid}")
def get_entry(eid: int, _=Depends(require_auth)):
    conn = get_conn()
    e = conn.execute("SELECT e.*, c.name AS collection_name FROM entries e "
                     "LEFT JOIN collections c ON c.id=e.collection_id WHERE e.id=?", (eid,)).fetchone()
    if not e:
        conn.close()
        raise HTTPException(404, "not found")
    answers = conn.execute("SELECT * FROM answers WHERE entry_id=? ORDER BY id", (eid,)).fetchall()
    out_answers = []
    for a in answers:
        refls = conn.execute("SELECT * FROM reflections WHERE answer_id=? ORDER BY id",
                             (a["id"],)).fetchall()
        d = dict(a)
        d["reflections"] = [dict(r) for r in refls]
        out_answers.append(d)
    photos = conn.execute("SELECT * FROM photos WHERE entry_id=? ORDER BY id", (eid,)).fetchall()
    conn.close()
    editable, seconds_left = entry_edit_state(e["created_at"])
    return {"entry": dict(e), "answers": out_answers, "photos": [dict(p) for p in photos],
            "editable": editable, "edit_seconds_left": seconds_left,
            "edit_window_hours": EDIT_WINDOW_HOURS}


@app.put("/api/entries/{eid}")
async def update_entry(eid: int, request: Request, _=Depends(require_auth)):
    """Edit an entry's answers, within the 48-hour window.

    Body: {"answers": [{"id": 1, "answer_text": "..."}, ...],
           "new_answers": [{"question_text": "...", "kind": "...", "answer_text": "..."}]}
    An existing answer whose text is blanked out is removed.
    """
    body = await request.json()
    conn = get_conn()
    require_editable(conn, eid)
    for a in body.get("answers", []):
        aid = a.get("id")
        if aid is None:
            continue
        txt = (a.get("answer_text") or "").strip()
        owned = conn.execute("SELECT id FROM answers WHERE id=? AND entry_id=?",
                             (aid, eid)).fetchone()
        if not owned:
            continue
        if txt:
            conn.execute("UPDATE answers SET answer_text=? WHERE id=?", (txt, aid))
        else:
            conn.execute("DELETE FROM answers WHERE id=?", (aid,))
    for a in body.get("new_answers", []):
        txt = (a.get("answer_text") or "").strip()
        if not txt:
            continue
        conn.execute(
            "INSERT INTO answers(entry_id, prompt_id, question_text, kind, answer_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, a.get("prompt_id"), a.get("question_text", ""), a.get("kind"), txt, now_iso()))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/entries/{eid}")
def delete_entry(eid: int, _=Depends(require_auth)):
    """Delete an entry and its photos, within the 48-hour window."""
    conn = get_conn()
    require_editable(conn, eid)
    photos = conn.execute("SELECT filename FROM photos WHERE entry_id=?", (eid,)).fetchall()
    conn.execute("DELETE FROM entries WHERE id=?", (eid,))  # cascades to answers/photos
    conn.commit()
    conn.close()
    for p in photos:
        try:
            os.remove(os.path.join(PHOTOS_DIR, p["filename"]))
        except OSError:
            pass
    return {"ok": True}


# ---- photos ----
@app.post("/api/entries/{eid}/photos")
async def upload_photos(eid: int, files: List[UploadFile] = File(...), _=Depends(require_auth)):
    conn = get_conn()
    require_editable(conn, eid)
    saved = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_PHOTO_EXT:
            ext = ".jpg"
        fname = secrets.token_hex(16) + ext
        data = await f.read()
        if not data:
            continue
        with open(os.path.join(PHOTOS_DIR, fname), "wb") as out:
            out.write(data)
        cur = conn.execute(
            "INSERT INTO photos(entry_id, filename, created_at) VALUES (?, ?, ?)",
            (eid, fname, now_iso()))
        saved.append({"id": cur.lastrowid, "filename": fname})
    conn.commit()
    conn.close()
    return {"photos": saved}


@app.get("/api/photos/{filename}")
def get_photo(filename: str, _=Depends(require_auth)):
    safe = os.path.basename(filename)  # prevent path traversal
    path = os.path.join(PHOTOS_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.delete("/api/photos/{pid}")
def delete_photo(pid: int, _=Depends(require_auth)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "not found")
    require_editable(conn, row["entry_id"])
    conn.execute("DELETE FROM photos WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    try:
        os.remove(os.path.join(PHOTOS_DIR, row["filename"]))
    except OSError:
        pass
    return {"ok": True}


# ---- resurfacing / reflections ----
@app.get("/api/resurface")
def resurface(_=Depends(require_auth)):
    conn = get_conn()
    # prefer something from ~1 year ago (+/- 3 days)
    target = (datetime.now(timezone.utc) - timedelta(days=365))
    lo = (target - timedelta(days=3)).date().isoformat()
    hi = (target + timedelta(days=3)).date().isoformat()
    row = conn.execute(
        "SELECT a.*, e.created_at AS entry_date FROM answers a JOIN entries e ON e.id=a.entry_id "
        "WHERE substr(e.created_at,1,10) BETWEEN ? AND ? AND a.answer_text != '' "
        "ORDER BY RANDOM() LIMIT 1", (lo, hi)).fetchone()
    on_this_day = bool(row)
    if not row:
        row = conn.execute(
            "SELECT a.*, e.created_at AS entry_date FROM answers a JOIN entries e ON e.id=a.entry_id "
            "WHERE a.answer_text != '' AND e.created_at < ? ORDER BY RANDOM() LIMIT 1",
            ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),)).fetchone()
    conn.close()
    if not row:
        return {"answer": None}
    return {"answer": dict(row), "on_this_day": on_this_day}


@app.post("/api/reflections")
async def add_reflection(request: Request, _=Depends(require_auth)):
    body = await request.json()
    aid = body.get("answer_id")
    text = (body.get("text") or "").strip()
    if not aid or not text:
        raise HTTPException(400, "answer_id and text required")
    conn = get_conn()
    conn.execute("INSERT INTO reflections(answer_id, text, created_at) VALUES (?, ?, ?)",
                 (aid, text, now_iso()))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---- AI ----
@app.post("/api/ai/deeper")
async def ai_deeper(request: Request, _=Depends(require_auth)):
    body = await request.json()
    q = body.get("question_text", "")
    a = body.get("answer_text", "")
    if not a.strip():
        raise HTTPException(400, "nothing to go deeper on yet")
    followup = await ai_followup(q, a)
    return {"followup": followup}


# ---- push ----
@app.get("/api/push/key")
def push_key(_=Depends(require_auth)):
    return {"public_key": VAPID_PUBLIC}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request, _=Depends(require_auth)):
    body = await request.json()
    sub = body.get("subscription")
    if not sub or "endpoint" not in sub:
        raise HTTPException(400, "bad subscription")
    conn = get_conn()
    conn.execute(
        "INSERT INTO push_subscriptions(endpoint, data, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET data=excluded.data",
        (sub["endpoint"], json.dumps(sub), now_iso()))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/push/test")
def push_test(_=Depends(require_auth)):
    send_push("Journal", "This is a test reminder — tap to open.")
    return {"ok": True}


# ---- settings ----
SETTING_KEYS = ["cadence_min_days", "cadence_max_days", "window_start_hour",
                "window_end_hour", "morning_cutoff_hour", "session_size"]


@app.get("/api/settings")
def get_settings(_=Depends(require_auth)):
    return {k: db.get_setting(k) for k in SETTING_KEYS}


@app.put("/api/settings")
async def put_settings(request: Request, _=Depends(require_auth)):
    body = await request.json()
    for k in SETTING_KEYS:
        if k in body:
            db.set_setting(k, body[k])
    # reschedule next primary with new params
    conn = get_conn()
    conn.execute("DELETE FROM reminders WHERE kind='primary' AND sent_at IS NULL")
    conn.commit()
    conn.close()
    ensure_future_primary()
    return {k: db.get_setting(k) for k in SETTING_KEYS}


@app.get("/api/reminders/next")
def next_reminder(_=Depends(require_auth)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM reminders WHERE sent_at IS NULL ORDER BY scheduled_for LIMIT 1").fetchone()
    conn.close()
    return {"next": dict(row) if row else None}
