"""Home Assistant entry point for the Custody Schedule integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.calendar import CalendarEntityFeature
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_CALENDAR_SYNC,
    CONF_CALENDAR_SYNC_INTERVAL_HOURS,
    CONF_CALENDAR_SYNC_DAYS,
    CONF_CALENDAR_TARGET,
    CONF_EXCEPTIONS_LIST,
    CONF_EXCEPTIONS_RECURRING,
    CONF_HOLIDAY_API_URL,
    CONF_LOCATION,
    CONF_REFERENCE_YEAR,
    CONF_REFERENCE_YEAR_CUSTODY,
    CONF_REFERENCE_YEAR_VACATIONS,
    DOMAIN,
    HOLIDAY_API,
    LOGGER,
    PLATFORMS,
    SERVICE_OVERRIDE_PRESENCE,
    SERVICE_REFRESH_SCHEDULE,
    SERVICE_SET_MANUAL_DATES,
    SERVICE_TEST_HOLIDAY_API,
    SERVICE_EXPORT_EXCEPTIONS,
    SERVICE_IMPORT_EXCEPTIONS,
    SERVICE_PURGE_CALENDAR,
    UPDATE_INTERVAL,
)
from .schedule import CustodyComputation, CustodyScheduleManager
from .school_holidays import SchoolHolidayClient


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (YAML not supported, placeholder only)."""
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("services_registered"):
        _register_services(hass)
        hass.data[DOMAIN]["services_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Custody Schedule from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = {**entry.data, **(entry.options or {})}
    config = _migrate_reference_years(hass, entry, config)
    api_url = config.get(CONF_HOLIDAY_API_URL) or HOLIDAY_API
    
    # Store clients by API URL to support multiple entries with different API URLs
    # Multiple entries can share the same client if they use the same API URL (benefits from shared cache)
    holiday_clients: dict[str, SchoolHolidayClient] = hass.data[DOMAIN].setdefault("holiday_clients", {})
    
    if api_url not in holiday_clients:
        holiday_clients[api_url] = SchoolHolidayClient(hass, api_url)
        LOGGER.debug("Created new holiday client for API URL: %s", api_url)
    
    holidays = holiday_clients[api_url]
    
    manager = CustodyScheduleManager(hass, config, holidays)
    _apply_manual_exceptions(manager, config)
    coordinator = CustodyScheduleCoordinator(hass, manager, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "manager": manager,
    }

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle entry removal by purging synced calendar events."""
    config = {**entry.data, **(entry.options or {})}
    child_label = config.get(CONF_CHILD_NAME_DISPLAY, config.get(CONF_CHILD_NAME, ""))
    match_text = child_label or ""
    await _async_purge_calendar_events(
        hass,
        entry.entry_id,
        config,
        include_unmarked=True,
        purge_all=False,
        days=3650,
        match_text=match_text,
        debug=True,
        raise_on_error=False,
        log_context="entry removal",
    )


def _apply_manual_exceptions(manager: CustodyScheduleManager, config: dict[str, Any]) -> None:
    exceptions = config.get(CONF_EXCEPTIONS_LIST)
    if isinstance(exceptions, list) and exceptions:
        manager.set_manual_windows(exceptions)


class CustodyScheduleCoordinator(DataUpdateCoordinator[CustodyComputation]):
    """Coordinator that keeps the schedule state up to date."""

    def __init__(self, hass: HomeAssistant, manager: CustodyScheduleManager, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.manager = manager
        self.entry = entry
        self._last_state: CustodyComputation | None = None
        self._calendar_sync_lock = asyncio.Lock()
        self._last_calendar_sync: datetime | None = None

    async def _async_update_data(self) -> CustodyComputation:
        """Fetch data from the schedule manager."""
        try:
            state = await self.manager.async_calculate(dt_util.now())
        except Exception as err:
            raise UpdateFailed(f"Unable to compute custody schedule: {err}") from err

        self._fire_events(state)
        await self._maybe_sync_calendar(state)
        self._last_state = state
        return state

    def _fire_events(self, new_state: CustodyComputation) -> None:
        """Emit Home Assistant events when key transitions happen."""
        if self._last_state is None:
            return

        last = self._last_state
        child_label = self.entry.data.get(CONF_CHILD_NAME_DISPLAY, self.entry.data.get(CONF_CHILD_NAME))
        if last.is_present != new_state.is_present:
            event = "custody_arrival" if new_state.is_present else "custody_departure"
            self.hass.bus.async_fire(
                event,
                {
                    "entry_id": self.entry.entry_id,
                    "child": child_label,
                    "next_departure": new_state.next_departure.isoformat() if new_state.next_departure else None,
                    "next_arrival": new_state.next_arrival.isoformat() if new_state.next_arrival else None,
                },
            )

        if last.current_period != new_state.current_period and new_state.current_period == "vacation":
            self.hass.bus.async_fire(
                "custody_vacation_start",
                {
                    "entry_id": self.entry.entry_id,
                    "holiday": new_state.vacation_name,
                },
            )
        elif last.current_period != new_state.current_period and new_state.current_period == "school":
            self.hass.bus.async_fire(
                "custody_vacation_end",
                {
                    "entry_id": self.entry.entry_id,
                    "holiday": last.vacation_name,
                },
            )

    async def _maybe_sync_calendar(self, state: CustodyComputation) -> None:
        """Sync custody windows to an external calendar if enabled."""
        config = {**self.entry.data, **(self.entry.options or {})}
        if not config.get(CONF_CALENDAR_SYNC):
            LOGGER.debug("Calendar sync disabled for entry %s", self.entry.entry_id)
            return
        target = _normalize_calendar_target(config.get(CONF_CALENDAR_TARGET))
        if not target:
            LOGGER.warning("Calendar sync enabled but no target calendar selected.")
            return
        LOGGER.debug("Calendar sync target resolved: %s (entry %s)", target, self.entry.entry_id)

        now = dt_util.now()
        interval_hours = config.get(CONF_CALENDAR_SYNC_INTERVAL_HOURS, 1)
        try:
            interval_hours = int(interval_hours)
        except (TypeError, ValueError):
            interval_hours = 1
        interval_hours = max(1, min(24, interval_hours))

        if self._last_calendar_sync and now - self._last_calendar_sync < timedelta(hours=interval_hours):
            LOGGER.debug(
                "Calendar sync skipped (interval). Last sync: %s, interval: %sh",
                self._last_calendar_sync,
                interval_hours,
            )
            return

        async with self._calendar_sync_lock:
            now = dt_util.now()
            if self._last_calendar_sync and now - self._last_calendar_sync < timedelta(hours=interval_hours):
                LOGGER.debug(
                    "Calendar sync skipped inside lock (interval). Last sync: %s, interval: %sh",
                    self._last_calendar_sync,
                    interval_hours,
                )
                return
            try:
                if not self.hass.services.has_service("calendar", "get_events"):
                    LOGGER.warning("Calendar sync skipped: calendar.get_events not available.")
                    return
                LOGGER.debug("Calendar sync starting for %s", target)
                await _sync_calendar_events(self.hass, target, state, config, self.entry.entry_id)
                LOGGER.debug("Calendar sync completed for %s", target)
                self._last_calendar_sync = now
            except Exception as err:
                LOGGER.warning("Calendar sync failed for %s: %s", target, err)


def _event_key(summary: str, start: str, end: str) -> tuple[str, str, str]:
    return summary, start, end


def _normalize_calendar_target(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("entity_id") or value.get("value") or value.get("id")
    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = _normalize_calendar_target(item)
            if normalized:
                return normalized
    return None


def _normalize_event_datetime(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date")
    elif isinstance(value, str):
        # Keep raw string for parsing below.
        pass
    elif hasattr(value, "get"):
        try:
            value = value.get("dateTime") or value.get("date")
        except Exception:
            LOGGER.debug("Calendar event datetime get() failed: %s (%s)", value, type(value).__name__)
            return None
    else:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(value).isoformat()
    if isinstance(value, date):
        return dt_util.as_utc(
            datetime.combine(value, datetime.min.time(), tzinfo=dt_util.DEFAULT_TIME_ZONE)
        ).isoformat()
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt_util.as_utc(parsed).isoformat()
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            return None
        return dt_util.as_utc(
            datetime.combine(parsed_date, datetime.min.time(), tzinfo=dt_util.DEFAULT_TIME_ZONE)
        ).isoformat()
    return None


def _ensure_local_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(value)


def _calendar_marker(entry_id: str) -> str:
    return f"custody_schedule:{entry_id}"


def _matches_marker(event: dict[str, Any], marker: str) -> bool:
    if not isinstance(event, dict):
        return False
    description = event.get("description") or ""
    if marker and marker in description:
        return True
    # Backward compatibility for events created before marker was added
    return "Planning de garde" in description


def _extract_event_id(event: dict[str, Any]) -> str | None:
    """Extract event ID/UID for backward compatibility."""
    uid, _ = _extract_event_uid_and_recurrence(event)
    return uid


def _extract_event_uid_and_recurrence(event: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract UID and recurrence_id from a calendar event.
    
    Based on Google Calendar implementation:
    - uid should be event.ical_uuid (from CalendarEvent)
    - recurrence_id should be event.id if it's a recurring event
    
    Returns:
        Tuple of (uid, recurrence_id) where either can be None
    """
    uid = None
    recurrence_id = None
    
    # Google Calendar uses ical_uuid as the UID
    # Try direct uid field first (CalendarEvent format)
    raw_uid = event.get("uid")
    if isinstance(raw_uid, str) and raw_uid:
        uid = raw_uid
    elif isinstance(raw_uid, dict):
        for key in ("uid", "value", "text", "id", "ical_uuid"):
            value = raw_uid.get(key)
            if isinstance(value, str) and value:
                uid = value
                break
    
    # Try ical_uuid directly (Google Calendar internal format)
    if not uid:
        raw_ical = event.get("ical_uuid") or event.get("icalUuid")
        if isinstance(raw_ical, str) and raw_ical:
            uid = raw_ical
        elif isinstance(raw_ical, dict):
            for key in ("value", "text", "uid", "id"):
                value = raw_ical.get(key)
                if isinstance(value, str) and value:
                    uid = value
                    break
    
    # Try alternative UID fields (various formats)
    if not uid:
        for key in ("id", "event_id", "iCalUID", "ical_uid", "iCalUid", "icalUuid"):
            value = event.get(key)
            if isinstance(value, str) and value:
                uid = value
                break
            elif isinstance(value, dict):
                for nested in ("value", "text", "uid", "id", "ical_uuid"):
                    nested_val = value.get(nested)
                    if isinstance(nested_val, str) and nested_val:
                        uid = nested_val
                        break
                if uid:
                    break
    
    # Extract recurrence_id if present
    # Google Calendar uses event.id for recurring events
    raw_recurrence = event.get("recurrence_id") or event.get("recurrenceId") or event.get("recurring_event_id")
    if isinstance(raw_recurrence, str) and raw_recurrence:
        recurrence_id = raw_recurrence
    elif isinstance(raw_recurrence, dict):
        for key in ("value", "text", "id"):
            value = raw_recurrence.get(key)
            if isinstance(value, str) and value:
                recurrence_id = value
                break
    
    # If event has recurring_event_id, use event.id as recurrence_id
    if event.get("recurring_event_id") and not recurrence_id:
        raw_id = event.get("id")
        if isinstance(raw_id, str) and raw_id:
            recurrence_id = raw_id
    
    return uid, recurrence_id


def _get_calendar_delete_service(hass: HomeAssistant) -> str | None:
    for service in ("delete_event", "remove_event"):
        if hass.services.has_service("calendar", service):
            return service
    return None


async def _delete_calendar_event_direct(
    hass: HomeAssistant, entity_id: str, uid: str, recurrence_id: str | None = None
) -> bool:
    """Delete a calendar event by accessing the entity directly.
    
    Args:
        hass: Home Assistant instance
        entity_id: Calendar entity ID (e.g., calendar.jacky_niglio_gmail_com)
        uid: Event UID (required)
        recurrence_id: Optional recurrence ID for recurring events
    """
    try:
        state = hass.states.get(entity_id)
        if not state:
            LOGGER.debug("Entity %s not found in states", entity_id)
            return False

        entity = None
        
        # Method 1: Try entity_platform
        platform_data = hass.data.get("entity_platform", {})
        if isinstance(platform_data, dict):
            calendar_platform = platform_data.get("calendar")
            if calendar_platform and hasattr(calendar_platform, "entities"):
                entity = calendar_platform.entities.get(entity_id)
        
        # Method 2: Try entity registry to find the entity
        if not entity:
            registry = er.async_get(hass)
            entity_entry = registry.async_get(entity_id)
            if entity_entry:
                # Try to get entity from platform using registry info
                platform_data = hass.data.get("entity_platform", {})
                if isinstance(platform_data, dict):
                    calendar_platform = platform_data.get("calendar")
                    if calendar_platform and hasattr(calendar_platform, "entities"):
                        # Try both entity_id and unique_id
                        for eid, ent in calendar_platform.entities.items():
                            if eid == entity_id or (hasattr(ent, "unique_id") and ent.unique_id == entity_entry.unique_id):
                                entity = ent
                                break
        
        # Method 3: Try to find by domain
        if not entity:
            platform_data = hass.data.get("entity_platform", {})
            if isinstance(platform_data, dict):
                calendar_platform = platform_data.get("calendar")
                if calendar_platform and hasattr(calendar_platform, "entities"):
                    # Last resort: search all calendar entities
                    for eid, ent in calendar_platform.entities.items():
                        if eid == entity_id:
                            entity = ent
                            break

        if not entity:
            LOGGER.debug("Calendar entity %s not found in platform", entity_id)
            return False

        if not hasattr(entity, "async_delete_event"):
            LOGGER.debug("Entity %s does not have async_delete_event method", entity_id)
            return False

        if hasattr(entity, "supported_features"):
            if not (entity.supported_features & CalendarEntityFeature.DELETE_EVENT):
                LOGGER.debug("Entity %s does not support DELETE_EVENT feature", entity_id)
                return False

        LOGGER.debug("Deleting event uid=%s recurrence_id=%s from %s", uid, recurrence_id, entity_id)
        await entity.async_delete_event(uid, recurrence_id=recurrence_id)
        LOGGER.info("Successfully deleted event uid=%s from %s", uid, entity_id)
        return True
    except Exception as err:
        LOGGER.warning("Direct entity delete failed for %s (uid=%s): %s", entity_id, uid, err, exc_info=True)
        return False


async def _sync_calendar_events(
    hass: HomeAssistant,
    target: str,
    state: CustodyComputation,
    config: dict[str, Any],
    entry_id: str,
) -> None:
    """Create, update, and delete custody events in the target calendar."""
    if not hass.services.has_service("calendar", "get_events") or not hass.services.has_service(
        "calendar", "create_event"
    ):
        LOGGER.debug("Calendar services not available, skipping sync.")
        return

    now = dt_util.now()
    days = config.get(CONF_CALENDAR_SYNC_DAYS, 120)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 120
    days = max(7, min(365, days))
    start_range = _ensure_local_tz(now - timedelta(days=1))
    end_range = _ensure_local_tz(now + timedelta(days=days))

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": target,
            "start_date_time": start_range.isoformat(),
            "end_date_time": end_range.isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    LOGGER.debug("Calendar get_events response type: %s", type(response).__name__)

    events: list[Any] = []
    if isinstance(response, list):
        events = response
    elif isinstance(response, dict):
        if "events" in response:
            events = response.get("events") or []
        elif target in response:
            target_payload = response.get(target)
            if isinstance(target_payload, dict) and "events" in target_payload:
                events = target_payload.get("events") or []
            elif isinstance(target_payload, list):
                events = target_payload

    marker = _calendar_marker(entry_id)

    existing_keys: set[tuple[str, str, str]] = set()
    existing_events: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if marker and not _matches_marker(event, marker):
            continue
        summary = event.get("summary") or event.get("message") or ""
        start_val = _normalize_event_datetime(event.get("start"))
        end_val = _normalize_event_datetime(event.get("end"))
        if not summary or not start_val or not end_val:
            continue
        existing_keys.add(_event_key(summary, start_val, end_val))
        event["__key"] = _event_key(summary, start_val, end_val)
        existing_events.append(event)
    LOGGER.debug("Calendar sync: %d existing events after filtering", len(existing_events))

    child_label = config.get(CONF_CHILD_NAME_DISPLAY, config.get(CONF_CHILD_NAME, ""))
    location = config.get(CONF_LOCATION) or ""

    desired_keys: set[tuple[str, str, str]] = set()
    created = 0
    updated = 0
    for window in state.windows:
        if window.source == "vacation_filter":
            continue
        if window.end < start_range or window.start > end_range:
            continue
        summary = f"{child_label} - {window.label}".strip()
        start_val = _ensure_local_tz(window.start).isoformat()
        end_val = _ensure_local_tz(window.end).isoformat()
        key = _event_key(summary, start_val, end_val)
        desired_keys.add(key)
        if key not in existing_keys:
            await hass.services.async_call(
                "calendar",
                "create_event",
                {
                    "entity_id": target,
                    "summary": summary,
                    "start_date_time": start_val,
                    "end_date_time": end_val,
                    "description": f"{marker} Planning de garde ({window.source})",
                    "location": location,
                },
                blocking=True,
            )
            created += 1
        elif hass.services.has_service("calendar", "update_event"):
            # Update events if metadata changed (location/description)
            existing = next((ev for ev in existing_events if ev.get("__key") == key), None)
            if existing:
                event_id = _extract_event_id(existing)
                if event_id:
                    existing_desc = existing.get("description") or ""
                    existing_loc = existing.get("location") or ""
                    new_desc = f"{marker} Planning de garde ({window.source})"
                    if existing_desc != new_desc or existing_loc != location:
                        await hass.services.async_call(
                            "calendar",
                            "update_event",
                            {
                                "entity_id": target,
                                "event_id": event_id,
                                "summary": summary,
                                "start_date_time": start_val,
                                "end_date_time": end_val,
                                "description": new_desc,
                                "location": location,
                            },
                            blocking=True,
                        )
                        updated += 1

    # Delete events that no longer exist in the planning
    delete_service = _get_calendar_delete_service(hass)
    deleted = 0
    for event in existing_events:
        key = event.get("__key")
        if key in desired_keys:
            continue
        uid, recurrence_id = _extract_event_uid_and_recurrence(event)
        if not uid:
            continue
        if delete_service:
            try:
                await hass.services.async_call(
                    "calendar",
                    delete_service,
                    {"entity_id": target, "event_id": uid},
                    blocking=True,
                )
                deleted += 1
            except Exception as err:
                LOGGER.debug("Service delete failed in sync, trying direct entity: %s", err)
                if await _delete_calendar_event_direct(hass, target, uid, recurrence_id):
                    deleted += 1
        else:
            if await _delete_calendar_event_direct(hass, target, uid, recurrence_id):
                deleted += 1
    if deleted > 0:
        LOGGER.debug(
            "Calendar sync summary for %s: created=%d updated=%d deleted=%d",
            target,
            created,
            updated,
            deleted,
        )
        LOGGER.info(
            "Calendar sync result for %s: existing=%d desired=%d created=%d updated=%d deleted=%d",
            target,
            len(existing_events),
            len(desired_keys),
            created,
            updated,
            deleted,
        )
    if created == 0 and updated == 0 and deleted == 0:
        LOGGER.info(
            "Calendar sync for %s did not require changes (entries already aligned).",
            target,
        )


async def _async_purge_calendar_events(
    hass: HomeAssistant,
    entry_id: str,
    config: dict[str, Any],
    *,
    include_unmarked: bool,
    purge_all: bool,
    days: int | None,
    match_text: str | None,
    debug: bool,
    raise_on_error: bool,
    log_context: str | None = None,
) -> tuple[int, int, int]:
    context = f" ({log_context})" if log_context else ""
    target = _normalize_calendar_target(config.get(CONF_CALENDAR_TARGET))
    if not target:
        message = "No target calendar configured"
        if raise_on_error:
            raise HomeAssistantError(message)
        LOGGER.warning("Calendar purge skipped%s: %s", context, message)
        return 0, 0, 0
    if not hass.services.has_service("calendar", "get_events"):
        message = "calendar.get_events not available"
        if raise_on_error:
            raise HomeAssistantError(message)
        LOGGER.warning("Calendar purge skipped%s: %s", context, message)
        return 0, 0, 0

    now = dt_util.now()
    if days is None:
        days = config.get(CONF_CALENDAR_SYNC_DAYS, 120)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 120
    days = max(7, min(3650, days))
    start_range = _ensure_local_tz(now - timedelta(days=1))
    end_range = _ensure_local_tz(now + timedelta(days=days))

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": target,
            "start_date_time": start_range.isoformat(),
            "end_date_time": end_range.isoformat(),
        },
        blocking=True,
        return_response=True,
    )

    events: list[Any] = []
    if isinstance(response, list):
        events = response
    elif isinstance(response, dict):
        if "events" in response:
            events = response.get("events") or []
        elif target in response:
            target_payload = response.get(target)
            if isinstance(target_payload, dict) and "events" in target_payload:
                events = target_payload.get("events") or []
            elif isinstance(target_payload, list):
                events = target_payload

    marker = _calendar_marker(entry_id)
    child_label = config.get(CONF_CHILD_NAME_DISPLAY, config.get(CONF_CHILD_NAME, ""))
    summary_prefix = f"{child_label} - " if child_label else ""
    match_text = str(match_text or "").strip()
    match_text_lower = match_text.lower() if match_text else ""
    child_label_lower = child_label.lower() if child_label else ""
    deleted = 0
    matched = 0
    missing_id = 0
    delete_service = _get_calendar_delete_service(hass)
    if not delete_service:
        LOGGER.debug(
            "Calendar purge: no delete service available, will try direct entity access%s",
            context,
        )

    def _truncate(value: str, limit: int = 120) -> str:
        value = value.replace("\n", " ").strip()
        return value if len(value) <= limit else f"{value[:limit]}..."

    stats = {
        "with_summary": 0,
        "with_description": 0,
        "with_event_id": 0,
        "marker": 0,
        "legacy": 0,
        "prefix": 0,
        "label": 0,
        "text": 0,
    }
    debug_matches: list[str] = []
    debug_misses: list[str] = []

    if debug and events:
        sample_event = events[0] if isinstance(events[0], dict) else {}
        LOGGER.info(
            "Purge debug%s: sample event keys=%s",
            context,
            ", ".join(sorted(sample_event.keys())) if isinstance(sample_event, dict) else "not a dict",
        )
        if isinstance(sample_event, dict):
            import json
            sample_str = json.dumps(sample_event, default=str, indent=2)
            if len(sample_str) > 500:
                sample_str = sample_str[:500] + "..."
            LOGGER.info("Purge debug%s: sample event structure:\n%s", context, sample_str)
            # Also check UID extraction
            sample_uid, sample_recurrence = _extract_event_uid_and_recurrence(sample_event)
            LOGGER.info(
                "Purge debug%s: extracted uid=%s recurrence_id=%s from sample",
                context,
                sample_uid,
                sample_recurrence,
            )

    for event in events:
        if not isinstance(event, dict):
            continue
        summary = event.get("summary") or event.get("message") or ""
        description = event.get("description") or ""
        uid, recurrence_id = _extract_event_uid_and_recurrence(event)
        event_id = uid  # Keep for backward compatibility in stats
        if summary:
            stats["with_summary"] += 1
        if description:
            stats["with_description"] += 1
        if uid:
            stats["with_event_id"] += 1

        marker_match = bool(marker and marker in description)
        legacy_match = "Planning de garde" in description
        prefix_match = bool(include_unmarked and summary_prefix and summary.startswith(summary_prefix))
        label_match = bool(include_unmarked and child_label_lower and child_label_lower in summary.lower())
        text_match = bool(match_text_lower and match_text_lower in summary.lower())

        if marker_match:
            stats["marker"] += 1
        if legacy_match:
            stats["legacy"] += 1
        if prefix_match:
            stats["prefix"] += 1
        if label_match:
            stats["label"] += 1
        if text_match:
            stats["text"] += 1

        if purge_all:
            matches = True
        else:
            matches = marker_match or legacy_match or prefix_match or label_match or text_match

        if matches:
            matched += 1
            if not uid:
                missing_id += 1
                if debug and len(debug_matches) < 10:
                    all_keys = ", ".join(sorted(event.keys())) if isinstance(event, dict) else "not a dict"
                    debug_matches.append(
                        f"summary='{_truncate(summary)}' uid=None recurrence_id={recurrence_id} "
                        f"all_keys=[{all_keys}] desc='{_truncate(description)}'"
                    )
                continue
            if debug and len(debug_matches) < 10:
                debug_matches.append(
                    f"summary='{_truncate(summary)}' uid='{uid}' recurrence_id={recurrence_id} "
                    f"marker={marker_match} legacy={legacy_match} prefix={prefix_match} "
                    f"label={label_match} text={text_match} desc='{_truncate(description)}'"
                )
            if delete_service:
                try:
                    await hass.services.async_call(
                        "calendar",
                        delete_service,
                        {"entity_id": target, "event_id": uid},
                        blocking=True,
                    )
                    deleted += 1
                except Exception as err:
                    LOGGER.debug("Service delete failed, trying direct entity: %s", err)
                    if await _delete_calendar_event_direct(hass, target, uid, recurrence_id):
                        deleted += 1
            else:
                if await _delete_calendar_event_direct(hass, target, uid, recurrence_id):
                    deleted += 1
        else:
            if debug and len(debug_misses) < 10:
                debug_misses.append(
                    f"summary='{_truncate(summary)}' uid='{uid}' recurrence_id={recurrence_id} "
                    f"marker={marker_match} legacy={legacy_match} prefix={prefix_match} "
                    f"label={label_match} text={text_match}"
                )

    LOGGER.info(
        "Purged %d custody events from %s (purge_all=%s, include_unmarked=%s, days=%s, match_text=%s)%s",
        deleted,
        target,
        purge_all,
        include_unmarked,
        days,
        match_text if match_text else None,
        context,
    )
    if deleted == 0:
        LOGGER.info(
            "Purge completed with no deletions (matched=%d, events=%d).%s",
            matched,
            len(events),
            context,
        )
    if missing_id:
        LOGGER.info("Purge skipped %d matched events without ids.%s", missing_id, context)
    if not delete_service and matched and deleted == 0:
        LOGGER.warning(
            "Purge found %d matching events but could not delete any%s (tried direct entity access).",
            matched,
            context,
        )
    if debug:
        calendar_services = hass.services.async_services().get("calendar", {})
        LOGGER.info(
            "Purge debug%s: total=%d summary=%d desc=%d ids=%d marker=%d legacy=%d "
            "prefix=%d label=%d text=%d",
            context,
            len(events),
            stats["with_summary"],
            stats["with_description"],
            stats["with_event_id"],
            stats["marker"],
            stats["legacy"],
            stats["prefix"],
            stats["label"],
            stats["text"],
        )
        LOGGER.info(
            "Purge debug%s: delete_service=%s calendar_services=%s",
            context,
            delete_service,
            ", ".join(sorted(calendar_services.keys())) if calendar_services else "none",
        )
        for line in debug_matches:
            LOGGER.info("Purge debug match%s: %s", context, line)
        for line in debug_misses:
            LOGGER.info("Purge debug miss%s: %s", context, line)

    return deleted, matched, len(events)


