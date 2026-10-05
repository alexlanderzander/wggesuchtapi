import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from .config import Settings


class CalendarProvider(ABC):
    name: str

    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def authorization_url(self, state: str) -> str: ...

    @abstractmethod
    def exchange_code(self, code: str) -> dict[str, Any]: ...

    @abstractmethod
    def refresh(self, token_data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def account_label(self, token_data: dict[str, Any]) -> str | None: ...

    @abstractmethod
    def busy(self, token_data: dict[str, Any], start: datetime, end: datetime) -> list[dict[str, str]]: ...

    @abstractmethod
    def create_event(
        self,
        token_data: dict[str, Any],
        *,
        start: datetime,
        end: datetime,
        title: str,
        description: str,
        attendee_email: str | None,
        location: str | None,
    ) -> dict[str, Any]: ...

    def ensure_token(self, token_data: dict[str, Any]) -> dict[str, Any]:
        expires_at = float(token_data.get('expires_at') or 0)
        if expires_at and expires_at > time.time() + 60:
            return token_data
        if token_data.get('refresh_token'):
            return self.refresh(token_data)
        return token_data


class GoogleCalendarProvider(CalendarProvider):
    name = 'google'
    AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
    TOKEN_URL = 'https://oauth2.googleapis.com/token'
    FREEBUSY_URL = 'https://www.googleapis.com/calendar/v3/freeBusy'
    EVENTS_URL = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
    USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
    SCOPES = [
        'openid',
        'email',
        'https://www.googleapis.com/auth/calendar.freebusy',
        'https://www.googleapis.com/auth/calendar.events.owned',
    ]

    def authorization_url(self, state: str) -> str:
        params = {
            'client_id': self.settings.google_client_id,
            'redirect_uri': self.settings.google_redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(self.SCOPES),
            'access_type': 'offline',
            'include_granted_scopes': 'true',
            'prompt': 'consent',
            'state': state,
        }
        return f'{self.AUTH_URL}?{urlencode(params)}'

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = requests.post(
            self.TOKEN_URL,
            data={
                'code': code,
                'client_id': self.settings.google_client_id,
                'client_secret': self.settings.google_client_secret,
                'redirect_uri': self.settings.google_redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=20,
        )
        response.raise_for_status()
        token = response.json()
        token['expires_at'] = time.time() + int(token.get('expires_in', 3600))
        return token

    def refresh(self, token_data: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self.TOKEN_URL,
            data={
                'client_id': self.settings.google_client_id,
                'client_secret': self.settings.google_client_secret,
                'refresh_token': token_data['refresh_token'],
                'grant_type': 'refresh_token',
            },
            timeout=20,
        )
        response.raise_for_status()
        updated = {**token_data, **response.json()}
        updated['expires_at'] = time.time() + int(updated.get('expires_in', 3600))
        return updated

    def account_label(self, token_data: dict[str, Any]) -> str | None:
        response = requests.get(
            self.USERINFO_URL,
            headers={'Authorization': f"Bearer {token_data['access_token']}"},
            timeout=20,
        )
        if response.ok:
            return response.json().get('email')
        return None

    def busy(self, token_data: dict[str, Any], start: datetime, end: datetime) -> list[dict[str, str]]:
        token_data = self.ensure_token(token_data)
        response = requests.post(
            self.FREEBUSY_URL,
            headers={'Authorization': f"Bearer {token_data['access_token']}"},
            json={
                'timeMin': start.astimezone(timezone.utc).isoformat(),
                'timeMax': end.astimezone(timezone.utc).isoformat(),
                'items': [{'id': 'primary'}],
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get('calendars', {}).get('primary', {}).get('busy', [])

    def create_event(self, token_data: dict[str, Any], *, start: datetime, end: datetime, title: str, description: str, attendee_email: str | None, location: str | None) -> dict[str, Any]:
        token_data = self.ensure_token(token_data)
        payload: dict[str, Any] = {
            'summary': title,
            'description': description,
            'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': end.isoformat()},
        }
        if attendee_email:
            payload['attendees'] = [{'email': attendee_email}]
        if location:
            payload['location'] = location
        response = requests.post(
            self.EVENTS_URL,
            params={'sendUpdates': 'all'},
            headers={'Authorization': f"Bearer {token_data['access_token']}"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()


class MicrosoftCalendarProvider(CalendarProvider):
    name = 'microsoft'
    AUTH_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
    TOKEN_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    GRAPH_URL = 'https://graph.microsoft.com/v1.0'
    SCOPES = ['openid', 'email', 'offline_access', 'User.Read', 'Calendars.ReadWrite']

    def authorization_url(self, state: str) -> str:
        params = {
            'client_id': self.settings.microsoft_client_id,
            'redirect_uri': self.settings.microsoft_redirect_uri,
            'response_type': 'code',
            'response_mode': 'query',
            'scope': ' '.join(self.SCOPES),
            'state': state,
        }
        return f'{self.AUTH_URL}?{urlencode(params)}'

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = requests.post(
            self.TOKEN_URL,
            data={
                'client_id': self.settings.microsoft_client_id,
                'client_secret': self.settings.microsoft_client_secret,
                'code': code,
                'redirect_uri': self.settings.microsoft_redirect_uri,
                'grant_type': 'authorization_code',
                'scope': ' '.join(self.SCOPES),
            },
            timeout=20,
        )
        response.raise_for_status()
        token = response.json()
        token['expires_at'] = time.time() + int(token.get('expires_in', 3600))
        return token

    def refresh(self, token_data: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self.TOKEN_URL,
            data={
                'client_id': self.settings.microsoft_client_id,
                'client_secret': self.settings.microsoft_client_secret,
                'refresh_token': token_data['refresh_token'],
                'grant_type': 'refresh_token',
                'scope': ' '.join(self.SCOPES),
            },
            timeout=20,
        )
        response.raise_for_status()
        updated = {**token_data, **response.json()}
        updated['expires_at'] = time.time() + int(updated.get('expires_in', 3600))
        return updated

    def account_label(self, token_data: dict[str, Any]) -> str | None:
        response = requests.get(
            f'{self.GRAPH_URL}/me?$select=displayName,mail,userPrincipalName',
            headers={'Authorization': f"Bearer {token_data['access_token']}"},
            timeout=20,
        )
        if response.ok:
            body = response.json()
            return body.get('mail') or body.get('userPrincipalName') or body.get('displayName')
        return None

    def busy(self, token_data: dict[str, Any], start: datetime, end: datetime) -> list[dict[str, str]]:
        token_data = self.ensure_token(token_data)
        response = requests.get(
            f'{self.GRAPH_URL}/me/calendar/calendarView',
            params={
                'startDateTime': start.astimezone(timezone.utc).isoformat(),
                'endDateTime': end.astimezone(timezone.utc).isoformat(),
                '$select': 'start,end,showAs,isCancelled',
            },
            headers={
                'Authorization': f"Bearer {token_data['access_token']}",
                'Prefer': 'outlook.timezone="UTC"',
            },
            timeout=20,
        )
        response.raise_for_status()
        result = []
        for event in response.json().get('value', []):
            if event.get('isCancelled') or event.get('showAs') == 'free':
                continue
            result.append({'start': event['start']['dateTime'] + 'Z', 'end': event['end']['dateTime'] + 'Z'})
        return result

    def create_event(self, token_data: dict[str, Any], *, start: datetime, end: datetime, title: str, description: str, attendee_email: str | None, location: str | None) -> dict[str, Any]:
        token_data = self.ensure_token(token_data)
        payload: dict[str, Any] = {
            'subject': title,
            'body': {'contentType': 'Text', 'content': description},
            'start': {'dateTime': start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'},
            'end': {'dateTime': end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'},
        }
        if attendee_email:
            payload['attendees'] = [{'emailAddress': {'address': attendee_email}, 'type': 'required'}]
        if location:
            payload['location'] = {'displayName': location}
        response = requests.post(
            f'{self.GRAPH_URL}/me/events',
            headers={'Authorization': f"Bearer {token_data['access_token']}"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()


def provider_for(name: str, settings: Settings) -> CalendarProvider:
    if name == 'google':
        return GoogleCalendarProvider(settings)
    if name == 'microsoft':
        return MicrosoftCalendarProvider(settings)
    raise ValueError(f'Unsupported calendar provider: {name}')
