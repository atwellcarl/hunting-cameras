"""Buck Book server: the swipe app, its API, and photo files, all local.

Crew members sign in with the shared crew passcode (BUCKBOOK_PASSCODE in .env)
plus their name. Signing in with an existing name continues as that person.

Usage: .venv/bin/python -m buckbook.server [--host 0.0.0.0] [--port 8765]
"""
import argparse
import hmac
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from buckbook.db import IMG_DIR, ROOT, bump_version, connect, version
from reveal_poc import load_env

STATIC = Path(__file__).parent / "static"
COOKIE = "buckbook_session"

conn = connect()
lock = Lock()
PASSCODE = load_env(ROOT / ".env").get("BUCKBOOK_PASSCODE", "")

app = FastAPI(title="Buck Book", docs_url=None, redoc_url=None)


def now():
    return datetime.now(timezone.utc).isoformat()


def current_user(buckbook_session: str | None = Cookie(default=None)):
    if not buckbook_session:
        raise HTTPException(401, "Sign in with the crew passcode.")
    row = conn.execute(
        "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (buckbook_session,),
    ).fetchone()
    if not row:
        raise HTTPException(401, "Your sign-in expired. Sign in again.")
    return dict(row)


# ---------- auth ----------
class Login(BaseModel):
    passcode: str
    name: str = Field(min_length=1, max_length=30)


@app.post("/api/login")
def login(body: Login, response: Response):
    if not PASSCODE:
        raise HTTPException(503, "No crew passcode set. Add BUCKBOOK_PASSCODE to .env and restart.")
    if not hmac.compare_digest(body.passcode.strip(), PASSCODE):
        time.sleep(1)
        raise HTTPException(403, "That passcode isn't right.")
    name = body.name.strip()
    with lock:
        row = conn.execute("SELECT id, name FROM users WHERE name = ?", (name,)).fetchone()
        if row:
            user = dict(row)
        else:
            user = {"id": uuid.uuid4().hex, "name": name}
            conn.execute("INSERT INTO users VALUES (?, ?, ?)", (user["id"], name, now()))
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, user["id"], now()))
        bump_version(conn)
        conn.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return user


@app.post("/api/logout")
def logout(response: Response, buckbook_session: str | None = Cookie(default=None)):
    if buckbook_session:
        with lock:
            conn.execute("DELETE FROM sessions WHERE token = ?", (buckbook_session,))
            conn.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


# ---------- data ----------
@app.get("/api/cards")
def cards(user=Depends(current_user)):
    out = []
    for r in conn.execute("SELECT * FROM cards ORDER BY camera, taken_at"):
        out.append({
            "id": r["id"], "cam": r["camera"], "property": r["property"], "when": r["taken_at"],
            "daylight": bool(r["daylight"]), "temp": r["temp_f"], "wind": r["wind"], "moon": r["moon"],
            "pressure": r["pressure"], "burst": r["burst"],
            "crop": f"/img/crop/{r['id']}.jpg", "frame": f"/img/frame/{r['photo_id']}",
        })
    return out


@app.get("/api/sync")
def sync(since: int = -1, user=Depends(current_user)):
    v = version(conn)
    if since == v:
        return {"version": v, "changed": False}
    labels = {
        r["card_id"]: {"verdict": r["verdict"], "buckId": r["buck_id"], "points": r["points"],
                       "confidence": r["confidence"], "by": r["by_user"], "at": r["at"]}
        for r in conn.execute("SELECT * FROM labels")
    }
    bucks = {
        r["id"]: {"name": r["name"], "cover": r["cover"], "by": r["by_user"], "at": r["at"]}
        for r in conn.execute("SELECT * FROM bucks")
    }
    users = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users")}
    return {"version": v, "changed": True, "labels": labels, "bucks": bucks, "users": users}


class Label(BaseModel):
    verdict: str = Field(pattern="^(buck|not|unsure)$")
    buckId: str | None = None
    points: int | None = Field(default=None, ge=0, le=40)
    confidence: int | None = Field(default=None, ge=1, le=5)


@app.put("/api/labels/{card_id}")
def put_label(card_id: str, body: Label, user=Depends(current_user)):
    with lock:
        if not conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone():
            raise HTTPException(404, "No such photo.")
        if body.buckId and not conn.execute("SELECT 1 FROM bucks WHERE id = ?", (body.buckId,)).fetchone():
            raise HTTPException(400, "That buck isn't in the book.")
        conn.execute(
            """INSERT OR REPLACE INTO labels (card_id, verdict, buck_id, points, confidence, by_user, at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (card_id, body.verdict, body.buckId, body.points, body.confidence, user["id"], now()),
        )
        bump_version(conn)
        conn.commit()
    return {"ok": True}


@app.delete("/api/labels/{card_id}")
def delete_label(card_id: str, user=Depends(current_user)):
    with lock:
        conn.execute("DELETE FROM labels WHERE card_id = ?", (card_id,))
        bump_version(conn)
        conn.commit()
    return {"ok": True}


class Buck(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    cover: str | None = None


@app.put("/api/bucks/{buck_id}")
def put_buck(buck_id: str, body: Buck, user=Depends(current_user)):
    with lock:
        row = conn.execute("SELECT by_user, at FROM bucks WHERE id = ?", (buck_id,)).fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO bucks (id, name, cover, by_user, at) VALUES (?, ?, ?, ?, ?)",
            (buck_id, body.name.strip(), body.cover,
             row["by_user"] if row else user["id"], row["at"] if row else now()),
        )
        bump_version(conn)
        conn.commit()
    return {"ok": True}


@app.delete("/api/bucks/{buck_id}")
def delete_buck(buck_id: str, user=Depends(current_user)):
    with lock:
        if conn.execute("SELECT 1 FROM labels WHERE buck_id = ?", (buck_id,)).fetchone():
            raise HTTPException(409, "That buck still has photos. Re-sort them first.")
        conn.execute("DELETE FROM bucks WHERE id = ?", (buck_id,))
        bump_version(conn)
        conn.commit()
    return {"ok": True}


# ---------- files ----------
@app.get("/img/{kind}/{name}")
def image(kind: str, name: str, user=Depends(current_user)):
    if kind not in ("crop", "frame"):
        raise HTTPException(404)
    path = (IMG_DIR / kind / name).resolve()
    if path.parent != (IMG_DIR / kind).resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow other devices on your network")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if not PASSCODE:
        print("Warning: BUCKBOOK_PASSCODE is not set in .env; nobody can sign in.")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
