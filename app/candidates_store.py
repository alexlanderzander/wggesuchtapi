import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import db, decrypt_text, encrypt_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_candidate(*, external_id: str, display_name: str, conversation_id: str, application_text: str, signals: dict[str, Any]) -> str:
    with db() as conn:
        row = conn.execute('SELECT id, status FROM candidates WHERE external_id = ?', (external_id,)).fetchone()
        candidate_id = row['id'] if row else str(uuid.uuid4())
        status = row['status'] if row else 'new'
        conn.execute(
            '''
            INSERT INTO candidates
                (id, external_id, display_name, conversation_id, latest_message, application_text_enc, fit_json, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                display_name = excluded.display_name,
                conversation_id = excluded.conversation_id,
                latest_message = excluded.latest_message,
                application_text_enc = excluded.application_text_enc,
                fit_json = excluded.fit_json,
                updated_at = excluded.updated_at
            ''',
            (
                candidate_id,
                external_id,
                display_name,
                conversation_id,
                '',
                encrypt_text(application_text),
                json.dumps(signals),
                status,
                _now(),
            ),
        )
        return candidate_id


def _row_to_candidate(row) -> dict[str, Any]:
    item = dict(row)
    item['signals'] = json.loads(item.pop('fit_json') or '{}')
    encrypted = item.pop('application_text_enc', None)
    legacy = item.pop('latest_message', '') or ''
    item['latest_message'] = decrypt_text(encrypted) if encrypted else legacy
    return item


def _detail_values(candidate: dict[str, Any]) -> tuple[int, int, int]:
    detail = candidate.get('signals', {}).get('application_detail', {})
    level_rank = {'sparse': 0, 'medium': 1, 'detailed': 2}.get(detail.get('level'), -1)
    covered_topics = int(detail.get('covered_topics') or 0)
    word_count = int(detail.get('word_count') or 0)
    return level_rank, covered_topics, word_count


def list_candidates(*, sort: str = 'completeness', detail_filter: str | None = None) -> list[dict[str, Any]]:
    """List candidates without using sensitive profile traits for ordering.

    `completeness` sorts only by application-detail signals: detail level,
    number of neutral topics covered, and word count. Age, gender and other
    displayed profile facts are deliberately excluded from the sort key.
    """
    with db() as conn:
        rows = conn.execute(
            '''
            SELECT id, external_id, display_name, conversation_id, latest_message,
                   application_text_enc, fit_json, status, updated_at
            FROM candidates
            ORDER BY updated_at DESC
            '''
        ).fetchall()

    result = [_row_to_candidate(row) for row in rows]
    if detail_filter:
        result = [
            candidate for candidate in result
            if candidate.get('signals', {}).get('application_detail', {}).get('level') == detail_filter
        ]

    if sort == 'completeness':
        result.sort(
            key=lambda candidate: (*_detail_values(candidate), candidate.get('updated_at', '')),
            reverse=True,
        )
    return result


def get_candidate(candidate_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            '''
            SELECT id, external_id, display_name, conversation_id, latest_message,
                   application_text_enc, fit_json, status, updated_at
            FROM candidates WHERE id = ?
            ''',
            (candidate_id,),
        ).fetchone()
    return _row_to_candidate(row) if row else None


def set_candidate_status(candidate_id: str, status: str) -> bool:
    with db() as conn:
        cursor = conn.execute(
            'UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?',
            (status, _now(), candidate_id),
        )
        return cursor.rowcount > 0
