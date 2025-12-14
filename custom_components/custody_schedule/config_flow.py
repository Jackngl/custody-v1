"""Config flow for the Custody Schedule integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.util import slugify

from .const import (
    CONF_ARRIVAL_TIME,
    CONF_CALENDAR_SYNC,
    CONF_CHILD_NAME,
    CONF_CUSTODY_TYPE,
    CONF_DEPARTURE_TIME,
    CONF_EXCEPTIONS,
    CONF_ICON,
    CONF_LOCATION,
    CONF_NOTES,
    CONF_NOTIFICATIONS,
    CONF_PHOTO,
    CONF_REFERENCE_YEAR,
    CONF_START_DAY,
    CONF_SUMMER_RULE,
    CONF_VACATION_RULE,
    CONF_ZONE,
    CUSTODY_TYPES,
    DOMAIN,
    FRENCH_ZONES,
    REFERENCE_YEARS,
    SUMMER_RULES,
    VACATION_RULES,
)


ALLOWED_PHOTO_PREFIXES = ("http://", "https://", "media-source://", "data:")
ALLOWED_PHOTO_PREFIXES_CI = tuple(prefix.lower() for prefix in ALLOWED_PHOTO_PREFIXES)


def _validate_time(value: str) -> str:
    """Ensure HH:MM format."""
    if isinstance(value, (int, float)):
        raise vol.Invalid("Expected HH:MM string")
    parts = str(value).split(":")
    if len(parts) != 2:
        raise vol.Invalid("Use HH:MM format")
    hour, minute = parts
    try:
        hour_i = int(hour)
        minute_i = int(minute)
    except ValueError as err:
        raise vol.Invalid("Invalid time digits") from err
    if not 0 <= hour_i <= 23 or not 0 <= minute_i <= 59:
        raise vol.Invalid("Time must be within 00:00-23:59")
    return f"{hour_i:02d}:{minute_i:02d}"


class CustodyScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the step-driven configuration."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Gather child information (step 1)."""
        errors: dict[str, str] = {}
        if user_input:
            cleaned_input = dict(user_input)
            photo_value = cleaned_input.get(CONF_PHOTO)
            if isinstance(photo_value, str):
                if photo_value.strip():
                    normalized, error_key = self._normalize_photo(photo_value)
                    if error_key:
                        errors[CONF_PHOTO] = error_key
                    else:
                        cleaned_input[CONF_PHOTO] = normalized
                else:
                    cleaned_input.pop(CONF_PHOTO, None)

            if not errors:
                self._data.update(cleaned_input)
                unique_id = slugify(cleaned_input[CONF_CHILD_NAME])
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return await self.async_step_custody()

        schema = vol.Schema(
            {
                vol.Required(CONF_CHILD_NAME): cv.string,
                vol.Optional(CONF_ICON, default="mdi:account-child"): cv.string,
                vol.Optional(CONF_PHOTO): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_custody(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Select custody type and schedules (step 2)."""
        if user_input:
            self._data.update(user_input)
            return await self.async_step_vacations()

        schema = vol.Schema(
            {
                vol.Required(CONF_CUSTODY_TYPE, default="alternate_week"): vol.In(sorted(CUSTODY_TYPES.keys())),
                vol.Required(CONF_REFERENCE_YEAR, default="even"): vol.In(REFERENCE_YEARS),
                vol.Required(CONF_START_DAY, default="monday"): vol.In(
                    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                ),
                vol.Required(CONF_ARRIVAL_TIME, default="08:00"): vol.All(cv.string, _validate_time),
                vol.Required(CONF_DEPARTURE_TIME, default="19:00"): vol.All(cv.string, _validate_time),
                vol.Optional(CONF_LOCATION): cv.string,
            }
        )
        return self.async_show_form(step_id="custody", data_schema=schema)

    async def async_step_vacations(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure school zones and vacation rules (step 3)."""
        if user_input:
            self._data.update(user_input)
            return await self.async_step_advanced()

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE, default="A"): vol.In(FRENCH_ZONES),
                vol.Optional(CONF_VACATION_RULE): vol.In(VACATION_RULES),
                vol.Optional(CONF_SUMMER_RULE): vol.In(SUMMER_RULES),
            }
        )
        return self.async_show_form(step_id="vacations", data_schema=schema)

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Advanced optional settings (step 4)."""
        if user_input:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_CHILD_NAME], data=self._data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTES): cv.string,
                vol.Optional(CONF_NOTIFICATIONS, default=False): cv.boolean,
                vol.Optional(CONF_CALENDAR_SYNC, default=False): cv.boolean,
                vol.Optional(CONF_EXCEPTIONS): cv.string,
            }
        )
        return self.async_show_form(step_id="advanced", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> config_entries.OptionsFlowWithConfigEntry:
        """Return the options handler."""
        return CustodyScheduleOptionsFlow(entry)

    def _normalize_photo(self, raw: str) -> tuple[str | None, str | None]:
        """Allow HTTP(S) URLs, media sources or files stored in www/."""
        value = raw.strip()
        if not value:
            return None, None

        lowered = value.lower()
        if lowered.startswith(ALLOWED_PHOTO_PREFIXES_CI):
            return value, None

        if value.startswith("/local/"):
            return value, None
        if value.startswith("local/"):
            return f"/{value}", None

        try:
            www_dir = Path(self.hass.config.path("www")).resolve(strict=False)
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = (www_dir / value).resolve(strict=False)
            else:
                candidate = candidate.resolve(strict=False)
            relative = candidate.relative_to(www_dir)
        except ValueError:
            return None, "invalid_local_photo"

        return f"/local/{relative.as_posix()}", None


class CustodyScheduleOptionsFlow(config_entries.OptionsFlow):
    """Allow users to tweak schedule details from the UI."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Single step options form."""
        if user_input:
            return self.async_create_entry(title="", data=user_input)

        data = {**self._entry.data, **(self._entry.options or {})}
        schema = vol.Schema(
            {
                vol.Optional(CONF_ARRIVAL_TIME, default=data.get(CONF_ARRIVAL_TIME, "08:00")): vol.All(cv.string, _validate_time),
                vol.Optional(CONF_DEPARTURE_TIME, default=data.get(CONF_DEPARTURE_TIME, "19:00")): vol.All(cv.string, _validate_time),
                vol.Optional(CONF_LOCATION, default=data.get(CONF_LOCATION, "")): cv.string,
                vol.Optional(CONF_NOTES, default=data.get(CONF_NOTES, "")): cv.string,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
