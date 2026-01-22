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
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.components import persistent_notification

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
    CONF_NOTIFICATIONS,
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
    SERVICE_EXPORT_PLANNING_PDF,
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
        config = {**self.entry.data, **(self.entry.options or {})}
        notifications_enabled = bool(config.get(CONF_NOTIFICATIONS))
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

            if notifications_enabled:
                next_dt = new_state.next_departure if new_state.is_present else new_state.next_arrival
                next_label = "depart" if new_state.is_present else "arrivee"
                formatted = (
                    dt_util.as_local(next_dt).strftime("%d/%m/%Y %H:%M") if next_dt else "inconnu"
                )
                title = f"{child_label} - Arrivee" if new_state.is_present else f"{child_label} - Depart"
                message = f"{child_label} est arrive" if new_state.is_present else f"{child_label} est parti"
                message = f"{message}. Prochain {next_label}: {formatted}"
                persistent_notification.async_create(
                    self.hass,
                    message,
                    title,
                    f"{DOMAIN}_{self.entry.entry_id}_{next_label}",
                )

        if last.current_period != new_state.current_period and new_state.current_period == "vacation":
            self.hass.bus.async_fire(
                "custody_vacation_start",
                {
                    "entry_id": self.entry.entry_id,
                    "holiday": new_state.vacation_name,
                },
            )

            if notifications_enabled:
                title = f"{child_label} - Vacances"
                holiday = new_state.vacation_name or "Vacances scolaires"
                message = f"Debut des vacances: {holiday}"
                persistent_notification.async_create(
                    self.hass,
                    message,
                    title,
                    f"{DOMAIN}_{self.entry.entry_id}_vacation_start",
                )
        elif last.current_period != new_state.current_period and new_state.current_period == "school":
            self.hass.bus.async_fire(
                "custody_vacation_end",
                {
                    "entry_id": self.entry.entry_id,
                    "holiday": last.vacation_name,
                },
            )

            if notifications_enabled:
                title = f"{child_label} - Fin vacances"
                holiday = last.vacation_name or "Vacances scolaires"
                message = f"Fin des vacances: {holiday}"
                persistent_notification.async_create(
                    self.hass,
                    message,
                    title,
                    f"{DOMAIN}_{self.entry.entry_id}_vacation_end",
                )

    async def _maybe_sync_calendar(self, state: CustodyComputation) -> None:
        """Sync custody windows to an external calendar if enabled."""
        config = {**self.entry.data, **(self.entry.options or {})}
        if not config.get(CONF_CALENDAR_SYNC):
            return
        target = config.get(CONF_CALENDAR_TARGET)
        if not target:
            return

        now = dt_util.now()
        interval_hours = config.get(CONF_CALENDAR_SYNC_INTERVAL_HOURS, 1)
        try:
            interval_hours = int(interval_hours)
        except (TypeError, ValueError):
            interval_hours = 1
        interval_hours = max(1, min(24, interval_hours))

        if self._last_calendar_sync and now - self._last_calendar_sync < timedelta(hours=interval_hours):
            return

        async with self._calendar_sync_lock:
            now = dt_util.now()
            if self._last_calendar_sync and now - self._last_calendar_sync < timedelta(hours=interval_hours):
                return
            self._last_calendar_sync = now
            try:
                await _sync_calendar_events(self.hass, target, state, config, self.entry.entry_id)
            except Exception as err:
                LOGGER.warning("Calendar sync failed for %s: %s", target, err)


def _event_key(summary: str, start: str, end: str) -> tuple[str, str, str]:
    return summary, start, end


