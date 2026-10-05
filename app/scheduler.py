from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from .calendars import provider_for
from .config import get_settings
from .db import get_calendar_connection, update_calendar_tokens


def _parse_dt(value: str) -> datetime:
    value = value.replace('Z', '+00:00')
    return datetime.fromisoformat(value)


def find_common_slots(
    connection_ids: list[str],
    start: datetime,
    end: datetime,
    *,
    duration_minutes: int = 30,
    step_minutes: int = 30,
    timezone_name: str = 'Europe/Berlin',
    day_start: time = time(9, 0),
    day_end: time = time(21, 0),
    limit: int = 30,
) -> list[dict[str, str]]:
    if not connection_ids:
        return []
    settings = get_settings()
    all_busy: list[tuple[datetime, datetime]] = []
    for connection_id in connection_ids:
        connection = get_calendar_connection(connection_id)
        if not connection:
            raise ValueError(f'Calendar connection not found: {connection_id}')
        provider = provider_for(connection['provider'], settings)
        token = provider.ensure_token(connection['token_data'])
        if token != connection['token_data']:
            update_calendar_tokens(connection_id, token)
        for interval in provider.busy(token, start, end):
            all_busy.append((_parse_dt(interval['start']), _parse_dt(interval['end'])))

    tz = ZoneInfo(timezone_name)
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    cursor = start.astimezone(tz)
    boundary = end.astimezone(tz)
    slots: list[dict[str, str]] = []

    while cursor + duration <= boundary and len(slots) < limit:
        local_end = cursor + duration
        within_hours = day_start <= cursor.timetz().replace(tzinfo=None) and local_end.timetz().replace(tzinfo=None) <= day_end
        same_day = cursor.date() == local_end.date()
        if within_hours and same_day:
            slot_start = cursor.astimezone(start.tzinfo)
            slot_end = local_end.astimezone(start.tzinfo)
            overlap = any(slot_start < busy_end and slot_end > busy_start for busy_start, busy_end in all_busy)
            if not overlap:
                slots.append({'start': slot_start.isoformat(), 'end': slot_end.isoformat()})
        cursor += step
    return slots