def _migrate_reference_years(
    hass: HomeAssistant, entry: ConfigEntry, config: dict[str, Any]
) -> dict[str, Any]:
    """Backfill split reference year keys from legacy config if needed."""
    legacy = config.get(CONF_REFERENCE_YEAR)
    custody_year = config.get(CONF_REFERENCE_YEAR_CUSTODY)
    vacations_year = config.get(CONF_REFERENCE_YEAR_VACATIONS)

    if legacy and (custody_year is None or vacations_year is None):
        updated = dict(entry.data)
        if custody_year is None:
            updated[CONF_REFERENCE_YEAR_CUSTODY] = legacy
        if vacations_year is None:
            updated[CONF_REFERENCE_YEAR_VACATIONS] = legacy
        hass.config_entries.async_update_entry(entry, data=updated)
        return {**updated, **(entry.options or {})}

    return config

def _register_services(hass: HomeAssistant) -> None:
    """Register services exposed by the integration."""

    def _get_manager(entry_id: str) -> tuple[CustodyScheduleCoordinator, CustodyScheduleManager]:
        entry_data = hass.data[DOMAIN].get(entry_id)
        if not entry_data:
            raise HomeAssistantError(f"No custody schedule found for entry_id {entry_id}")
        return entry_data["coordinator"], entry_data["manager"]

    def _get_entry(entry_id: str) -> ConfigEntry:
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            raise HomeAssistantError(f"No custody schedule found for entry_id {entry_id}")
        return entry

    async def _async_handle_manual_dates(call: ServiceCall) -> None:
        coordinator, manager = _get_manager(call.data["entry_id"])
        manager.set_manual_windows(call.data["dates"])
        await coordinator.async_request_refresh()

    async def _async_handle_override(call: ServiceCall) -> None:
        coordinator, manager = _get_manager(call.data["entry_id"])
        duration = call.data.get("duration")
        duration_td = timedelta(minutes=duration) if duration else None
        manager.override_presence(call.data["state"], duration_td)
        await coordinator.async_request_refresh()

    async def _async_handle_refresh(call: ServiceCall) -> None:
        coordinator, _ = _get_manager(call.data["entry_id"])
        await coordinator.async_request_refresh()

    async def _async_handle_export_exceptions(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        entry = _get_entry(entry_id)
        config = {**entry.data, **(entry.options or {})}
        payload = {
            "exceptions": config.get(CONF_EXCEPTIONS_LIST, []),
            "recurring": config.get(CONF_EXCEPTIONS_RECURRING, []),
        }

        filename = call.data.get("filename")
        www_dir = Path(hass.config.path("www")).resolve(strict=False)
        if filename:
            filename = str(filename).strip()
            if filename.startswith("/config/www/"):
                target = Path(filename)
            elif filename.startswith("www/"):
                target = www_dir / filename[4:]
            else:
                target = www_dir / filename
        else:
            target = www_dir / f"custody_exceptions_{entry_id}.json"
        target = target.resolve(strict=False)
        if www_dir not in target.parents and target != www_dir:
            raise HomeAssistantError("Filename must be under /config/www")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        LOGGER.info("Exceptions exported to %s", target)

    async def _async_handle_import_exceptions(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        entry = _get_entry(entry_id)
        payload = None

        if "exceptions" in call.data or "recurring" in call.data:
            payload = {
                "exceptions": call.data.get("exceptions") or [],
                "recurring": call.data.get("recurring") or [],
            }
        elif filename := call.data.get("filename"):
            www_dir = Path(hass.config.path("www")).resolve(strict=False)
            filename = str(filename).strip()
            if filename.startswith("/config/www/"):
                target = Path(filename)
            elif filename.startswith("www/"):
                target = www_dir / filename[4:]
            else:
                target = www_dir / filename
            target = target.resolve(strict=False)
            if www_dir not in target.parents and target != www_dir:
                raise HomeAssistantError("Filename must be under /config/www")
            if not target.exists():
                raise HomeAssistantError("File not found")
            payload = json.loads(target.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            raise HomeAssistantError("Invalid payload")

        exceptions = payload.get("exceptions", [])
        recurring = payload.get("recurring", [])
        if not isinstance(exceptions, list) or not isinstance(recurring, list):
            raise HomeAssistantError("Invalid exceptions format")

        options = {**(entry.options or {})}
        options[CONF_EXCEPTIONS_LIST] = exceptions
        options[CONF_EXCEPTIONS_RECURRING] = recurring
        hass.config_entries.async_update_entry(entry, options=options)
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MANUAL_DATES,
        _async_handle_manual_dates,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): cv.string,
                vol.Required("dates"): vol.All(
                    cv.ensure_list,
                    [
                        vol.Schema(
                            {
                                "start": cv.datetime,
                                "end": cv.datetime,
                                vol.Optional("label"): cv.string,
                            }
                        )
                    ],
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_OVERRIDE_PRESENCE,
        _async_handle_override,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): cv.string,
                vol.Required("state"): vol.In(["on", "off"]),
                vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_SCHEDULE,
        _async_handle_refresh,
        schema=vol.Schema({vol.Required("entry_id"): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_EXCEPTIONS,
        _async_handle_export_exceptions,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): cv.string,
                vol.Optional("filename"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_EXCEPTIONS,
        _async_handle_import_exceptions,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): cv.string,
                vol.Optional("filename"): cv.string,
                vol.Optional("exceptions"): list,
                vol.Optional("recurring"): list,
            }
        ),
    )

    async def _async_handle_purge_calendar(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        include_unmarked = bool(call.data.get("include_unmarked", False))
        purge_all = bool(call.data.get("purge_all", False))
        match_text = call.data.get("match_text")
        days = call.data.get("days")
        debug = bool(call.data.get("debug", False))
        entry = _get_entry(entry_id)
        config = {**entry.data, **(entry.options or {})}
        await _async_purge_calendar_events(
            hass,
            entry_id,
            config,
            include_unmarked=include_unmarked,
            purge_all=purge_all,
            days=days,
            match_text=match_text,
            debug=debug,
            raise_on_error=True,
            log_context="service",
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PURGE_CALENDAR,
        _async_handle_purge_calendar,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): cv.string,
                vol.Optional("include_unmarked", default=False): cv.boolean,
                vol.Optional("purge_all", default=False): cv.boolean,
                vol.Optional("days"): cv.positive_int,
                vol.Optional("match_text"): cv.string,
                vol.Optional("debug", default=False): cv.boolean,
            }
        ),
    )

    async def _async_handle_test_api(call: ServiceCall) -> None:
        """Test the holiday API connection."""
        entry_id = call.data.get("entry_id")
        zone = call.data.get("zone", "A")
        year = call.data.get("year")
        
        if entry_id:
            entry_data = hass.data[DOMAIN].get(entry_id)
            if not entry_data:
                raise HomeAssistantError(f"No custody schedule found for entry_id {entry_id}")
            config = {**entry_data["manager"]._config}
            api_url = config.get(CONF_HOLIDAY_API_URL) or HOLIDAY_API
        else:
            api_url = HOLIDAY_API
        
        # Use shared client if available, otherwise create a temporary one for testing
        holiday_clients: dict[str, SchoolHolidayClient] = hass.data[DOMAIN].get("holiday_clients", {})
        if api_url in holiday_clients:
            holidays = holiday_clients[api_url]
        else:
            holidays = SchoolHolidayClient(hass, api_url)
        
        result = await holidays.async_test_connection(zone, year)
        
        # Log the result
        if result["success"]:
            LOGGER.info(
                "API test successful: %d holidays found for zone %s, year %s",
                result["holidays_count"],
                zone,
                result["school_year"],
            )
        else:
            LOGGER.error("API test failed: %s", result.get("error"))
        
        # Store result in hass.data for potential UI display
        hass.data[DOMAIN]["last_api_test"] = result

    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_HOLIDAY_API,
        _async_handle_test_api,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): cv.string,
                vol.Optional("zone", default="A"): cv.string,
                vol.Optional("year"): cv.string,
            }
        ),
    )


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)