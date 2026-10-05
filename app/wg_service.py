import json
import os
from pathlib import Path
from typing import Any

from core.wgGesuchtClient import WgGesuchtClient

from .candidates_store import upsert_candidate
from .config import get_settings
from .matching import extract_application_signals


def _first_value(obj: Any, keys: set[str]) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.casefold() in keys and isinstance(value, (str, int)) and str(value).strip():
                return str(value)
        for value in obj.values():
            found = _first_value(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _first_value(value, keys)
            if found:
                return found
    return None


def _explicit_profile_facts(source: Any) -> dict[str, str]:
    """Return only explicit structured fields; never infer sensitive traits from text."""
    field_aliases = {
        'age': {'age', 'alter'},
        'gender': {'gender', 'sex', 'geschlecht'},
        'occupation': {'occupation', 'profession', 'beruf', 'job_title', 'jobtitle'},
        'study': {'study', 'studies', 'studium', 'course_of_study', 'courseofstudy'},
    }
    result: dict[str, str] = {}
    for label, aliases in field_aliases.items():
        value = _first_value(source, aliases)
        if value:
            result[label] = value[:160]
    return result


def _collect_message_text(obj: Any) -> list[str]:
    texts: list[str] = []
    message_keys = {'content', 'message', 'text', 'body'}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.casefold() in message_keys and isinstance(value, str) and len(value.strip()) > 1:
                texts.append(value.strip())
            elif isinstance(value, (dict, list)):
                texts.extend(_collect_message_text(value))
    elif isinstance(obj, list):
        for value in obj:
            texts.extend(_collect_message_text(value))
    return texts


def _save_session(client: WgGesuchtClient, session_path: Path) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(client.exportAccount()), encoding='utf-8')
    try:
        os.chmod(session_path, 0o600)
    except OSError:
        pass


def _client() -> WgGesuchtClient:
    settings = get_settings()
    client = WgGesuchtClient()
    session_path = Path(settings.wg_session_file)

    if session_path.exists():
        try:
            client.importAccount(json.loads(session_path.read_text(encoding='utf-8')))
            if client.myProfile():
                _save_session(client, session_path)
                return client
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            pass

    if not settings.wg_gesucht_email or not settings.wg_gesucht_password:
        raise RuntimeError('WG-Gesucht credentials are not configured in environment variables')
    if not client.login(settings.wg_gesucht_email, settings.wg_gesucht_password):
        raise RuntimeError('WG-Gesucht login failed')
    _save_session(client, session_path)
    return client


def sync_candidates(max_pages: int = 4) -> dict[str, Any]:
    client = _client()
    synced = 0
    errors: list[str] = []

    for page in range(1, max_pages + 1):
        conversations = client.conversations(str(page))
        if conversations is False:
            errors.append(f'Could not load conversation page {page}')
            break
        if not conversations:
            break

        for summary in conversations:
            conversation_id = _first_value(summary, {'id', 'conversation_id', 'conversationid'})
            if not conversation_id:
                continue
            detail = client.conversationDetail(conversation_id)
            if detail is False:
                errors.append(f'Could not load conversation {conversation_id}')
                continue

            messages = _collect_message_text(detail)
            application_text = '\n\n'.join(dict.fromkeys(messages))
            if not application_text:
                continue

            display_name = _first_value(
                {'summary': summary, 'detail': detail},
                {'display_name', 'displayname', 'name', 'firstname', 'first_name'},
            )
            profile = _explicit_profile_facts({'summary': summary, 'detail': detail})
            signals = extract_application_signals(application_text, profile=profile)
            upsert_candidate(
                external_id=conversation_id,
                display_name=display_name or 'Applicant',
                conversation_id=conversation_id,
                application_text=application_text,
                signals=signals,
            )
            synced += 1

        if len(conversations) < 25:
            break

    _save_session(client, Path(get_settings().wg_session_file))
    return {'synced': synced, 'errors': errors}
