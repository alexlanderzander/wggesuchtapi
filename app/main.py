import base64
import hashlib
import hmac
import html
import json
import re
import time
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .calendars import provider_for
from .candidates_store import list_candidates, set_candidate_status
from .config import get_settings
from .db import (
    get_calendar_connection,
    init_db,
    list_calendar_connections,
    update_calendar_tokens,
    upsert_calendar_connection,
)
from .scheduler import find_common_slots
from .wg_service import sync_candidates

app = FastAPI(title='WG Review MVP', version='0.3.0')


@app.on_event('startup')
def startup() -> None:
    init_db()


def _sign_payload(payload: dict[str, Any]) -> str:
    settings = get_settings()
    data = {**payload, 'iat': int(time.time())}
    raw = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')
    sig = hmac.new(settings.app_secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f'{raw}.{sig}'


def _read_payload(value: str, max_age_seconds: int) -> dict[str, Any]:
    settings = get_settings()
    try:
        raw, signature = value.rsplit('.', 1)
        expected = hmac.new(settings.app_secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('bad signature')
        payload = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
        if int(time.time()) - int(payload['iat']) > max_age_seconds:
            raise ValueError('expired')
        return payload
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid or expired signed link') from exc


def _sign_state(provider: str, member_id: str) -> str:
    return _sign_payload({'kind': 'oauth_state', 'provider': provider, 'member_id': member_id})


def _read_state(value: str) -> dict[str, Any]:
    payload = _read_payload(value, 900)
    if payload.get('kind') != 'oauth_state':
        raise HTTPException(status_code=400, detail='Invalid OAuth state')
    return payload


def _sign_calendar_invite(member_id: str, display_name: str, role: str) -> str:
    return _sign_payload({
        'kind': 'calendar_invite',
        'member_id': member_id,
        'display_name': display_name,
        'role': role,
    })


def _read_calendar_invite(value: str) -> dict[str, Any]:
    payload = _read_payload(value, 60 * 60 * 24 * 30)
    if payload.get('kind') != 'calendar_invite':
        raise HTTPException(status_code=400, detail='Invalid calendar invite')
    return payload


def _member_id(display_name: str, role: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', display_name.casefold()).strip('-')[:30] or role
    return f'{slug}-{uuid4().hex[:8]}'


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
body{font-family:system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#171717;background:#f7f7f7}
.card{background:#fff;border:1px solid #ddd;border-radius:16px;padding:20px;margin:16px 0}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.candidate{border-top:1px solid #eee;padding:18px 0}.badge{display:inline-block;background:#eee;border-radius:999px;padding:4px 9px;margin:3px 5px 3px 0;font-size:13px}.badge.warn{background:#fff1d6}.badge.ok{background:#e8f5e9}.profile{display:flex;gap:12px;flex-wrap:wrap;margin:9px 0}.profile span{font-size:13px}.profile b{font-weight:600}button,a.btn{padding:10px 14px;border-radius:10px;border:0;background:#111;color:#fff;text-decoration:none;cursor:pointer}.secondary{background:#eee;color:#111}.muted{color:#666}.small{font-size:13px}input,select{padding:9px;border:1px solid #ccc;border-radius:8px}pre{white-space:pre-wrap}details{margin-top:10px}.message{background:#fafafa;border-radius:10px;padding:12px;white-space:pre-wrap;max-height:320px;overflow:auto}.invite{padding:10px;background:#f5f5f5;border-radius:10px;overflow-wrap:anywhere}
</style></head><body>
<h1>WG Review MVP</h1><p class="muted">Human review of WG-Gesucht applications + shared viewing scheduling.</p>
<div class="card"><h2>Applicants</h2><p class="small muted">The app surfaces explicit WG-relevant statements and application completeness. Structured profile facts can be displayed, but sensitive traits such as age or gender are not used to rank or recommend applicants.</p><div class="row"><button onclick="syncCandidates()">Sync WG-Gesucht</button><button class="secondary" onclick="loadCandidates()">Refresh</button></div><div id="candidates">Loading…</div></div>
<div class="card"><h2>Calendar connections</h2><p>Create a link for a roommate or applicant. They open it themselves and authorize Google Calendar or Outlook/Microsoft inside the app.</p><div class="row"><input id="inviteName" placeholder="Name, e.g. Anna or Candidate Max"><select id="inviteRole"><option value="roommate">Roommate</option><option value="applicant">Applicant</option><option value="guest">Guest</option></select><button onclick="createInvite()">Create connect link</button></div><div id="inviteResult" style="margin-top:12px"></div><h3>Connected calendars</h3><pre id="connections">Loading…</pre></div>
<script>
function esc(v){return String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
async function loadConnections(){connections.textContent=JSON.stringify(await (await fetch('/api/calendar/connections')).json(),null,2)}
async function createInvite(){
  const name=document.getElementById('inviteName').value.trim();
  const role=document.getElementById('inviteRole').value;
  if(!name){alert('Enter a name first');return}
  const r=await fetch('/api/calendar/invites',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({display_name:name,role})});
  const body=await r.json();
  if(!r.ok){alert(body.detail||'Could not create link');return}
  inviteResult.innerHTML='<div class="invite"><b>'+esc(body.display_name)+'</b><br><a href="'+esc(body.url)+'">'+esc(body.url)+'</a><br><button class="secondary" style="margin-top:8px" onclick="navigator.clipboard.writeText(\''+esc(body.url)+'\')">Copy link</button></div>';
}
async function syncCandidates(){const r=await fetch('/api/wg/sync',{method:'POST'}); const body=await r.json(); if(!r.ok){alert(body.detail||'Sync failed')} else {alert('Synced '+body.synced+' conversations');} loadCandidates()}
async function setStatus(id,status){await fetch('/api/candidates/'+id+'/status',{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({status})});loadCandidates()}
function detailLabel(v){return ({sparse:'Sparse',medium:'Medium detail',detailed:'Detailed',very_short:'Very short',basic:'Basic',very_detailed:'Very detailed'})[v]||v}
function profileHtml(profile){const labels={age:'Age',gender:'Gender',occupation:'Occupation',study:'Study'};return Object.entries(profile||{}).map(([k,v])=>'<span><b>'+esc(labels[k]||k)+':</b> '+esc(v)+'</span>').join('')}
async function loadCandidates(){
  const data=await (await fetch('/api/candidates')).json();
  candidates.innerHTML=data.length?'':'<p class="muted">No applicants synced yet.</p>';
  for(const c of data){
    const s=c.signals||{}; const detail=s.application_detail||{}; const criteria=s.criteria||[]; const profile=s.profile||{};
    const badges=[];
    badges.push('<span class="badge '+(detail.availability_only?'warn':'')+'">'+esc(detailLabel(detail.detail_level||detail.level||'unknown'))+' · '+esc(detail.word_count||0)+' words</span>');
    if(detail.availability_only) badges.push('<span class="badge warn">Mostly availability question</span>');
    for(const item of criteria){if(item.mentioned) badges.push('<span class="badge ok">'+esc(item.label)+'</span>')}
    const evidence=criteria.filter(x=>x.evidence&&x.evidence.length).map(x=>'<li><b>'+esc(x.label)+':</b> '+esc(x.evidence[0])+'</li>').join('');
    const profileBlock=Object.keys(profile).length?'<div class="profile">'+profileHtml(profile)+'</div><div class="small muted">Profile facts shown for context only; not used by automated matching.</div>':'';
    candidates.innerHTML += '<div class="candidate"><div class="row"><b>'+esc(c.display_name)+'</b><span class="muted">'+esc(c.status)+'</span></div>'+profileBlock+'<div>'+badges.join('')+'</div>'+(evidence?'<ul>'+evidence+'</ul>':'<p class="muted small">No WG-specific topics detected yet.</p>')+'<details><summary>Application text</summary><div class="message">'+esc(c.latest_message||'')+'</div></details><div class="row" style="margin-top:12px"><button onclick="setStatus(\''+esc(c.id)+'\',\'shortlist\')">Shortlist</button><button class="secondary" onclick="setStatus(\''+esc(c.id)+'\',\'interview\')">Interview</button><button class="secondary" onclick="setStatus(\''+esc(c.id)+'\',\'pass\')">Pass</button></div></div>';
  }
}
loadCandidates();loadConnections();
</script></body></html>'''


class CalendarInviteRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal['roommate', 'applicant', 'guest'] = 'roommate'


@app.post('/api/calendar/invites')
def create_calendar_invite(body: CalendarInviteRequest):
    settings = get_settings()
    member_id = _member_id(body.display_name, body.role)
    token = _sign_calendar_invite(member_id, body.display_name, body.role)
    return {
        'member_id': member_id,
        'display_name': body.display_name,
        'role': body.role,
        'url': f"{settings.app_base_url.rstrip('/')}/calendar/invite/{token}",
        'expires_in_days': 30,
    }


@app.get('/calendar/invite/{token}', response_class=HTMLResponse)
def calendar_invite_page(token: str) -> str:
    payload = _read_calendar_invite(token)
    name = html.escape(payload['display_name'])
    role = html.escape(payload['role'])
    token_q = html.escape(token, quote=True)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect calendar</title><style>body{{font-family:system-ui,sans-serif;max-width:620px;margin:60px auto;padding:0 20px}}.card{{border:1px solid #ddd;border-radius:16px;padding:24px}}a{{display:inline-block;background:#111;color:#fff;text-decoration:none;padding:11px 15px;border-radius:10px;margin:6px 8px 6px 0}}.muted{{color:#666}}</style></head><body><div class="card"><h1>Connect your calendar</h1><p><b>{name}</b> · {role}</p><p class="muted">Choose your calendar provider. Your password is entered only on Google/Microsoft's authorization page; this app receives OAuth tokens, not your calendar password.</p><a href="/api/calendar/google/connect?invite_token={token_q}">Google Calendar</a><a href="/api/calendar/microsoft/connect?invite_token={token_q}">Outlook / Microsoft</a></div></body></html>'''


@app.get('/api/calendar/providers')
def providers() -> dict[str, Any]:
    settings = get_settings()
    return {
        'google': {'configured': bool(settings.google_client_id and settings.google_client_secret)},
        'microsoft': {'configured': bool(settings.microsoft_client_id and settings.microsoft_client_secret)},
    }


@app.get('/api/calendar/{provider}/connect')
def connect_calendar(
    provider: str,
    member_id: str | None = Query(default=None, min_length=1, max_length=100),
    invite_token: str | None = None,
):
    if provider not in {'google', 'microsoft'}:
        raise HTTPException(status_code=404, detail='Unknown provider')
    _validate_provider_config(provider)
    if invite_token:
        invite = _read_calendar_invite(invite_token)
        member_id = invite['member_id']
    if not member_id:
        raise HTTPException(status_code=400, detail='member_id or invite_token is required')
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
    mode: Literal['online', 'in_person'] = 'in_person'


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
        online=body.mode == 'online',
    )
    join_url = event.get('hangoutLink') or (event.get('onlineMeeting') or {}).get('joinUrl')
    return {'provider': connection['provider'], 'event_id': event.get('id'), 'join_url': join_url, 'event': event}


class CandidateStatus(BaseModel):
    status: Literal['new', 'shortlist', 'interview', 'pass']


@app.post('/api/wg/sync')
def wg_sync(max_pages: int = Query(default=4, ge=1, le=20)):
    try:
        return sync_candidates(max_pages=max_pages)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get('/api/candidates')
def candidates():
    return list_candidates()


@app.patch('/api/candidates/{candidate_id}/status')
def candidate_status(candidate_id: str, body: CandidateStatus):
    if not set_candidate_status(candidate_id, body.status):
        raise HTTPException(status_code=404, detail='Candidate not found')
    return {'ok': True, 'status': body.status}


class SlotSearch(BaseModel):
    connection_ids: list[str]
    start: datetime
    end: datetime
    duration_minutes: int = 30
    step_minutes: int = 30
    timezone: str = 'Europe/Berlin'


@app.post('/api/schedule/slots')
def schedule_slots(body: SlotSearch):
    if body.end <= body.start:
        raise HTTPException(status_code=400, detail='end must be after start')
    if not 15 <= body.duration_minutes <= 180:
        raise HTTPException(status_code=400, detail='duration_minutes must be between 15 and 180')
    if not 5 <= body.step_minutes <= 180:
        raise HTTPException(status_code=400, detail='step_minutes must be between 5 and 180')
    try:
        slots = find_common_slots(
            body.connection_ids,
            body.start,
            body.end,
            duration_minutes=body.duration_minutes,
            step_minutes=body.step_minutes,
            timezone_name=body.timezone,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'slots': slots}
