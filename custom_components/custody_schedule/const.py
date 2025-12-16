"""Constants for the Custody Schedule integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)

DOMAIN = "custody_schedule"
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.CALENDAR,
]
UPDATE_INTERVAL = timedelta(minutes=15)
# API du calendrier scolaire français (data.education.gouv.fr)
# Format année scolaire: "2024-2025" (septembre à juin)
# Zones: A, B, C, Corse, Guadeloupe, Martinique, Guyane, La Réunion, Mayotte, etc.
HOLIDAY_API = (
    "https://data.education.gouv.fr/api/records/1.0/search/"
    "?dataset=fr-en-calendrier-scolaire"
    "&refine.annee_scolaire={year}"
    "&refine.zones={zone}"
    "&rows=100"
)

CONF_CHILD_NAME = "child_name"
CONF_CHILD_NAME_DISPLAY = "child_name_display"
CONF_ICON = "icon"
CONF_PHOTO = "photo"
CONF_CUSTODY_TYPE = "custody_type"
CONF_REFERENCE_YEAR = "reference_year"
CONF_START_DAY = "start_day"
CONF_ARRIVAL_TIME = "arrival_time"
CONF_DEPARTURE_TIME = "departure_time"
CONF_LOCATION = "location"
CONF_NOTES = "notes"
CONF_ZONE = "zone"
CONF_VACATION_RULE = "vacation_rule"
CONF_SUMMER_RULE = "summer_rule"
CONF_NOTIFICATIONS = "notifications"
CONF_CALENDAR_SYNC = "calendar_sync"
CONF_EXCEPTIONS = "exceptions"
CONF_CUSTOM_RULES = "custom_rules"
CONF_HOLIDAY_API_URL = "holiday_api_url"

REFERENCE_YEARS = ["even", "odd"]

# Zones étendues avec libellés pour l'UI
FRENCH_ZONES = ["A", "B", "C", "Corse", "DOM-TOM"]
FRENCH_ZONES_WITH_CITIES: dict[str, str] = {
    "A": "Zone A — Besançon, Bordeaux, Clermont-Ferrand, Dijon, Grenoble, Limoges, Lyon, Poitiers",
    "B": "Zone B — Aix-Marseille, Amiens, Lille, Nancy-Metz, Nantes, Nice, Normandie, Orléans-Tours, Reims, Rennes, Strasbourg",
    "C": "Zone C — Créteil, Montpellier, Paris, Toulouse, Versailles",
    "Corse": "Corse",
    "DOM-TOM": "DOM-TOM",
}

VACATION_RULES = [
    "first_week",
    "second_week",
    "first_half",
    "second_half",
    "even_weeks",
    "odd_weeks",
    "july",
    "august",
    "first_week_even_year",
    "first_week_odd_year",
    "second_week_even_year",
    "second_week_odd_year",
    "custom",
]
SUMMER_RULES = [
    "july_first_half",
    "july_second_half",
    "july_even_weeks",
    "july_odd_weeks",
    "august_first_half",
    "august_second_half",
    "august_even_weeks",
    "august_odd_weeks",
    "july_even_year",
    "july_odd_year",
    "august_even_year",
    "august_odd_year",
]

CUSTODY_TYPES = {
    "alternate_week": {
        "label": "Alternating Weeks",
        "cycle_days": 14,
        "pattern": [
            {"days": 7, "state": "on"},
            {"days": 7, "state": "off"},
        ],
    },
    "alternate_weekend": {
        "label": "Alternating Weekends",
        "cycle_days": 14,
        "pattern": [
            {"days": 12, "state": "off"},
            {"days": 2, "state": "on"},
        ],
    },
    "even_weekends": {
        "label": "Week-ends semaines paires",
        "cycle_days": 7,
        "pattern": [],
    },
    "odd_weekends": {
        "label": "Week-ends semaines impaires",
        "cycle_days": 7,
        "pattern": [],
    },
    "two_two_three": {
        "label": "2-2-3",
        "cycle_days": 7,
        "pattern": [
            {"days": 2, "state": "on"},
            {"days": 2, "state": "off"},
            {"days": 3, "state": "on"},
        ],
    },
    "two_two_five_five": {
        "label": "2-2-5-5",
        "cycle_days": 14,
        "pattern": [
            {"days": 2, "state": "on"},
            {"days": 2, "state": "off"},
            {"days": 5, "state": "on"},
            {"days": 5, "state": "off"},
        ],
    },
    "custom": {
        "label": "Custom",
        "cycle_days": 14,
        "pattern": [],
    },
}

ATTR_NEXT_ARRIVAL = "next_arrival"
ATTR_NEXT_DEPARTURE = "next_departure"
ATTR_CUSTODY_TYPE = "custody_type"
ATTR_CURRENT_PERIOD = "current_period"
ATTR_VACATION_NAME = "vacation_name"
ATTR_ZONE = "zone"
ATTR_LOCATION = "location"
ATTR_NOTES = "notes"
ATTR_DAYS_REMAINING = "days_remaining"

SERVICE_SET_MANUAL_DATES = "set_manual_dates"
SERVICE_OVERRIDE_PRESENCE = "override_presence"
SERVICE_REFRESH_SCHEDULE = "refresh_schedule"
SERVICE_TEST_HOLIDAY_API = "test_holiday_api"
