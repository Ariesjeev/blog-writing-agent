"""SQLite storage: users (PBKDF2 hashed passwords), blogs (+ JSON data) and version history.
Set BWA_DB to change the file, or swap sqlite3 for Postgres (psycopg) with the same SQL."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("BWA_DB", "bwa.db")


def _c() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _c() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, salt BLOB, pw BLOB, created REAL);
        CREATE TABLE IF NOT EXISTS blogs(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, title TEXT,
                                         md TEXT, data TEXT, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY AUTOINCREMENT, blog_id INTEGER,
                                            md TEXT, note TEXT, created REAL);
        """)


def _hash(pw: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)


def register(user: str, pw: str) -> Optional[str]:
    """Returns an error message, or None on success."""
    user = user.strip().lower()
    if len(user) < 3 or len(pw) < 8:
        return "Username needs 3+ characters and password 8+ characters."
    salt = secrets.token_bytes(16)
    try:
        with _c() as c:
            c.execute("INSERT INTO users VALUES (?,?,?,?)", (user, salt, _hash(pw, salt), time.time()))
    except sqlite3.IntegrityError:
        return "That username is taken."
    return None


def login(user: str, pw: str) -> bool:
    with _c() as c:
        row = c.execute("SELECT salt, pw FROM users WHERE username=?", (user.strip().lower(),)).fetchone()
    return bool(row) and hmac.compare_digest(row["pw"], _hash(pw, row["salt"]))


def save_blog(owner: str, title: str, md: str, data: Dict[str, Any],
              blog_id: Optional[int] = None, note: str = "Generated") -> int:
    now, blob = time.time(), json.dumps(data, default=str)
    with _c() as c:
        row = c.execute("SELECT md FROM blogs WHERE id=? AND owner=?", (blog_id, owner)).fetchone() if blog_id else None
        if row:
            c.execute("UPDATE blogs SET title=?, md=?, data=?, updated=? WHERE id=?", (title, md, blob, now, blog_id))
            if row["md"] != md:
                c.execute("INSERT INTO versions(blog_id, md, note, created) VALUES (?,?,?,?)", (blog_id, md, note, now))
        else:
            cur = c.execute("INSERT INTO blogs(owner,title,md,data,created,updated) VALUES (?,?,?,?,?,?)",
                            (owner, title, md, blob, now, now))
            blog_id = cur.lastrowid
            c.execute("INSERT INTO versions(blog_id, md, note, created) VALUES (?,?,?,?)", (blog_id, md, note, now))
    return int(blog_id)


def list_blogs(owner: str, q: str = "") -> List[sqlite3.Row]:
    with _c() as c:
        return c.execute("SELECT id, title, updated FROM blogs WHERE owner=? AND title LIKE ? ORDER BY updated DESC LIMIT 100",
                         (owner, f"%{q}%")).fetchall()


def get_blog(blog_id: int, owner: str) -> Optional[Dict[str, Any]]:
    with _c() as c:
        row = c.execute("SELECT * FROM blogs WHERE id=? AND owner=?", (blog_id, owner)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "title": row["title"], "md": row["md"], "data": json.loads(row["data"] or "{}")}


def delete_blog(blog_id: int, owner: str) -> None:
    with _c() as c:
        if c.execute("SELECT 1 FROM blogs WHERE id=? AND owner=?", (blog_id, owner)).fetchone():
            c.execute("DELETE FROM versions WHERE blog_id=?", (blog_id,))
            c.execute("DELETE FROM blogs WHERE id=?", (blog_id,))


def list_versions(blog_id: int) -> List[sqlite3.Row]:
    with _c() as c:
        return c.execute("SELECT id, md, note, created FROM versions WHERE blog_id=? ORDER BY id DESC", (blog_id,)).fetchall()