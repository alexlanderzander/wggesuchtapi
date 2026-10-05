import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .calendars import provider_for
from .config import get_settings
from .db import (
    get_calendar_connection,
    init_db,
    list_calendar_connections,
    update_calendar_tokens,
    upsert_calendar_connection,
)

app = FastAPI(title='WG Review MVP', version='0.1.0')


@app.on_event('startup')
def startup() -> None:
    init_db()


def _sign_state(provider: str, member_id: str) -> str:
    settings = get_settings()
    payload = {'provider': provider, 'member_id': member_id, 'iat': int(time.time())}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    sig = hmac.new(settings.app_secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f'{raw}.{sig}'


def _read_state(value: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        raw, signature = value.rsplit('.', 1)
        expected = hmac.new(settings.app_secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('bad signature')
        payload = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
        if int(time.time()) - int(payload['iat']) > 900:
            raise ValueError('expired')
        return payload
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid or expired OAuth state') from exc


def _validate_provider_config(provider: str) -> None:
    settings = get_settings()
    if provider == 'google' and (not settings.google_client_id or not settings.google_client_secret):
        raise HTTPException(status_code=503, detail='Google OAuth is not configured')
    if provider == 'microsoft' and (not settings.microsoft_client_id or not settings.microsoft_client_secret):
        raise HTTPException(status_code=503, detail='Microsoft OAuth is not configured')


@app.get('/', response_class=HTMLResponse)
def home() -> str:
    return '''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WG Review MVP</title><style>
body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#171717}
.card{border:1px solid #ddd;border-radius:16px;padding:20px;margin:16px 0}button,a.btn{padding:10px 14px;border-radius:10px;border:0;background:#111;color:#fff;text-decoration:none;margin-right:8px}.muted{color:#666}input{padding:9px;border:1px solid #ccc;border-radius:8px}
</style></head><body>
<h1>WG Review MVP</h1><p class="muted">Candidate review + shared interview scheduling.</p>
<div class="card"><h2>Connect a roommate calendar</h2><p>Enter a local member id/name, then connect the provider. Each person authorizes their own account.</p>
<input id="member" value="roommate-1"><p><a class="btn" id="g">Google Calendar</a><a class="btn" id="m">Outlook / Microsoft</a></p></div>
<div class="card"><h2>Connections</h2><pre id="connections">Loading…</pre></div>
<script>
const member=document.getElementById('member');
function link(provider){return '/api/calendar/'+provider+'/connect?member_id='+encodeURIComponent(member.value)}
function refreshLinks(){g.href=link('google');m.href=link('microsoft')} member.oninput=refreshLinks;refreshLinks();
fetch('/api/calendar/connections').then(r=>r.json()).then(x=>connections.textContent=JSON.stringify(x,null,2));
</script></body></html>'''


@app.get('/api/calendar/providers')
def providers() -> dict[str, Any]:
    settings = get_settings()
    return {
        'google': {'configured': bool(settings.google_client_id and settings.google_client_secret)},
        'microsoft': {'configured': bool(settings.microsoft_client_id and settings.microsoft_client_secret)},
    }


@app.get('/api/calendar/{provider}/connect')
def connect_calendar(provider: str, member_id: str = Query(min_length=1, max_length=100)):
    if provider not in {'google', 'microsoft'}:
        raise HTTPException(status_code=404, detail='Unknown provider')
    _validate_provider_config(provider)
    client = provider_for(provider, get_settings())
    return RedirectResponse(client.authorization_url(_sign_state(provider, member_id)))


@app.get('/api/calendar/{provider}/callback')
def calendar_callback(provider: str, code: str, state: str):
    payload = _read_state(state)
    if payload['provider'] != provider:
        raise HTTPException(status_code=400, detail='Provider mismatch')
    _validate_provider_config(provider)
    client = provider_for(provider, get_settings())
    token_data = client.exchange_code(code)
    account_label = client.account_label(token_data)
    connection_id = upsert_calendar_connection(payload['member_id'], provider, account_label, token_data)
    return RedirectResponse(url=f'/?connected={connection_id}')


@app.get('/api/calendar/connections')
def calendar_connections(member_id: str | None = None):
    return list_calendar_connections(member_id)


@app.get('/api/calendar/{connection_id}/busy')
def calendar_busy(connection_id: str, start: datetime, end: datetime):
    if end <= start:
        raise HTTPException(status_code=400, detail='end must be after start')
    connection = get_calendar_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail='Calendar connection not found')
    client = provider_for(connection['provider'], get_settings())
    fresh = client.ensure_token(connection['token_data'])
    if fresh != connection['token_data']:
        update_calendar_tokens(connection_id, fresh)
    return {'connection_id': connection_id, 'busy': client.busy(fresh, start, end)}


class Appointment(BaseModel):
    start: datetime
    end: datetime
    title: str = 'WG viewing'
    description: str = ''
    attendee_email: str | None = None
    location: str | None = None


@app.post('/api/calendar/{connection_id}/appointments')
def create_appointment(connection_id: str, body: Appointment):
    if body.end <= body.start:
        raise HTTPException(status_code=400, detail='end must be after start')
    connection = get_calendar_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail='Calendar connection not found')
    client = provider_for(connection['provider'], get_settings())
    fresh = client.ensure_token(connection['token_data'])
    if fresh != connection['token_data']:
        update_calendar_tokens(connection_id, fresh)
    event = client.create_event(
        fresh,
        start=body.start,
        end=body.end,
        title=body.title,
        description=body.description,
        attendee_email=body.attendee_email,
        location=body.location,
    )
    return {'provider': connection['provider'], 'event_id': event.get('id'), 'event': event}
