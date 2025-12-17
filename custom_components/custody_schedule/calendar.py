"""Calendar entity for the custody schedule."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CustodyScheduleCoordinator
from .const import CONF_CHILD_NAME, CONF_CHILD_NAME_DISPLAY, CONF_LOCATION, CONF_PHOTO, DOMAIN
from .schedule import CustodyComputation, CustodyWindow


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the calendar entity."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        from .const import LOGGER
        LOGGER.error("Custody schedule entry %s not found in hass.data", entry.entry_id)
        return
    
    coordinator: CustodyScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    child_name = entry.data.get(CONF_CHILD_NAME_DISPLAY, entry.data.get(CONF_CHILD_NAME))
    async_add_entities([CustodyCalendarEntity(coordinator, entry, child_name)])


class CustodyCalendarEntity(CoordinatorEntity[CustodyComputation], CalendarEntity):
    """Expose the custody planning as a calendar."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: CustodyScheduleCoordinator, entry: ConfigEntry, child_name: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = f"{child_name} Planning de garde Calendrier"
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = None
        photo = entry.data.get(CONF_PHOTO)
        if photo:
            self._attr_entity_picture = photo

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next relevant event."""
        data = self.coordinator.data
        if not data:
            return None

        now = dt_util.now()
        upcoming = sorted(
            (window for window in data.windows if window.end > now), key=lambda window: window.start
        )
        window = upcoming[0] if upcoming else None
        return self._window_to_event(window) if window else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return all events within the requested range."""
        data = self.coordinator.data
        if not data:
            return []

        events: list[CalendarEvent] = []
        for window in data.windows:
            if window.end < start_date or window.start > end_date:
                continue
            events.append(self._window_to_event(window))
        return events

    def _window_to_event(self, window: CustodyWindow) -> CalendarEvent:
        """Convert an internal window to a CalendarEvent."""
        description = f"{window.label} • Source: {window.source}"
        location = self.coordinator.data.attributes.get(CONF_LOCATION) if self.coordinator.data else None
        return CalendarEvent(
            start=window.start,
            end=window.end,
            summary=window.label,
            description=description,
            location=location,
        )