# AGENTS.md — WG Review MVP handoff

## Mission

Continue building the `mvp/wg-review-app` branch into a small self-hosted MVP for one WG in Bonn to review WG-Gesucht applications, coordinate roommate decisions, and schedule viewings while one roommate may be remote/in another time zone.

The product should optimize the review workflow without turning the software into an automated tenant-selection system.

## Start here

1. Work from branch `mvp/wg-review-app`.
2. Read `README.md` before changing architecture or OAuth scopes.
3. Inspect the current code before assuming this handoff is perfectly current; the branch has been changing quickly.
4. Keep secrets local. Never commit `.env`, WG-Gesucht credentials/sessions, OAuth tokens, SQLite data, or exported chats.
5. Run the app locally with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Use a long random `APP_SECRET_KEY` in `.env` before storing real data.

## Product requirements

The MVP should support:

- ingesting WG-Gesucht conversation/application data;
- a roommate-facing candidate review UI;
- explicit evidence from an application for WG-relevant topics;
- application-completeness indicators so a substantial application is easier to review than a one-line `is the room still available?` message;
- manual roommate states such as `new`, `shortlist`, `interview`, `pass`;
- communication with applicants once a reliable existing-conversation reply endpoint is verified;
- Google Calendar and Microsoft/Outlook Calendar connections inside the app using per-user OAuth;
- each roommate and optionally an applicant/guest connecting their own calendar;
- common-free-slot calculation;
- in-person and online viewing appointments;
- Google Meet / Microsoft Teams creation where supported;
- eventual Apple Calendar support if a safe practical integration is designed.

## Housing-review guardrail

This is housing-related decision support.

The UI may display **explicit structured profile facts** that WG-Gesucht actually supplies, including fields such as age, gender, occupation, or study information. Do not infer those facts from names, photos, pronouns, writing style, or message text.

Do **not** use sensitive traits such as age or gender to automatically rank, filter out, hide, reject, shortlist, recommend, or score applicants.

The current intended automation is limited to neutral workflow/completeness signals such as:

- application length/detail level;
- whether the message is basically only an availability question;
- whether move-in/sublet dates are provided;
- viewing availability;
- whether the applicant discusses WG life expectations;
- cleanliness/shared chores;
- privacy/boundaries;
- communication/reliability statements;
- hobbies/social-life information;
- other explicit answers to the ad.

The final housing decision remains manual.

## Current architecture

### WG-Gesucht adapter

`core/wgGesuchtClient.py`

The original repository is an unofficial WG-Gesucht client. It is not affiliated with WG-Gesucht/SMP GmbH & Co. KG and endpoints may change.

Supported/used operations include:

- login/import/export session;
- profile validation;
- conversations list;
- conversation detail;
- original contact-offer method.

A refresh-token naming collision from the original fork has already been fixed by using a separate `refreshAccessToken()` method rather than shadowing it with the refresh-token string.

Do not invent a write endpoint for replying to an existing conversation. Verify the endpoint/payload before sending anything from a real account.

### Application sync

`app/wg_service.py`

The service:

- restores/validates a stored WG-Gesucht session;
- falls back to login from environment variables;
- persists the session in the configured `.data` path;
- loads conversation pages/details;
- extracts message text;
- extracts explicit structured profile metadata;
- computes review/completeness signals;
- upserts candidates.

Important known limitations are listed below.

### Review signals

`app/matching.py`

This is intentionally evidence/completeness-oriented, not a tenant-fit model.

Current signal categories include shared WG life, cleanliness/shared chores, privacy/boundaries, reliability/communication, social life, and viewing/move-in logistics.

Application detail currently includes sparse/medium/detailed-style classification, word count, covered topics, and availability-only detection.

Keep this transparent. Prefer showing evidence excerpts over opaque scores.

### Candidate persistence

`app/candidates_store.py`

Candidate application text is encrypted at rest using the app secret. Legacy plaintext fields may still exist for migration compatibility.

The default queue currently orders by application completeness signals rather than sensitive profile data. Preserve that constraint.

### Database

`app/db.py`

SQLite is used for the MVP.

Calendar OAuth token payloads and applicant application text are encrypted server-side using a key derived from `APP_SECRET_KEY`.

Do not expose provider tokens to browser JavaScript.

### Calendar providers

`app/calendars.py`

Implemented providers:

- Google Calendar OAuth + free/busy + event creation + Google Meet request;
- Microsoft/Outlook OAuth + calendar availability + event creation + Teams online-meeting request.

Each person connects their own account. Do not connect the developer/user's personal calendar through ChatGPT or through a shared server login.

### Calendar invites

`app/main.py`

The app can generate signed participant-specific calendar-connect links for roommate/applicant/guest roles. The participant opens the link and performs Google/Microsoft OAuth themselves.

### Scheduler

`app/scheduler.py`

Combines busy intervals and proposes common slots. Default scheduling timezone is `Europe/Berlin`.

Input datetimes should remain timezone-aware. Add validation/tests rather than silently guessing time zones.

## Highest-priority next work

### 1. Make WG-Gesucht ingestion trustworthy

This is the most important backend correctness task.

Current message extraction walks generic `content/message/text/body` fields recursively. It may accidentally combine both the applicant's messages and the WG's own replies.

Fix this by inspecting the real conversation-detail payload and identifying sender/user IDs. Only applicant-authored messages should feed application-completeness/WG-topic extraction.

Also verify that `display_name` and explicit profile facts come from the applicant object, not an unrelated nested object.

