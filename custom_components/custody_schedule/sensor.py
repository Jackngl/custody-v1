"""Sensor platform for Custody Schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CustodyScheduleCoordinator
from .schedule import CustodyComputation
from .const import (
    ATTR_CUSTODY_TYPE,
    ATTR_CURRENT_PERIOD,
    ATTR_DAYS_REMAINING,
    ATTR_NEXT_ARRIVAL,
    ATTR_NEXT_DEPARTURE,
    ATTR_VACATION_NAME,
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_PHOTO,
    DOMAIN,
)


@dataclass(slots=True)
class SensorDefinition:
    """Meta description for each logical sensor."""

    key: str
    name: str
    icon: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    unit: str | None = None


SENSORS: tuple[SensorDefinition, ...] = (
    SensorDefinition("next_arrival", "Prochaine arrivée", "mdi:calendar-clock"),
    SensorDefinition("next_departure", "Prochain départ", "mdi:calendar-arrow-right"),
    SensorDefinition(
        "days_remaining",
        "Jours restants",
        "mdi:clock-end",
        SensorDeviceClass.DURATION,
        SensorStateClass.MEASUREMENT,
        UnitOfTime.DAYS,
    ),
    SensorDefinition("current_period", "Période actuelle", "mdi:school"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up Custody Schedule sensors."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        from .const import LOGGER
        LOGGER.error("Custody schedule entry %s not found in hass.data", entry.entry_id)
        return
    
    coordinator: CustodyScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    child_name = entry.data.get(CONF_CHILD_NAME_DISPLAY, entry.data.get(CONF_CHILD_NAME))

    entities = [CustodyScheduleSensor(coordinator, entry, definition, child_name) for definition in SENSORS]
    async_add_entities(entities)


class CustodyScheduleSensor(CoordinatorEntity[CustodyComputation], SensorEntity):
    """Represent a derived sensor from the custody schedule state."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: CustodyScheduleCoordinator,
        entry: ConfigEntry,
        definition: SensorDefinition,
        child_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._definition = definition
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"
        self._attr_name = f"{child_name} Planning de garde {definition.name}"
        self._attr_icon = definition.icon
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_device_info = None
        photo = entry.data.get(CONF_PHOTO)
        if photo:
            self._attr_entity_picture = photo

    @property
    def native_value(self) -> Any:
        """Return the sensor state."""
        data = self.coordinator.data
        if not data:
            return None

        if self._definition.key == "next_arrival":
            return self._format_datetime(data.next_arrival)
        if self._definition.key == "next_departure":
            return self._format_datetime(data.next_departure)
        if self._definition.key == "days_remaining":
            return data.days_remaining
        if self._definition.key == "current_period":
            return data.current_period
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional metadata shared across sensors."""
        data = self.coordinator.data
        if not data:
            return {}

        attrs: dict[str, Any] = {
            ATTR_CUSTODY_TYPE: self._entry.data.get("custody_type"),
            ATTR_CURRENT_PERIOD: data.current_period,
            ATTR_VACATION_NAME: data.vacation_name,
            ATTR_NEXT_ARRIVAL: self._format_datetime(data.next_arrival),
            ATTR_NEXT_DEPARTURE: self._format_datetime(data.next_departure),
            ATTR_DAYS_REMAINING: data.days_remaining,
        }
        attrs.update(data.attributes)
        return {key: value for key, value in attrs.items() if value is not None}

    def _format_datetime(self, value: datetime | None) -> str | None:
        """Return ISO string for UI friendliness."""
        if value is None:
            return None
        localized = dt_util.as_local(value)
        return localized.isoformat()
