import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_candidate(*, external_id: str, display_name: str, conversation_id: str, application_text: str, fit: dict[str, Any]) -> str:
    with db() as conn:
        row = conn.execute('SELECT id, status FROM candidates WHERE external_id = ?', (external_id,)).fetchone()
        candidate_id = row['id'] if row else str(uuid.uuid4())
        status = row['status'] if row else 'new'
        conn.execute(
            '''
            INSERT INTO candidates (id, external_id, display_name, conversation_id, latest_message, fit_json, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                display_name = excluded.display_name,
                conversation_id = excluded.conversation_id,
                latest_message = excluded.latest_message,
                fit_json = excluded.fit_json,
                updated_at = excluded.updated_at
            ''',
            (candidate_id, external_id, display_name, conversation_id, application_text, json.dumps(fit), status, _now()),
        )
        return candidate_id


def list_candidates() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            'SELECT id, external_id, display_name, conversation_id, latest_message, fit_json, status, updated_at FROM candidates ORDER BY json_extract(fit_json, "$.score") DESC, updated_at DESC'
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['fit'] = json.loads(item.pop('fit_json'))
        result.append(item)
    return result


def set_candidate_status(candidate_id: str, status: str) -> bool:
    with db() as conn:
        cursor = conn.execute('UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?', (status, _now(), candidate_id))
        return cursor.rowcount > 0
