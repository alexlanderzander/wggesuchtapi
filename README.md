# WG Review MVP

Small self-hosted application built on top of the unofficial `WgGesuchtAPI` client. It is intended for one WG to review incoming WG-Gesucht conversations, coordinate human decisions, and schedule viewings across roommates and applicants.

> This project is not affiliated with WG-Gesucht / SMP GmbH & Co. KG. The WG-Gesucht API used by the original repository is unofficial and can change without notice.

## What the MVP currently does

- Reads WG-Gesucht conversation threads into a local review inbox.
- Shows explicit WG-relevant statements from the application text (shared WG life, cleaning routines, privacy/personal space, viewing/move-in logistics).
- Shows application completeness such as word count, detail level, topics covered, and whether a message is essentially only an availability question.
- Keeps the actual shortlist/interview/pass choice manual.
- Connects multiple Google Calendar and Microsoft/Outlook Calendar accounts independently with OAuth.
- Reads availability, finds common free slots, and creates in-person or online viewing appointments.
- Creates Google Meet links for Google events and requests Teams online meetings for Microsoft events.
- Encrypts calendar OAuth token data and applicant message text at rest using `APP_SECRET_KEY`.

The automated review layer does **not** score or rank housing applicants using sensitive traits such as age, gender, nationality, religion, disability, sexual orientation, or similar personal attributes. If an applicant voluntarily includes such information, it can remain visible in their original application text for human review, but it is not an automated matching input.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

Before using real WG-Gesucht data, generate a long random `APP_SECRET_KEY` and rotate any WG-Gesucht password that has ever appeared in an exported chat or other plaintext file.

## Environment variables

```dotenv
WG_GESUCHT_EMAIL=
WG_GESUCHT_PASSWORD=
WG_SESSION_FILE=.data/wg_session.json

APP_SECRET_KEY=replace-with-a-long-random-secret
DATABASE_PATH=.data/wg_review.sqlite3
APP_BASE_URL=http://127.0.0.1:8000

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/calendar/google/callback

MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REDIRECT_URI=http://127.0.0.1:8000/api/calendar/microsoft/callback
```

`.env`, `.data/`, session files, SQLite databases, and OAuth tokens must never be committed.

## Google Calendar setup

1. Create a Google Cloud project and enable the Google Calendar API.
2. Configure the OAuth consent screen.
3. Create an OAuth **Web application** client.
4. Add the redirect URI from `GOOGLE_REDIRECT_URI` exactly.
5. Put the client ID and client secret in `.env`.

The app requests offline access so it can refresh access tokens when the user is not present. It requests free/busy access plus permission to create events on calendars the user owns.

Official references:
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/identity/protocols/oauth2/scopes#calendar

## Microsoft / Outlook Calendar setup

1. Create an app registration in Microsoft Entra ID.
2. Allow personal Microsoft accounts as well as work/school accounts if your WG needs both.
3. Add the redirect URI from `MICROSOFT_REDIRECT_URI` as a Web redirect URI.
4. Create a client secret.
5. Add delegated Microsoft Graph permissions: `User.Read` and `Calendars.ReadWrite`. `offline_access` is requested during OAuth so refresh tokens can be used.
6. Put the application/client ID and secret in `.env`.

Official references:
- https://learn.microsoft.com/graph/permissions-reference
- https://learn.microsoft.com/graph/api/resources/calendar

## Calendar model

Every roommate or applicant connects their own calendar account. Connections are stored separately per participant/provider. The scheduler combines only busy intervals to find common slots; event titles/content are not needed for the common-slot calculation.

For a viewing:

- `mode=in_person`: create a normal event with a physical location.
- `mode=online`: Google requests a Google Meet conference; Microsoft requests a Teams meeting.

The default scheduling timezone is `Europe/Berlin`, while OAuth calendars can of course belong to users in other time zones.

## WG-Gesucht adapter

The original client lives in `core/wgGesuchtClient.py`. The MVP uses it server-side only. Credentials, access tokens, refresh tokens, PHP sessions, and device references must never be exposed to browser JavaScript.

The fork had a refresh-token naming collision in the original implementation. The branch uses a separate refresh method (`refreshAccessToken`) so the stored refresh-token string no longer shadows a callable method.

Current conversation support:

- list conversations
- load conversation detail
- start a contact message for an offer (from the original client)

A reliable **reply-to-existing-conversation** method is not yet included because the public fork does not document that endpoint. Do not guess or ship an unverified write endpoint against a real WG-Gesucht account.

## API highlights

- `POST /api/wg/sync` — sync WG-Gesucht conversations.
- `GET /api/candidates` — list applicants with evidence/completeness signals.
- `PATCH /api/candidates/{id}/status` — manual `new`, `shortlist`, `interview`, or `pass` state.
- `GET /api/calendar/{provider}/connect?member_id=...` — start Google/Microsoft OAuth.
- `GET /api/calendar/connections` — list connected calendars without exposing tokens.
- `POST /api/schedule/slots` — find common free slots.
- `POST /api/calendar/{connection_id}/appointments` — create an in-person or online event.

## Next MVP hardening

Before exposing this beyond a trusted local/dev environment, add application authentication and invite-scoped participant links. The current `member_id` query parameter is convenient for local development but is not sufficient authorization for an internet-facing deployment.

Apple Calendar should be added separately (likely via a carefully designed CalDAV/ICS flow rather than pretending Apple has the same OAuth model as Google/Microsoft).