Add representative fixture data with personal details removed and unit tests for extraction.

### 2. Restrict sync to the correct room/listing

The current sync may read unrelated historic conversations.

Add a configured target listing/offer identifier (for example `WG_OFFER_ID`) or otherwise reliably identify which conversation belongs to the sublet being managed.

If a target listing is not configured, fail safely or show a very obvious warning rather than quietly importing unrelated conversations.

### 3. Build the viewing scheduler UI

Target workflow:

1. open candidate;
2. choose participating roommates/calendars;
3. choose date range and duration;
4. request common free slots;
5. select online vs in-person;
6. choose a slot;
7. create one organizer event and invite the applicant/other participants;
8. display Meet/Teams/location details.

Do not require the applicant to connect a calendar if an ordinary calendar/email invitation is enough. Calendar connection should be optional for applicants who want availability matching.

### 4. Add real app authentication before Internet exposure

The current MVP admin dashboard/API is not suitable for public deployment without authentication/authorization.

Protect at least:

- applicant list and application text;
- WG sync;
- shortlist/interview/pass actions;
- calendar connection inventory;
- calendar invite creation;
- appointment creation.

Signed calendar invite links are useful but are not a substitute for admin authentication.

### 5. Add tests and CI

At minimum add unit tests for:

- completeness classification;
- `availability_only` detection;
- profile metadata extraction without inference;
- applicant-only message extraction;
- target-listing filtering;
- scheduler overlap/common-slot logic;
- signed invite/state expiry and tamper detection;
- encryption/decryption round trips;
- token refresh behavior with mocked providers.

Add a simple GitHub Actions workflow for Python syntax/tests.

## Important secondary work

### Communication with applicants

The product ultimately needs replying to existing WG-Gesucht conversations.

The current fork does not document a reliable reply endpoint. Research/verify it before implementation. Until then, a draft/copy-to-clipboard workflow is safer than guessing a network endpoint.

### Apple Calendar

Not implemented yet.

Investigate the current Apple/iCloud Calendar integration options before coding. Apple should not be forced into the Google/Microsoft OAuth abstraction if the authentication model is materially different.

A CalDAV-based option may require an app-specific password and therefore needs careful credential handling. A read-only ICS approach is simpler but may not satisfy free/busy + event-creation requirements.

### Candidate data retention/privacy

Minimize stored applicant data. Consider:

- retention/expiry after the sublet decision is complete;
- deleting rejected/old candidate data;
- not storing unnecessary full WG-Gesucht payloads;
- access logging if the app becomes multi-user;
- keeping application text encrypted at rest.

## Known issues / things to inspect before trusting production data

- Generic recursive message extraction may include roommate-authored messages.
- Conversation sync may include unrelated listings/conversations.
- Generic recursive `_first_value` profile/name lookup can choose the wrong nested value if the payload contains multiple people.
- The application UI is still a single server-rendered HTML/JS page; acceptable for MVP but likely to become unwieldy.
- No proper admin authentication/authorization yet.
- Existing-conversation WG-Gesucht reply is not implemented/verified.
- Apple Calendar is not implemented.
- Provider APIs and unofficial WG-Gesucht endpoints may change.
- Tests/CI need to be added/expanded.

## Coding preferences for this MVP

- Keep it boring and inspectable: FastAPI + SQLite is fine.
- Prefer small pure functions for payload parsing and scheduling logic.
- Use fixtures/mocks for external APIs in tests. Never run destructive tests against the real WG-Gesucht account or real calendars.
- Preserve timezone-aware datetimes throughout scheduling.
- Preserve provider refresh tokens when OAuth refresh responses omit a new refresh token.
- Use OAuth authorization-code flows server-side; never put provider client secrets in browser code.
- Do not log credentials, OAuth tokens, session blobs, application text, or signed invite tokens.
- Escape user-controlled content in HTML.
- Validate redirect URLs and state tokens.
- Avoid silently swallowing external API errors; surface actionable messages to the admin UI.
- Keep migrations backward-compatible with existing local SQLite data when practical.

## Environment variables

See `.env.example`. The important settings currently include:

```dotenv
WG_GESUCHT_EMAIL=
WG_GESUCHT_PASSWORD=
WG_SESSION_FILE=.data/wg_session.json

APP_SECRET_KEY=
DATABASE_PATH=.data/wg_review.sqlite3
APP_BASE_URL=http://127.0.0.1:8000

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/calendar/google/callback

MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REDIRECT_URI=http://127.0.0.1:8000/api/calendar/microsoft/callback
```

If implementing listing scoping, add/document a setting such as:

```dotenv
WG_OFFER_ID=
```

## Local development checklist

Before using real accounts:

```bash
python -m compileall app core
# run tests once a test suite exists
# pytest
```

Then start:

```bash
uvicorn app.main:app --reload
```

For Google/Microsoft OAuth on a deployed environment, use HTTPS and configure the exact callback URLs in the provider console to match `APP_BASE_URL`/redirect settings.

## Definition of a good next iteration

A strong next iteration should let the WG safely do the following end to end:

1. sync only conversations for the intended sublet;
2. see only applicant-authored application content;
3. quickly distinguish substantive applications from low-information messages;
4. see explicit profile metadata and evidence in a clear review card;
5. manually decide who to contact/interview;
6. select roommates for a viewing;
7. calculate common available slots;
8. create an in-person or Meet/Teams appointment;
9. keep applicant/calendar secrets out of the client and out of git.

Prioritize correctness, privacy, and a usable end-to-end path over adding more scoring heuristics.