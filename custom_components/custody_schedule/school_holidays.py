"""School holiday helper for Custody Schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.util import dt as dt_util

from .const import HOLIDAY_API, LOGGER


@dataclass(frozen=True, slots=True)
class SchoolHoliday:
    """Represent a school holiday period."""

    name: str
    zone: str
    start: datetime
    end: datetime


class SchoolHolidayClient:
    """Simple cached client around the Education Nationale API."""

    def __init__(self, hass: HomeAssistant, api_url: str | None = None) -> None:
        self._hass = hass
        self._session = aiohttp_client.async_get_clientsession(hass)
        self._cache: dict[tuple[str, str], list[SchoolHoliday]] = {}
        self._api_url = api_url or HOLIDAY_API

    def _get_school_year(self, date: datetime) -> str:
        """Convert a calendar date to school year format (e.g., '2024-2025').
        
        School year in France runs from September to June.
        If date is before September, it belongs to the previous school year.
        """
        year = date.year
        # If before September, it's the previous school year
        if date.month < 9:
            return f"{year - 1}-{year}"
        return f"{year}-{year + 1}"

    def _normalize_zone(self, zone: str) -> str:
        """Normalize zone name for API compatibility.
        
        The API uses specific zone names. For DOM-TOM, we default to Guadeloupe
        as it's the most common. Users can configure a specific territory if needed.
        """
        zone_mapping = {
            "Corse": "Corse",
            "DOM-TOM": "Guadeloupe",  # Default to Guadeloupe for DOM-TOM
            # Other DOM-TOM territories available: Martinique, Guyane, La Réunion, Mayotte
        }
        return zone_mapping.get(zone, zone)

    async def async_list(self, zone: str, year: int | None = None) -> list[SchoolHoliday]:
        """Return all holidays for the provided zone.
        
        If year is provided, fetches for that calendar year's school year(s).
        Otherwise, uses current date to determine school year.
        """
        now = dt_util.utcnow()
        
        # Get school years that might contain holidays for this calendar year
        # A calendar year can span two school years (e.g., 2024 spans 2023-2024 and 2024-2025)
        school_years = set()
        
        if year is not None:
            # For a given calendar year, we need to check:
            # 1. The school year that started in September of (year-1) and ends in June of year
            # 2. The school year that starts in September of year and ends in June of (year+1)
            school_years.add(f"{year - 1}-{year}")
            school_years.add(f"{year}-{year + 1}")
        else:
            # Use current date to determine relevant school years directly
            current_school_year = self._get_school_year(now)
            school_years.add(current_school_year)
            # Also get next school year to ensure we have summer holidays
            # Parse current school year to get next one
            parts = current_school_year.split("-")
            if len(parts) == 2:
                next_year_start = int(parts[1])
                school_years.add(f"{next_year_start}-{next_year_start + 1}")

        normalized_zone = self._normalize_zone(zone)
        all_holidays: list[SchoolHoliday] = []
        
        for school_year in school_years:
            cache_key = (normalized_zone, school_year)
            if cache_key in self._cache:
                all_holidays.extend(self._cache[cache_key])
                continue

            url = self._api_url.format(zone=normalized_zone, year=school_year)
            try:
                LOGGER.info("Fetching school holidays from API: %s", url)
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    resp.raise_for_status()
                    payload: dict[str, Any] = await resp.json()
            except aiohttp.ClientError as err:
                LOGGER.warning(
                    "Failed to fetch school holidays for zone %s, year %s: %s",
                    normalized_zone,
                    school_year,
                    err,
                )
                self._cache[cache_key] = []
                continue
            except Exception as err:
                LOGGER.error(
                    "Unexpected error fetching school holidays for zone %s, year %s: %s",
                    normalized_zone,
                    school_year,
                    err,
                )
                self._cache[cache_key] = []
                continue

            holidays: list[SchoolHoliday] = []
            records = payload.get("records", [])
            LOGGER.info("Found %d records for zone %s, year %s", len(records), normalized_zone, school_year)
            
            for record in records:
                fields = record.get("fields", {})
                start_str = fields.get("start_date") or fields.get("date_debut")
                end_str = fields.get("end_date") or fields.get("date_fin")
                name = fields.get("description") or fields.get("libelle") or "Vacances scolaires"
                
                if not start_str or not end_str:
                    LOGGER.debug("Skipping record with missing dates: %s", fields)
                    continue
                
                start = dt_util.parse_datetime(start_str)
                end = dt_util.parse_datetime(end_str)
                
                if not start or not end:
                    LOGGER.debug("Failed to parse dates: start=%s, end=%s", start_str, end_str)
                    continue
                
                # Filter holidays that overlap with the requested calendar year if specified
                if year is not None:
                    # Include holidays that:
                    # - Start or end in the requested year, OR
                    # - Span across the requested year (start before and end after)
                    if not (start.year == year or end.year == year or (start.year < year < end.year)):
                        continue
                
                holidays.append(
                    SchoolHoliday(
                        name=name,
                        zone=zone,  # Keep original zone name
                        start=dt_util.as_local(start),
                        end=dt_util.as_local(end),
                    )
                )

            holidays.sort(key=lambda holiday: holiday.start)
            self._cache[cache_key] = holidays
            all_holidays.extend(holidays)

        # Remove duplicates and sort
        seen = set()
        unique_holidays = []
        for holiday in sorted(all_holidays, key=lambda h: (h.start, h.end)):
            key = (holiday.name, holiday.start, holiday.end)
            if key not in seen:
                seen.add(key)
                unique_holidays.append(holiday)

        LOGGER.info("Returning %d unique holidays for zone %s", len(unique_holidays), zone)
        return unique_holidays

    async def async_test_connection(self, zone: str, year: str | None = None) -> dict[str, Any]:
        """Test the API connection and return diagnostic information."""
        if year is None:
            now = dt_util.utcnow()
            year = self._get_school_year(now)
        
        normalized_zone = self._normalize_zone(zone)
        url = self._api_url.format(zone=normalized_zone, year=year)
        
        result = {
            "url": url,
            "zone": zone,
            "normalized_zone": normalized_zone,
            "school_year": year,
            "success": False,
            "error": None,
            "records_count": 0,
            "holidays_count": 0,
        }
        
        try:
            LOGGER.info("Testing API connection: %s", url)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                result["status_code"] = resp.status
                resp.raise_for_status()
                payload: dict[str, Any] = await resp.json()
                records = payload.get("records", [])
                result["records_count"] = len(records)
                
                # Parse holidays
                holidays = []
                for record in records:
                    fields = record.get("fields", {})
                    start_str = fields.get("start_date") or fields.get("date_debut")
                    end_str = fields.get("end_date") or fields.get("date_fin")
                    if start_str and end_str:
                        holidays.append({
                            "name": fields.get("description") or fields.get("libelle", "Vacances scolaires"),
                            "start": start_str,
                            "end": end_str,
                        })
                
                result["holidays_count"] = len(holidays)
                result["holidays"] = holidays[:5]  # Limit to first 5 for display
                result["success"] = True
                LOGGER.info("API test successful: %d holidays found", len(holidays))
                
        except aiohttp.ClientError as err:
            result["error"] = str(err)
            LOGGER.error("API test failed: %s", err)
        except Exception as err:
            result["error"] = str(err)
            LOGGER.error("API test unexpected error: %s", err)
        
        return result

    def clear(self) -> None:
        """Drop the local cache."""
        self._cache.clear()