def _normalize_event_datetime(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed:
            return parsed.isoformat()
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            return None
        return datetime.combine(parsed_date, datetime.min.time()).isoformat()
    return None


def _calendar_marker(entry_id: str) -> str:
    return f"custody_schedule:{entry_id}"


def _matches_marker(event: dict[str, Any], marker: str) -> bool:
    description = event.get("description") or ""
    if marker and marker in description:
        return True
    # Backward compatibility for events created before marker was added
    return "Planning de garde" in description


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
    start_range = now - timedelta(days=1)
    end_range = now + timedelta(days=days)

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

    events = []
    if isinstance(response, dict):
        if "events" in response:
            events = response.get("events") or []
        elif target in response:
            events = response.get(target) or []

    marker = _calendar_marker(entry_id)

    existing_keys: set[tuple[str, str, str]] = set()
    existing_events: list[dict[str, Any]] = []
    for event in events:
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

    child_label = config.get(CONF_CHILD_NAME_DISPLAY, config.get(CONF_CHILD_NAME, ""))
    location = config.get(CONF_LOCATION) or ""

    desired_keys: set[tuple[str, str, str]] = set()
    for window in state.windows:
        if window.source == "vacation_filter":
            continue
        if window.end < start_range or window.start > end_range:
            continue
        summary = f"{child_label} - {window.label}".strip()
        start_val = window.start.isoformat()
        end_val = window.end.isoformat()
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
        elif hass.services.has_service("calendar", "update_event"):
            # Update events if metadata changed (location/description)
            existing = next((ev for ev in existing_events if ev.get("__key") == key), None)
            if existing:
                event_id = existing.get("uid") or existing.get("id") or existing.get("event_id")
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

    # Delete events that no longer exist in the planning
    if hass.services.has_service("calendar", "delete_event"):
        for event in existing_events:
            key = event.get("__key")
            if key in desired_keys:
                continue
            event_id = event.get("uid") or event.get("id") or event.get("event_id")
            if not event_id:
                continue
            await hass.services.async_call(
                "calendar",
                "delete_event",
                {"entity_id": target, "event_id": event_id},
                blocking=True,
            )


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

    async def _async_handle_export_planning_pdf(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        entry = _get_entry(entry_id)
        coordinator, manager = _get_manager(entry_id)
        child_label = entry.data.get(CONF_CHILD_NAME_DISPLAY, entry.data.get(CONF_CHILD_NAME))
        start = call.data.get("start") or dt_util.now()
        end = call.data.get("end") or (start + timedelta(days=120))
        if start.tzinfo is None:
            start = dt_util.as_local(start)
        if end.tzinfo is None:
            end = dt_util.as_local(end)
        if end <= start:
            raise HomeAssistantError("End date must be after start date")

        state = coordinator.data or await manager.async_calculate(dt_util.now())
        windows = [w for w in state.windows if w.end > start and w.start < end]
        windows.sort(key=lambda w: w.start)

        from fpdf import FPDF

        def _pdf_safe(value: str) -> str:
            return value.encode("latin-1", "replace").decode("latin-1")

        pdf = FPDF()
        pdf.set_auto_page_break(True, margin=12)
        pdf.add_page()
        pdf.set_font("Helvetica", size=14)
        pdf.cell(0, 10, _pdf_safe(f"Planning de garde - {child_label}"), ln=1)
        pdf.set_font("Helvetica", size=10)
        period_line = f"Periode: {start:%d/%m/%Y %H:%M} - {end:%d/%m/%Y %H:%M}"
        pdf.cell(0, 6, _pdf_safe(period_line), ln=1)
        pdf.ln(2)

        if not windows:
            pdf.cell(0, 6, _pdf_safe("Aucun evenement sur la periode."), ln=1)
        else:
            for window in windows:
                label = window.label or "Garde"
                line = f"{window.start:%d/%m/%Y %H:%M} -> {window.end:%d/%m/%Y %H:%M} | {label}"
                pdf.multi_cell(0, 5, _pdf_safe(line))

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
            target = www_dir / f"custody_planning_{entry_id}.pdf"
        target = target.resolve(strict=False)
        if www_dir not in target.parents and target != www_dir:
            raise HomeAssistantError("Filename must be under /config/www")

        target.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(target))
        LOGGER.info("Planning PDF exported to %s", target)

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

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_PLANNING_PDF,
        _async_handle_export_planning_pdf,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): cv.string,
                vol.Optional("start"): cv.datetime,
                vol.Optional("end"): cv.datetime,
                vol.Optional("filename"): cv.string,
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