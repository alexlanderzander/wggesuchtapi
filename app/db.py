import base64
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet

from .config import get_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet() -> Fernet:
    secret = get_settings().app_secret_key
    digest = hashlib.sha256(secret.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(value: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(value).encode('utf-8')).decode('ascii')


def decrypt_json(value: str) -> dict[str, Any]:
    return json.loads(_fernet().decrypt(value.encode('ascii')).decode('utf-8'))


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt_text(value: str) -> str:
    return _fernet().decrypt(value.encode('ascii')).decode('utf-8')


@contextmanager
def db():
    path = get_settings().database_path
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS calendar_connections (
                id TEXT PRIMARY KEY,
                member_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                account_label TEXT,
                token_json_enc TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(member_id, provider)
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                external_id TEXT UNIQUE,
                display_name TEXT,
                conversation_id TEXT,
                latest_message TEXT,
                fit_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'new',
                updated_at TEXT NOT NULL
            );
            '''
        )

        columns = {row['name'] for row in conn.execute('PRAGMA table_info(candidates)').fetchall()}
        if 'application_text_enc' not in columns:
            conn.execute('ALTER TABLE candidates ADD COLUMN application_text_enc TEXT')

        # One-time migration of older plaintext rows into encrypted storage.
        rows = conn.execute(
            "SELECT id, latest_message FROM candidates WHERE application_text_enc IS NULL AND COALESCE(latest_message, '') != ''"
        ).fetchall()
        for row in rows:
            conn.execute(
                'UPDATE candidates SET application_text_enc = ?, latest_message = ? WHERE id = ?',
                (encrypt_text(row['latest_message']), '', row['id']),
            )


def upsert_calendar_connection(member_id: str, provider: str, account_label: str | None, token_data: dict[str, Any]) -> str:
    with db() as conn:
        row = conn.execute(
            'SELECT id FROM calendar_connections WHERE member_id = ? AND provider = ?',
            (member_id, provider),
        ).fetchone()
        connection_id = row['id'] if row else str(uuid.uuid4())
        now = _now()
        conn.execute(
            '''
            INSERT INTO calendar_connections
                (id, member_id, provider, account_label, token_json_enc, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(member_id, provider) DO UPDATE SET
                account_label = excluded.account_label,
                token_json_enc = excluded.token_json_enc,
                updated_at = excluded.updated_at
            ''',
            (connection_id, member_id, provider, account_label, encrypt_json(token_data), now, now),
        )
        return connection_id


def get_calendar_connection(connection_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute('SELECT * FROM calendar_connections WHERE id = ?', (connection_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result['token_data'] = decrypt_json(result.pop('token_json_enc'))
    return result


def list_calendar_connections(member_id: str | None = None) -> list[dict[str, Any]]:
    with db() as conn:
        if member_id:
            rows = conn.execute(
                'SELECT id, member_id, provider, account_label, created_at, updated_at FROM calendar_connections WHERE member_id = ? ORDER BY provider',
                (member_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT id, member_id, provider, account_label, created_at, updated_at FROM calendar_connections ORDER BY member_id, provider'
            ).fetchall()
    return [dict(row) for row in rows]


def update_calendar_tokens(connection_id: str, token_data: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            'UPDATE calendar_connections SET token_json_enc = ?, updated_at = ? WHERE id = ?',
            (encrypt_json(token_data), _now(), connection_id),
        )
