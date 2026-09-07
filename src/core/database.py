"""Base de datos SQLite: usuarios y estado por telegram_chat_id.

Cada usuario de Telegram tiene UNA cuenta de Akumaja asociada.
Ninguna consulta cruza datos entre usuarios.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from src.core.config import DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id TEXT NOT NULL UNIQUE,
    moodle_instance_id TEXT NOT NULL,
    moodle_username TEXT NOT NULL,
    moodle_password_encrypted TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_sync_at TEXT
);
"""


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = _connect()
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_user_by_chat_id(chat_id):
    chat_id = str(chat_id)
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_chat_id = ? AND active = 1",
                (chat_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def upsert_user(chat_id, instance_id, username, password_encrypted):
    """Crea o actualiza la cuenta de un usuario."""
    chat_id = str(chat_id)
    now = _now()
    with _lock:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT id FROM users WHERE telegram_chat_id = ?",
                (chat_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE users SET
                        moodle_instance_id = ?,
                        moodle_username = ?,
                        moodle_password_encrypted = ?,
                        active = 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (instance_id, username, password_encrypted, now, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users (
                        telegram_chat_id, moodle_instance_id, moodle_username,
                        moodle_password_encrypted, active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (chat_id, instance_id, username, password_encrypted, now, now),
                )
            conn.commit()
        finally:
            conn.close()


def delete_user(chat_id):
    """Elimina la cuenta y los datos privados del usuario (logout)."""
    chat_id = str(chat_id)
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM users WHERE telegram_chat_id = ?", (chat_id,))
            conn.commit()
        finally:
            conn.close()


def list_active_users():
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM users WHERE active = 1 ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def update_last_sync(chat_id):
    chat_id = str(chat_id)
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE users SET last_sync_at = ? WHERE telegram_chat_id = ?",
                (_now(), chat_id),
            )
            conn.commit()
        finally:
            conn.close()


def update_user_faculty(chat_id, instance_id, username, password_encrypted):
    """Actualiza la instancia/credencial de un usuario existente.

    Se usa SOLO tras validar el login contra la nueva instancia.
    Actualiza también updated_at y last_sync_at.
    """
    chat_id = str(chat_id)
    now = _now()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id FROM users WHERE telegram_chat_id = ?",
                (chat_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"No existe cuenta para el chat {chat_id}")

            conn.execute(
                """
                UPDATE users SET
                    moodle_instance_id = ?,
                    moodle_username = ?,
                    moodle_password_encrypted = ?,
                    updated_at = ?,
                    last_sync_at = ?
                WHERE id = ?
                """,
                (instance_id, username, password_encrypted, now, now, row["id"]),
            )
            conn.commit()
        finally:
            conn.close()


def count_users():
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE active = 1").fetchone()
            return row["n"]
        finally:
            conn.close()
