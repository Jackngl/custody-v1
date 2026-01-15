"""Device tracker platform for Custody Schedule."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CustodyScheduleCoordinator
from .schedule import CustodyComputation
from .const import (
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_PHOTO,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the device tracker."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        from .const import LOGGER
        LOGGER.error("Custody schedule entry %s not found in hass.data", entry.entry_id)
        return
    
    coordinator: CustodyScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    child_name = entry.data.get(CONF_CHILD_NAME_DISPLAY, entry.data.get(CONF_CHILD_NAME))
    async_add_entities([CustodyDeviceTracker(coordinator, entry, child_name)])


class CustodyDeviceTracker(CoordinatorEntity[CustodyComputation], TrackerEntity):
    """Device tracker basé sur la présence de l'enfant."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: CustodyScheduleCoordinator,
        entry: ConfigEntry,
        child_name: str,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = f"{child_name} Suivi"
        self._attr_unique_id = f"{entry.entry_id}_device_tracker"
        self._attr_device_info = None
        self._attr_entity_description = "Dispositif de suivi basé sur la présence de l'enfant (garde classique ou vacances scolaires)"
        photo = entry.data.get(CONF_PHOTO)
        if photo:
            self._attr_entity_picture = photo

    @property
    def state(self) -> str:
        """Return the state of the device tracker."""
        data = self.coordinator.data
        if not data:
            return "not_home"
        
        # Si l'enfant est en garde, il est "home"
        # Sinon, il est "not_home"
        return "home" if data.is_present else "not_home"

    @property
    def source_type(self) -> str:
        """Return the source type of the device tracker."""
        return "gps"  # Utilisé pour les device trackers basés sur la logique

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional metadata."""
        data = self.coordinator.data
        if not data:
            return {}
        
        return {
            "child_name": self._entry.data.get(CONF_CHILD_NAME_DISPLAY, self._entry.data.get(CONF_CHILD_NAME)),
            "source": "custody_schedule",
            "is_present": data.is_present,
        }
