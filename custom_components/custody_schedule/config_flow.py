"""Config flow for the Custody Schedule integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.util import slugify

from .const import (
    CONF_ARRIVAL_TIME,
    CONF_CALENDAR_SYNC,
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_CUSTODY_TYPE,
    CONF_DEPARTURE_TIME,
    CONF_EXCEPTIONS,
    CONF_HOLIDAY_API_URL,
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
    FRENCH_ZONES_WITH_CITIES,
    HOLIDAY_API,
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


def _format_child_name(value: str) -> str:
    """Normalize child name to ASCII words recognized by Home Assistant."""
    normalized = slugify(value, separator=" ").strip()
    if not normalized:
        return ""
    return " ".join(part.capitalize() for part in normalized.split())


def _zone_selector() -> selector.SelectSelector:
    """Create a zone selector with city labels."""
    options_list = [
        {"value": zone, "label": FRENCH_ZONES_WITH_CITIES.get(zone, zone)} for zone in FRENCH_ZONES
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _custody_type_selector() -> selector.SelectSelector:
    """Create a custody type selector with French labels."""
    translations = {
        "alternate_week": "Semaines alternées (1/1)",
        "alternate_weekend": "Week-end sur 2",
        "even_weekends": "Week-ends semaines paires",
        "odd_weekends": "Week-ends semaines impaires",
        "two_two_three": "2-2-3",
        "two_two_five_five": "2-2-5-5",
        "custom": "Personnalisé",
    }
    options_list = [
        {"value": key, "label": translations.get(key, key)} for key in sorted(CUSTODY_TYPES.keys())
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _reference_year_selector() -> selector.SelectSelector:
    """Create a reference year selector with French labels."""
    translations = {
        "even": "Paire",
        "odd": "Impaire",
    }
    options_list = [
        {"value": year, "label": translations.get(year, year)} for year in REFERENCE_YEARS
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _start_day_selector() -> selector.SelectSelector:
    """Create a start day selector with French labels."""
    translations = {
        "monday": "Lundi",
        "tuesday": "Mardi",
        "wednesday": "Mercredi",
        "thursday": "Jeudi",
        "friday": "Vendredi",
        "saturday": "Samedi",
        "sunday": "Dimanche",
    }
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    options_list = [
        {"value": day, "label": translations.get(day, day)} for day in days
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _vacation_rule_selector() -> selector.SelectSelector:
    """Create a vacation rule selector with French labels."""
    translations = {
        "first_week": "1ère semaine",
        "second_week": "2ème semaine",
        "first_half": "1ère moitié",
        "second_half": "2ème moitié",
        "even_weeks": "Semaines paires",
        "odd_weeks": "Semaines impaires",
        "july": "Juillet",
        "august": "Août",
        "first_week_even_year": "1ère semaine - années paires",
        "first_week_odd_year": "1ère semaine - années impaires",
        "second_week_even_year": "2ème semaine - années paires",
        "second_week_odd_year": "2ème semaine - années impaires",
        "custom": "Personnalisé",
    }
    options_list = [{"value": "", "label": "Aucune"}]
    options_list.extend(
        [{"value": rule, "label": translations.get(rule, rule)} for rule in VACATION_RULES]
    )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _summer_rule_selector() -> selector.SelectSelector:
    """Create a summer rule selector with French labels."""
    translations = {
        "july_first_half": "Juillet - 1ère moitié",
        "july_second_half": "Juillet - 2ème moitié",
        "july_even_weeks": "Juillet - semaines paires",
        "july_odd_weeks": "Juillet - semaines impaires",
        "august_first_half": "Août - 1ère moitié",
        "august_second_half": "Août - 2ème moitié",
        "august_even_weeks": "Août - semaines paires",
        "august_odd_weeks": "Août - semaines impaires",
        "july_even_year": "Juillet - années paires",
        "july_odd_year": "Juillet - années impaires",
        "august_even_year": "Août - années paires",
        "august_odd_year": "Août - années impaires",
    }
    options_list = [{"value": "", "label": "Aucune"}]
    options_list.extend(
        [{"value": rule, "label": translations.get(rule, rule)} for rule in SUMMER_RULES]
    )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _time_to_str(value: Any, default: str) -> str:
    """Convert TimeSelector output to HH:MM string."""
    if value is None:
        return default
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) >= 2:
        try:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        except (TypeError, ValueError):
            return default
    return default


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

            name_value = cleaned_input.get(CONF_CHILD_NAME)
            if isinstance(name_value, str):
                display_name = name_value.strip()
                formatted_name = _format_child_name(display_name)
                if formatted_name:
                    cleaned_input[CONF_CHILD_NAME_DISPLAY] = display_name
                    cleaned_input[CONF_CHILD_NAME] = formatted_name
                else:
                    errors[CONF_CHILD_NAME] = "invalid_child_name"
            else:
                errors[CONF_CHILD_NAME] = "invalid_child_name"

            icon_value = cleaned_input.get(CONF_ICON, "mdi:account")
            if isinstance(icon_value, dict):
                icon_value = icon_value.get("icon", icon_value.get("id"))
            if not isinstance(icon_value, str) or not icon_value.strip():
                cleaned_input[CONF_ICON] = "mdi:account"
            else:
                cleaned_input[CONF_ICON] = icon_value

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
                # Allow multiple children with different names
                # Only abort if the exact same child name is already configured
                self._abort_if_unique_id_configured()
                return await self.async_step_custody()

        schema = vol.Schema(
            {
                vol.Required(CONF_CHILD_NAME): cv.string,
                vol.Optional(CONF_ICON, default="mdi:account"): selector.IconSelector(),
                vol.Optional(CONF_PHOTO): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_custody(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Select custody type and schedules (step 2)."""
        if user_input:
            cleaned = dict(user_input)
            cleaned[CONF_ARRIVAL_TIME] = _time_to_str(user_input.get(CONF_ARRIVAL_TIME), "08:00")
            cleaned[CONF_DEPARTURE_TIME] = _time_to_str(user_input.get(CONF_DEPARTURE_TIME), "19:00")
            self._data.update(cleaned)
            return await self.async_step_vacations()

        schema = vol.Schema(
            {
                vol.Required(CONF_CUSTODY_TYPE, default="alternate_week"): _custody_type_selector(),
                vol.Required(CONF_REFERENCE_YEAR, default="even"): _reference_year_selector(),
                vol.Required(CONF_START_DAY, default="monday"): _start_day_selector(),
                vol.Required(CONF_ARRIVAL_TIME, default="08:00"): selector.TimeSelector(),
                vol.Required(CONF_DEPARTURE_TIME, default="19:00"): selector.TimeSelector(),
                vol.Optional(CONF_LOCATION): cv.string,
            }
        )
        return self.async_show_form(step_id="custody", data_schema=schema)

    async def async_step_vacations(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure school zones and vacation rules (step 3)."""
        if user_input:
            cleaned = dict(user_input)
            # Convert empty strings to None for optional fields
            if cleaned.get(CONF_VACATION_RULE) == "":
                cleaned[CONF_VACATION_RULE] = None
            if cleaned.get(CONF_SUMMER_RULE) == "":
                cleaned[CONF_SUMMER_RULE] = None
            self._data.update(cleaned)
            return await self.async_step_advanced()

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE, default="A"): _zone_selector(),
                vol.Optional(CONF_VACATION_RULE): _vacation_rule_selector(),
                vol.Optional(CONF_SUMMER_RULE): _summer_rule_selector(),
            }
        )
        return self.async_show_form(step_id="vacations", data_schema=schema)

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Advanced optional settings (step 4)."""
        if user_input:
            cleaned = dict(user_input)
            # Validate API URL if provided
            api_url = cleaned.get(CONF_HOLIDAY_API_URL)
            if api_url and api_url.strip():
                # Basic validation: must contain {year} and {zone} placeholders
                if "{year}" not in api_url or "{zone}" not in api_url:
                    return self.async_show_form(
                        step_id="advanced",
                        data_schema=self._get_advanced_schema(),
                        errors={CONF_HOLIDAY_API_URL: "api_url_missing_placeholders"},
                    )
                cleaned[CONF_HOLIDAY_API_URL] = api_url.strip()
            else:
                cleaned.pop(CONF_HOLIDAY_API_URL, None)
            self._data.update(cleaned)
            title = self._data.get(CONF_CHILD_NAME_DISPLAY, self._data[CONF_CHILD_NAME])
            return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(step_id="advanced", data_schema=self._get_advanced_schema())

    def _get_advanced_schema(self) -> vol.Schema:
        """Get the advanced settings schema."""
        return vol.Schema(
            {
                vol.Optional(CONF_NOTES): cv.string,
                vol.Optional(CONF_NOTIFICATIONS, default=False): cv.boolean,
                vol.Optional(CONF_CALENDAR_SYNC, default=False): cv.boolean,
                vol.Optional(CONF_EXCEPTIONS): cv.string,
                vol.Optional(
                    CONF_HOLIDAY_API_URL,
                    default="",
                    description={"suggested_value": HOLIDAY_API},
                ): cv.string,
            }
        )

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
        self._data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "schedule": "Horaires et lieu",
                "vacations": "Zone scolaire et règles vacances",
                "advanced": "Options avancées",
            },
        )

    async def async_step_schedule(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modify schedule times and location."""
        if user_input:
            cleaned = dict(user_input)
            cleaned[CONF_ARRIVAL_TIME] = _time_to_str(user_input.get(CONF_ARRIVAL_TIME), "08:00")
            cleaned[CONF_DEPARTURE_TIME] = _time_to_str(user_input.get(CONF_DEPARTURE_TIME), "19:00")
            self._data.update(cleaned)
            return self.async_create_entry(title="", data=self._data)

        data = {**self._entry.data, **(self._entry.options or {})}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ARRIVAL_TIME, default=data.get(CONF_ARRIVAL_TIME, "08:00")
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_DEPARTURE_TIME, default=data.get(CONF_DEPARTURE_TIME, "19:00")
                ): selector.TimeSelector(),
                vol.Optional(CONF_LOCATION, default=data.get(CONF_LOCATION, "")): cv.string,
            }
        )
        return self.async_show_form(step_id="schedule", data_schema=schema)

    async def async_step_vacations(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modify school zone and vacation rules."""
        if user_input:
            cleaned = dict(user_input)
            # Convert empty strings to None for optional fields
            if cleaned.get(CONF_VACATION_RULE) == "":
                cleaned[CONF_VACATION_RULE] = None
            if cleaned.get(CONF_SUMMER_RULE) == "":
                cleaned[CONF_SUMMER_RULE] = None
            self._data.update(cleaned)
            return self.async_create_entry(title="", data=self._data)

        data = {**self._entry.data, **(self._entry.options or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE, default=data.get(CONF_ZONE, "A")): _zone_selector(),
                vol.Optional(CONF_VACATION_RULE, default=data.get(CONF_VACATION_RULE)): _vacation_rule_selector(),
                vol.Optional(CONF_SUMMER_RULE, default=data.get(CONF_SUMMER_RULE)): _summer_rule_selector(),
            }
        )
        return self.async_show_form(step_id="vacations", data_schema=schema)

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Advanced optional settings."""
        if user_input:
            cleaned = dict(user_input)
            # Validate API URL if provided
            api_url = cleaned.get(CONF_HOLIDAY_API_URL)
            if api_url and api_url.strip():
                # Basic validation: must contain {year} and {zone} placeholders
                if "{year}" not in api_url or "{zone}" not in api_url:
                    data = {**self._entry.data, **(self._entry.options or {})}
                    return self.async_show_form(
                        step_id="advanced",
                        data_schema=self._get_advanced_schema(data),
                        errors={CONF_HOLIDAY_API_URL: "api_url_missing_placeholders"},
                    )
                cleaned[CONF_HOLIDAY_API_URL] = api_url.strip()
            else:
                cleaned.pop(CONF_HOLIDAY_API_URL, None)
            self._data.update(cleaned)
            return self.async_create_entry(title="", data=self._data)

        data = {**self._entry.data, **(self._entry.options or {})}
        return self.async_show_form(step_id="advanced", data_schema=self._get_advanced_schema(data))

    def _get_advanced_schema(self, data: dict[str, Any] | None = None) -> vol.Schema:
        """Get the advanced settings schema."""
        if data is None:
            data = {}
        return vol.Schema(
            {
                vol.Optional(CONF_NOTES, default=data.get(CONF_NOTES, "")): cv.string,
                vol.Optional(CONF_NOTIFICATIONS, default=data.get(CONF_NOTIFICATIONS, False)): cv.boolean,
                vol.Optional(CONF_CALENDAR_SYNC, default=data.get(CONF_CALENDAR_SYNC, False)): cv.boolean,
                vol.Optional(CONF_EXCEPTIONS, default=data.get(CONF_EXCEPTIONS, "")): cv.string,
                vol.Optional(
                    CONF_HOLIDAY_API_URL,
                    default=data.get(CONF_HOLIDAY_API_URL, ""),
                    description={"suggested_value": HOLIDAY_API},
                ): cv.string,
            }
        )
