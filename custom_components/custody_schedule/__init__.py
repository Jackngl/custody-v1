"""Home Assistant entry point for the Custody Schedule integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_HOLIDAY_API_URL,
    DOMAIN,
    HOLIDAY_API,
    LOGGER,
    PLATFORMS,
    SERVICE_OVERRIDE_PRESENCE,
    SERVICE_REFRESH_SCHEDULE,
    SERVICE_SET_MANUAL_DATES,
    SERVICE_TEST_HOLIDAY_API,
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
    api_url = config.get(CONF_HOLIDAY_API_URL) or HOLIDAY_API
    
    # Store clients by API URL to support multiple entries with different API URLs
    # Multiple entries can share the same client if they use the same API URL (benefits from shared cache)
    holiday_clients: dict[str, SchoolHolidayClient] = hass.data[DOMAIN].setdefault("holiday_clients", {})
    
    if api_url not in holiday_clients:
        holiday_clients[api_url] = SchoolHolidayClient(hass, api_url)
        LOGGER.debug("Created new holiday client for API URL: %s", api_url)
    
    holidays = holiday_clients[api_url]
    
    manager = CustodyScheduleManager(hass, config, holidays)
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

    async def _async_update_data(self) -> CustodyComputation:
        """Fetch data from the schedule manager."""
        try:
            state = await self.manager.async_calculate(dt_util.now())
        except Exception as err:
            raise UpdateFailed(f"Unable to compute custody schedule: {err}") from err

        self._fire_events(state)
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


def _register_services(hass: HomeAssistant) -> None:
    """Register services exposed by the integration."""

    def _get_manager(entry_id: str) -> tuple[CustodyScheduleCoordinator, CustodyScheduleManager]:
        entry_data = hass.data[DOMAIN].get(entry_id)
        if not entry_data:
            raise HomeAssistantError(f"No custody schedule found for entry_id {entry_id}")
        return entry_data["coordinator"], entry_data["manager"]

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