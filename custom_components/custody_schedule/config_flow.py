"""Config flow for the Custody Schedule integration."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_ARRIVAL_TIME,
    CONF_AUGUST_RULE,
    CONF_CALENDAR_SYNC,
    CONF_CALENDAR_TARGET,
    CONF_CALENDAR_SYNC_DAYS,
    CONF_CALENDAR_SYNC_INTERVAL_HOURS,
    CONF_CHILD_NAME,
    CONF_CHILD_NAME_DISPLAY,
    CONF_CUSTODY_TYPE,
    CONF_DEPARTURE_TIME,
    CONF_EXCEPTIONS,
    CONF_EXCEPTIONS_LIST,
    CONF_EXCEPTIONS_RECURRING,
    CONF_HOLIDAY_API_URL,
    CONF_ICON,
    CONF_JULY_RULE,
    CONF_LOCATION,
    CONF_NOTES,
    CONF_NOTIFICATIONS,
    CONF_PHOTO,
    CONF_REFERENCE_YEAR,
    CONF_REFERENCE_YEAR_CUSTODY,
    CONF_REFERENCE_YEAR_VACATIONS,
    CONF_SCHOOL_LEVEL,
    CONF_START_DAY,
    CONF_SUMMER_RULE,
    CONF_VACATION_SPLIT_MODE,
    CONF_ZONE,
    AUGUST_RULES,
    CUSTODY_TYPES,
    DOMAIN,
    FRENCH_ZONES,
    FRENCH_ZONES_WITH_CITIES,
    HOLIDAY_API,
    JULY_RULES,
    REFERENCE_YEARS,
    SUMMER_RULES,
    VACATION_RULES,
    VACATION_SPLIT_MODES,
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


def _school_level_selector() -> selector.SelectSelector:
    """Return selector for school level."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "primary", "label": "Primaire"},
                {"value": "middle", "label": "Collège"},
                {"value": "high", "label": "Lycée"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _custody_type_selector() -> selector.SelectSelector:
    """Create a custody type selector with French labels."""
    translations = {
        "alternate_week": "Semaines alternées (1/1)",
        "alternate_week_parity": "Semaines alternées",
        "alternate_weekend": "Week-ends alternés",
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


def _summer_rule_selector() -> selector.SelectSelector:
    """Create a summer rule selector with French labels (quinzaines)."""
    translations = {
        "july_first_half": "Juillet - 1ère moitié (1-15 juillet)",
        "july_second_half": "Juillet - 2ème moitié (16-31 juillet)",
        "august_first_half": "Août - 1ère moitié (1-15 août)",
        "august_second_half": "Août - 2ème moitié (16-31 août)",
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


def _july_rule_selector() -> selector.SelectSelector:
    """Create a July rule selector with French labels."""
    translations = {
        "july_even": "Juillet (années paires)",
        "july_odd": "Juillet (années impaires)",
    }
    options_list = [{"value": "", "label": "Aucune"}]
    options_list.extend(
        [{"value": rule, "label": translations.get(rule, rule)} for rule in JULY_RULES]
    )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _august_rule_selector() -> selector.SelectSelector:
    """Create an August rule selector with French labels."""
    translations = {
        "august_even": "Août (années paires)",
        "august_odd": "Août (années impaires)",
    }
    options_list = [{"value": "", "label": "Aucune"}]
    options_list.extend(
        [{"value": rule, "label": translations.get(rule, rule)} for rule in AUGUST_RULES]
    )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _vacation_split_selector() -> selector.SelectSelector:
    """Create a selector for vacation split mode (odd/even halves)."""
    translations = {
        "odd_first": "Années impaires = 1ère moitié (années paires = 2ème moitié)",
        "odd_second": "Années impaires = 2ème moitié (années paires = 1ère moitié)",
    }
    options_list = [
        {"value": mode, "label": translations.get(mode, mode)} for mode in VACATION_SPLIT_MODES
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options_list,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _time_to_str(value: Any, default: str) -> str:
    """Convert TimeSelector output to HH:MM string.
    
    Handles various formats:
    - datetime.time objects
    - "HH:MM" strings
    - "HH:MM:SS" strings (extracts HH:MM)
    - None (returns default)
    """
    if value is None:
        return default
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) >= 2:
        try:
            # Extract only hours and minutes, ignore seconds if present
            hour = int(parts[0])
            minute = int(parts[1])
            # Validate range
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except (TypeError, ValueError):
            pass
    return default


def _normalize_datetime(value: Any) -> datetime | None:
    """Normalize datetime values from selectors or stored strings."""
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        return dt_util.as_local(parsed) if parsed else None
    return None


def _normalize_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        try:
            return value
        except TypeError:
            pass
    if isinstance(value, str):
        return dt_util.parse_date(value)
    return None


def _normalize_time(value: Any) -> time | None:
    if value is None:
        return None
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value
    if isinstance(value, str):
        return dt_util.parse_time(value)
    return None


def _get_exceptions(data: dict[str, Any]) -> list[dict[str, Any]]:
    exceptions = data.get(CONF_EXCEPTIONS_LIST, [])
    return list(exceptions) if isinstance(exceptions, list) else []


def _get_recurring_exceptions(data: dict[str, Any]) -> list[dict[str, Any]]:
    exceptions = data.get(CONF_EXCEPTIONS_RECURRING, [])
    return list(exceptions) if isinstance(exceptions, list) else []


def _format_exception_label(item: dict[str, Any]) -> str:
    label = item.get("label") or "Exception"
    start = _normalize_datetime(item.get("start"))
    end = _normalize_datetime(item.get("end"))
    if start and end:
        return f"{label} — {start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')}"
    return str(label)


def _format_recurring_label(item: dict[str, Any]) -> str:
    label = item.get("label") or "Exception récurrente"
    weekday = item.get("weekday")
    weekdays = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    day_label = weekdays[weekday] if isinstance(weekday, int) and 0 <= weekday <= 6 else "?"
    start_time = item.get("start_time") or "?"
    end_time = item.get("end_time") or "?"
    return f"{label} — {day_label} {start_time} → {end_time}"


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
        """Configure garde classique (weekends/semaines) - step 2."""
        if user_input:
            cleaned = dict(user_input)
            cleaned[CONF_ARRIVAL_TIME] = _time_to_str(user_input.get(CONF_ARRIVAL_TIME), "08:00")
            cleaned[CONF_DEPARTURE_TIME] = _time_to_str(user_input.get(CONF_DEPARTURE_TIME), "19:00")
            # For alternate_weekend/alternate_week_parity, start_day is not used (based on ISO week parity)
            # But we still save it for other custody types
            self._data.update(cleaned)
            return await self.async_step_vacations()

        # Use saved data if user goes back
        custody_type = self._data.get(CONF_CUSTODY_TYPE, "alternate_week")
        # start_day is only relevant for custody types that use cycles (not alternate_weekend/alternate_week_parity)
        show_start_day = custody_type not in ("alternate_weekend", "alternate_week_parity")
        
        reference_year_default = self._data.get(
            CONF_REFERENCE_YEAR_CUSTODY, self._data.get(CONF_REFERENCE_YEAR, "even")
        )
        schema_dict = {
            vol.Required(
                CONF_CUSTODY_TYPE, default=custody_type
            ): _custody_type_selector(),
            vol.Required(
                CONF_REFERENCE_YEAR_CUSTODY, default=reference_year_default
            ): _reference_year_selector(),
            vol.Required(
                CONF_ARRIVAL_TIME, default=self._data.get(CONF_ARRIVAL_TIME, "08:00")
            ): selector.TimeSelector(),
            vol.Required(
                CONF_DEPARTURE_TIME, default=self._data.get(CONF_DEPARTURE_TIME, "19:00")
            ): selector.TimeSelector(),
            vol.Optional(CONF_LOCATION, default=self._data.get(CONF_LOCATION, "")): cv.string,
        }
        
        # Only show start_day for custody types that use it
        if show_start_day:
            schema_dict[vol.Required(
                CONF_START_DAY, default=self._data.get(CONF_START_DAY, "monday")
            )] = _start_day_selector()
        
        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="custody", data_schema=schema)

    async def async_step_vacations(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure vacances scolaires - step 3."""
        if user_input:
            cleaned = dict(user_input)
            # Convert empty strings to None for optional fields
            if cleaned.get(CONF_SUMMER_RULE) == "":
                cleaned[CONF_SUMMER_RULE] = None
            if cleaned.get(CONF_JULY_RULE) == "":
                cleaned[CONF_JULY_RULE] = None
            if cleaned.get(CONF_AUGUST_RULE) == "":
                cleaned[CONF_AUGUST_RULE] = None
            self._data.update(cleaned)
            return await self.async_step_advanced()

        # Use saved data if user goes back, convert None to empty string for selectors
        summer_rule_default = self._data.get(CONF_SUMMER_RULE) or ""
        july_rule_default = self._data.get(CONF_JULY_RULE) or ""
        august_rule_default = self._data.get(CONF_AUGUST_RULE) or ""
        # Get reference_year for vacations (separate from custody reference_year)
        # Default to "even" if not set
        reference_year_default = self._data.get(
            CONF_REFERENCE_YEAR_VACATIONS, self._data.get(CONF_REFERENCE_YEAR, "even")
        )
        vacation_split_default = self._data.get(CONF_VACATION_SPLIT_MODE, "odd_first")
        
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE, default=self._data.get(CONF_ZONE, "A")): _zone_selector(),
                vol.Required(CONF_REFERENCE_YEAR_VACATIONS, default=reference_year_default): _reference_year_selector(),
                vol.Optional(CONF_VACATION_SPLIT_MODE, default=vacation_split_default): _vacation_split_selector(),
                vol.Optional(
                    CONF_SCHOOL_LEVEL, default=self._data.get(CONF_SCHOOL_LEVEL, "primary")
                ): _school_level_selector(),
                vol.Optional(CONF_JULY_RULE, default=july_rule_default): _july_rule_selector(),
                vol.Optional(CONF_AUGUST_RULE, default=august_rule_default): _august_rule_selector(),
                vol.Optional(CONF_SUMMER_RULE, default=summer_rule_default): _summer_rule_selector(),
            }
        )
        return self.async_show_form(step_id="vacations", data_schema=schema)

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Advanced optional settings (step 4)."""
        if user_input:
            cleaned = dict(user_input)
            errors: dict[str, str] = {}
            calendar_sync = cleaned.get(CONF_CALENDAR_SYNC, False)
            calendar_target = cleaned.get(CONF_CALENDAR_TARGET, "") or ""
            if calendar_sync and not str(calendar_target).strip():
                errors[CONF_CALENDAR_TARGET] = "calendar_target_required"

            # Validate API URL if provided
            api_url = cleaned.get(CONF_HOLIDAY_API_URL)
            if api_url and api_url.strip():
                # Basic validation: must contain {year} and {zone} placeholders
                if "{year}" not in api_url or "{zone}" not in api_url:
                    # Merge user input with existing data to preserve user's entry
                    merged_data = {**self._data, **cleaned}
                    return self.async_show_form(
                        step_id="advanced",
                        data_schema=self._get_advanced_schema(merged_data),
                        errors={**errors, CONF_HOLIDAY_API_URL: "api_url_missing_placeholders"},
                    )
                cleaned[CONF_HOLIDAY_API_URL] = api_url.strip()
            else:
                cleaned.pop(CONF_HOLIDAY_API_URL, None)
            if errors:
                merged_data = {**self._data, **cleaned}
                return self.async_show_form(
                    step_id="advanced",
                    data_schema=self._get_advanced_schema(merged_data),
                    errors=errors,
                )
            self._data.update(cleaned)
            title = self._data.get(CONF_CHILD_NAME_DISPLAY, self._data[CONF_CHILD_NAME])
            return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(step_id="advanced", data_schema=self._get_advanced_schema(self._data))

    def _get_advanced_schema(self, data: dict[str, Any] | None = None) -> vol.Schema:
        """Get the advanced settings schema."""
        if data is None:
            data = {}
        return vol.Schema(
            {
                vol.Optional(CONF_NOTES, default=data.get(CONF_NOTES, "")): cv.string,
                vol.Optional(CONF_NOTIFICATIONS, default=data.get(CONF_NOTIFICATIONS, False)): cv.boolean,
                vol.Optional(CONF_CALENDAR_SYNC, default=data.get(CONF_CALENDAR_SYNC, False)): cv.boolean,
                vol.Optional(
                    CONF_CALENDAR_TARGET,
                    default=data.get(CONF_CALENDAR_TARGET, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar")
                ),
                vol.Optional(
                    CONF_CALENDAR_SYNC_DAYS,
                    default=data.get(CONF_CALENDAR_SYNC_DAYS, 120),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=7, max=365, mode=selector.NumberSelectorMode.BOX, step=1
                    )
                ),
                vol.Optional(
                    CONF_CALENDAR_SYNC_INTERVAL_HOURS,
                    default=data.get(CONF_CALENDAR_SYNC_INTERVAL_HOURS, 1),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=24, mode=selector.NumberSelectorMode.BOX, step=1
                    )
                ),
                vol.Optional(
                    CONF_HOLIDAY_API_URL,
                    default=data.get(CONF_HOLIDAY_API_URL, ""),
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
        # Initialize with existing data to preserve all options
        self._data: dict[str, Any] = {**entry.data, **(entry.options or {})}
        self._selected_exception_id: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "custody": "Garde classique",
                "schedule": "Horaires et lieu",
                "vacations": "Vacances scolaires",
                "exceptions": "Exceptions",
                "advanced": "Options avancées",
            },
        )

    async def async_step_custody(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modify garde classique (custody type, reference year, and start day)."""
        if user_input:
            cleaned = dict(user_input)
            # For alternate_weekend/alternate_week_parity, start_day is not used (based on ISO week parity)
            self._data.update(cleaned)
            return self.async_create_entry(title="", data=self._data)

        data = {**self._entry.data, **(self._entry.options or {})}
        custody_type = data.get(CONF_CUSTODY_TYPE, "alternate_week")
        # start_day is only relevant for custody types that use cycles (not alternate_weekend/alternate_week_parity)
        show_start_day = custody_type not in ("alternate_weekend", "alternate_week_parity")
        
        reference_year_default = data.get(
            CONF_REFERENCE_YEAR_CUSTODY, data.get(CONF_REFERENCE_YEAR, "even")
        )
        schema_dict = {
            vol.Required(
                CONF_CUSTODY_TYPE, default=custody_type
            ): _custody_type_selector(),
            vol.Required(
                CONF_REFERENCE_YEAR_CUSTODY, default=reference_year_default
            ): _reference_year_selector(),
        }
        
        # Only show start_day for custody types that use it
        if show_start_day:
            schema_dict[vol.Required(
                CONF_START_DAY, default=data.get(CONF_START_DAY, "monday")
            )] = _start_day_selector()
        
        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="custody", data_schema=schema)

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

    async def async_step_exceptions(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage manual exceptions (add/edit/remove)."""
        return self.async_show_menu(
            step_id="exceptions",
            menu_options={
                "exceptions_add": "Ajouter",
                "exceptions_edit": "Modifier",
                "exceptions_delete": "Supprimer",
                "exceptions_recurring_add": "Ajouter récurrente",
                "exceptions_recurring_edit": "Modifier récurrente",
                "exceptions_recurring_delete": "Supprimer récurrente",
                "init": "Retour",
            },
        )

    async def async_step_exceptions_add(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Add a new exception window."""
        errors: dict[str, str] = {}
        if user_input:
            start = _normalize_datetime(user_input.get("start"))
            end = _normalize_datetime(user_input.get("end"))
            if not start or not end or end <= start:
                errors["base"] = "end_before_start"
            if not errors:
                label = str(user_input.get("label") or "Exception").strip() or "Exception"
                new_item = {
                    "id": uuid.uuid4().hex,
                    "label": label,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
                exceptions = _get_exceptions(self._data)
                exceptions.append(new_item)
                self._data[CONF_EXCEPTIONS_LIST] = exceptions
                return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Optional("label"): cv.string,
                vol.Required("start"): selector.DateTimeSelector(),
                vol.Required("end"): selector.DateTimeSelector(),
            }
        )
        return self.async_show_form(step_id="exceptions_add", data_schema=schema, errors=errors)

    async def async_step_exceptions_edit(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Select an exception to edit."""
        exceptions = _get_exceptions(self._data)
        if not exceptions:
            return self.async_show_form(
                step_id="exceptions_edit",
                data_schema=vol.Schema({}),
                errors={"base": "no_exceptions"},
            )

        if user_input:
            self._selected_exception_id = user_input.get("exception_id")
            return await self.async_step_exceptions_edit_form()

        schema = vol.Schema(
            {
                vol.Required("exception_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": item.get("id", ""),
                                "label": _format_exception_label(item),
                            }
                            for item in exceptions
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="exceptions_edit", data_schema=schema)

    async def async_step_exceptions_edit_form(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit the selected exception."""
        errors: dict[str, str] = {}
        exceptions = _get_exceptions(self._data)
        selected = next((item for item in exceptions if item.get("id") == self._selected_exception_id), None)
        if not selected:
            return await self.async_step_exceptions_edit()

        if user_input:
            start = _normalize_datetime(user_input.get("start"))
            end = _normalize_datetime(user_input.get("end"))
            if not start or not end or end <= start:
                errors["base"] = "end_before_start"
            if not errors:
                selected["label"] = str(user_input.get("label") or selected.get("label") or "Exception").strip()
                selected["start"] = start.isoformat()
                selected["end"] = end.isoformat()
                self._data[CONF_EXCEPTIONS_LIST] = exceptions
                return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Optional("label", default=selected.get("label", "")): cv.string,
                vol.Required("start", default=_normalize_datetime(selected.get("start"))): selector.DateTimeSelector(),
                vol.Required("end", default=_normalize_datetime(selected.get("end"))): selector.DateTimeSelector(),
            }
        )
        return self.async_show_form(step_id="exceptions_edit_form", data_schema=schema, errors=errors)

    async def async_step_exceptions_delete(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Delete an exception."""
        exceptions = _get_exceptions(self._data)
        if not exceptions:
            return self.async_show_form(
                step_id="exceptions_delete",
                data_schema=vol.Schema({}),
                errors={"base": "no_exceptions"},
            )

        if user_input:
            exception_id = user_input.get("exception_id")
            self._data[CONF_EXCEPTIONS_LIST] = [
                item for item in exceptions if item.get("id") != exception_id
            ]
            return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Required("exception_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": item.get("id", ""),
                                "label": _format_exception_label(item),
                            }
                            for item in exceptions
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="exceptions_delete", data_schema=schema)

    async def async_step_exceptions_recurring_add(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a recurring exception."""
        errors: dict[str, str] = {}
        if user_input:
            start_time = _normalize_time(user_input.get("start_time"))
            end_time = _normalize_time(user_input.get("end_time"))
            if not start_time or not end_time or end_time <= start_time:
                errors["base"] = "end_before_start"
            if not errors:
                label = str(user_input.get("label") or "Exception récurrente").strip() or "Exception récurrente"
                new_item = {
                    "id": uuid.uuid4().hex,
                    "label": label,
                    "weekday": int(user_input.get("weekday")),
                    "start_time": start_time.strftime("%H:%M"),
                    "end_time": end_time.strftime("%H:%M"),
                    "start_date": user_input.get("start_date") or None,
                    "end_date": user_input.get("end_date") or None,
                }
                exceptions = _get_recurring_exceptions(self._data)
                exceptions.append(new_item)
                self._data[CONF_EXCEPTIONS_RECURRING] = exceptions
                return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Optional("label"): cv.string,
                vol.Required("weekday"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": 0, "label": "Lundi"},
                            {"value": 1, "label": "Mardi"},
                            {"value": 2, "label": "Mercredi"},
                            {"value": 3, "label": "Jeudi"},
                            {"value": 4, "label": "Vendredi"},
                            {"value": 5, "label": "Samedi"},
                            {"value": 6, "label": "Dimanche"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("start_time"): selector.TimeSelector(),
                vol.Required("end_time"): selector.TimeSelector(),
                vol.Optional("start_date"): selector.DateSelector(),
                vol.Optional("end_date"): selector.DateSelector(),
            }
        )
        return self.async_show_form(
            step_id="exceptions_recurring_add", data_schema=schema, errors=errors
        )

    async def async_step_exceptions_recurring_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select a recurring exception to edit."""
        exceptions = _get_recurring_exceptions(self._data)
        if not exceptions:
            return self.async_show_form(
                step_id="exceptions_recurring_edit",
                data_schema=vol.Schema({}),
                errors={"base": "no_exceptions"},
            )

        if user_input:
            self._selected_exception_id = user_input.get("exception_id")
            return await self.async_step_exceptions_recurring_edit_form()

        schema = vol.Schema(
            {
                vol.Required("exception_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": item.get("id", ""),
                                "label": _format_recurring_label(item),
                            }
                            for item in exceptions
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="exceptions_recurring_edit", data_schema=schema)

    async def async_step_exceptions_recurring_edit_form(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the selected recurring exception."""
        errors: dict[str, str] = {}
        exceptions = _get_recurring_exceptions(self._data)
        selected = next((item for item in exceptions if item.get("id") == self._selected_exception_id), None)
        if not selected:
            return await self.async_step_exceptions_recurring_edit()

        if user_input:
            start_time = _normalize_time(user_input.get("start_time"))
            end_time = _normalize_time(user_input.get("end_time"))
            if not start_time or not end_time or end_time <= start_time:
                errors["base"] = "end_before_start"
            if not errors:
                selected["label"] = str(user_input.get("label") or selected.get("label") or "Exception").strip()
                selected["weekday"] = int(user_input.get("weekday"))
                selected["start_time"] = start_time.strftime("%H:%M")
                selected["end_time"] = end_time.strftime("%H:%M")
                selected["start_date"] = user_input.get("start_date") or None
                selected["end_date"] = user_input.get("end_date") or None
                self._data[CONF_EXCEPTIONS_RECURRING] = exceptions
                return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Optional("label", default=selected.get("label", "")): cv.string,
                vol.Required("weekday", default=selected.get("weekday", 0)): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": 0, "label": "Lundi"},
                            {"value": 1, "label": "Mardi"},
                            {"value": 2, "label": "Mercredi"},
                            {"value": 3, "label": "Jeudi"},
                            {"value": 4, "label": "Vendredi"},
                            {"value": 5, "label": "Samedi"},
                            {"value": 6, "label": "Dimanche"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("start_time", default=_normalize_time(selected.get("start_time"))): selector.TimeSelector(),
                vol.Required("end_time", default=_normalize_time(selected.get("end_time"))): selector.TimeSelector(),
                vol.Optional("start_date", default=_normalize_date(selected.get("start_date"))): selector.DateSelector(),
                vol.Optional("end_date", default=_normalize_date(selected.get("end_date"))): selector.DateSelector(),
            }
        )
        return self.async_show_form(
            step_id="exceptions_recurring_edit_form", data_schema=schema, errors=errors
        )

    async def async_step_exceptions_recurring_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete a recurring exception."""
        exceptions = _get_recurring_exceptions(self._data)
        if not exceptions:
            return self.async_show_form(
                step_id="exceptions_recurring_delete",
                data_schema=vol.Schema({}),
                errors={"base": "no_exceptions"},
            )

        if user_input:
            exception_id = user_input.get("exception_id")
            self._data[CONF_EXCEPTIONS_RECURRING] = [
                item for item in exceptions if item.get("id") != exception_id
            ]
            return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Required("exception_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": item.get("id", ""),
                                "label": _format_recurring_label(item),
                            }
                            for item in exceptions
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="exceptions_recurring_delete", data_schema=schema)

    async def async_step_vacations(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Modify vacances scolaires (school zone and vacation rules)."""
        if user_input:
            cleaned = dict(user_input)
            # Convert empty strings to None for optional fields
            if cleaned.get(CONF_SUMMER_RULE) == "":
                cleaned[CONF_SUMMER_RULE] = None
            if cleaned.get(CONF_JULY_RULE) == "":
                cleaned[CONF_JULY_RULE] = None
            if cleaned.get(CONF_AUGUST_RULE) == "":
                cleaned[CONF_AUGUST_RULE] = None
            self._data.update(cleaned)
            return self.async_create_entry(title="", data=self._data)

        data = {**self._entry.data, **(self._entry.options or {})}
        # Convert None to empty string for selectors
        summer_rule_default = data.get(CONF_SUMMER_RULE) or ""
        july_rule_default = data.get(CONF_JULY_RULE) or ""
        august_rule_default = data.get(CONF_AUGUST_RULE) or ""
        # Get reference_year for vacations (separate from custody reference_year)
        reference_year_default = data.get(
            CONF_REFERENCE_YEAR_VACATIONS, data.get(CONF_REFERENCE_YEAR, "even")
        )
        vacation_split_default = data.get(CONF_VACATION_SPLIT_MODE, "odd_first")
        
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE, default=data.get(CONF_ZONE, "A")): _zone_selector(),
                vol.Required(CONF_REFERENCE_YEAR_VACATIONS, default=reference_year_default): _reference_year_selector(),
                vol.Optional(CONF_VACATION_SPLIT_MODE, default=vacation_split_default): _vacation_split_selector(),
                vol.Optional(
                    CONF_SCHOOL_LEVEL, default=data.get(CONF_SCHOOL_LEVEL, "primary")
                ): _school_level_selector(),
                vol.Optional(CONF_JULY_RULE, default=july_rule_default): _july_rule_selector(),
                vol.Optional(CONF_AUGUST_RULE, default=august_rule_default): _august_rule_selector(),
                vol.Optional(CONF_SUMMER_RULE, default=summer_rule_default): _summer_rule_selector(),
            }
        )
        return self.async_show_form(step_id="vacations", data_schema=schema)

    async def async_step_advanced(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Advanced optional settings."""
        if user_input:
            cleaned = dict(user_input)
            errors: dict[str, str] = {}
            calendar_sync = cleaned.get(CONF_CALENDAR_SYNC, False)
            calendar_target = cleaned.get(CONF_CALENDAR_TARGET, "") or ""
            if calendar_sync and not str(calendar_target).strip():
                errors[CONF_CALENDAR_TARGET] = "calendar_target_required"

            # Validate API URL if provided
            api_url = cleaned.get(CONF_HOLIDAY_API_URL)
            if api_url and api_url.strip():
                # Basic validation: must contain {year} and {zone} placeholders
                if "{year}" not in api_url or "{zone}" not in api_url:
                    # Merge user input with existing data to preserve user's entry
                    data = {**self._entry.data, **(self._entry.options or {})}
                    merged_data = {**data, **cleaned}
                    return self.async_show_form(
                        step_id="advanced",
                        data_schema=self._get_advanced_schema(merged_data),
                        errors={**errors, CONF_HOLIDAY_API_URL: "api_url_missing_placeholders"},
                    )
                cleaned[CONF_HOLIDAY_API_URL] = api_url.strip()
            else:
                cleaned.pop(CONF_HOLIDAY_API_URL, None)
            if errors:
                data = {**self._entry.data, **(self._entry.options or {})}
                merged_data = {**data, **cleaned}
                return self.async_show_form(
                    step_id="advanced",
                    data_schema=self._get_advanced_schema(merged_data),
                    errors=errors,
                )
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
                vol.Optional(
                    CONF_CALENDAR_TARGET,
                    default=data.get(CONF_CALENDAR_TARGET, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar")
                ),
                vol.Optional(
                    CONF_CALENDAR_SYNC_DAYS,
                    default=data.get(CONF_CALENDAR_SYNC_DAYS, 120),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=7, max=365, mode=selector.NumberSelectorMode.BOX, step=1
                    )
                ),
                vol.Optional(
                    CONF_CALENDAR_SYNC_INTERVAL_HOURS,
                    default=data.get(CONF_CALENDAR_SYNC_INTERVAL_HOURS, 1),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=24, mode=selector.NumberSelectorMode.BOX, step=1
                    )
                ),
                vol.Optional(
                    CONF_HOLIDAY_API_URL,
                    default=data.get(CONF_HOLIDAY_API_URL, ""),
                    description={"suggested_value": HOLIDAY_API},
                ): cv.string,
            }
        )
