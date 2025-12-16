"""Binary sensor for current presence."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CustodyScheduleCoordinator
from .schedule import CustodyComputation
from .const import (
    ATTR_CUSTODY_TYPE,
    ATTR_NEXT_ARRIVAL,
    ATTR_NEXT_DEPARTURE,
    ATTR_VACATION_NAME,
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_PHOTO,
    DOMAIN,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the binary sensor."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        from .const import LOGGER
        LOGGER.error("Custody schedule entry %s not found in hass.data", entry.entry_id)
        return
    
    coordinator: CustodyScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    child_name = entry.data.get(CONF_CHILD_NAME_DISPLAY, entry.data.get(CONF_CHILD_NAME))
    async_add_entities([CustodyPresenceBinarySensor(coordinator, entry, child_name)])


class CustodyPresenceBinarySensor(CoordinatorEntity[CustodyComputation], BinarySensorEntity):
    """Represent the presence status."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_has_entity_name = False

    def __init__(self, coordinator: CustodyScheduleCoordinator, entry: ConfigEntry, child_name: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = f"{child_name} Planning de garde Présence"
        self._attr_unique_id = f"{entry.entry_id}_presence"
        self._attr_device_info = None
        photo = entry.data.get(CONF_PHOTO)
        if photo:
            self._attr_entity_picture = photo

    @property
    def is_on(self) -> bool | None:
        """Return presence state."""
        data = self.coordinator.data
        return data.is_present if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose additional metadata for automations."""
        data = self.coordinator.data
        if not data:
            return {}

        return {
            "child_name": self._entry.data.get(CONF_CHILD_NAME_DISPLAY, self._entry.data.get(CONF_CHILD_NAME)),
            ATTR_CUSTODY_TYPE: self._entry.data.get("custody_type"),
            ATTR_NEXT_ARRIVAL: data.next_arrival.isoformat() if data.next_arrival else None,
            ATTR_NEXT_DEPARTURE: data.next_departure.isoformat() if data.next_departure else None,
            ATTR_VACATION_NAME: data.vacation_name,
        }
