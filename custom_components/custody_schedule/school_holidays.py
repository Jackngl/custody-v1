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
        
        The API uses "Zone A", "Zone B", "Zone C" format in the zones field,
        but the refine.zones filter might need just "A", "B", "C".
        However, testing shows the filter doesn't work well, so we'll fetch all
        and filter manually.
        """
        zone_mapping = {
            "Corse": "Corse",
            "DOM-TOM": "Guadeloupe",  # Default to Guadeloupe for DOM-TOM
            # Other DOM-TOM territories available: Martinique, Guyane, La Réunion, Mayotte
        }
        # For zones A, B, C, keep as is for now (we'll filter manually)
        return zone_mapping.get(zone, zone)

    async def async_list(self, zone: str, year: int | None = None) -> list[SchoolHoliday]:
        """Return all holidays for the provided zone.
        
        If year is provided, fetches for that calendar year's school year(s).
        Otherwise, uses current date to determine school year.
        """
        # Use local timezone for school year determination (French school years are calendar-based)
        now = dt_util.now()
        
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

            try:
                url = self._api_url.format(zone=normalized_zone, year=school_year)
            except KeyError as err:
                LOGGER.error(
                    "Invalid API URL format: missing placeholder %s. URL: %s",
                    err,
                    self._api_url,
                )
                self._cache[cache_key] = []
                continue
            except Exception as err:
                LOGGER.error(
                    "Error formatting API URL for zone %s, year %s: %s. URL template: %s",
                    normalized_zone,
                    school_year,
                    err,
                    self._api_url,
                )
                self._cache[cache_key] = []
                continue

            try:
                LOGGER.info("Fetching school holidays from API: %s", url)
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    status = resp.status
                    resp.raise_for_status()
                    try:
                        payload: dict[str, Any] = await resp.json()
                    except Exception as json_err:
                        text = await resp.text()
                        LOGGER.error(
                            "Failed to parse JSON response for zone %s, year %s. Status: %s, Response: %s. Error: %s",
                            normalized_zone,
                            school_year,
                            status,
                            text[:500],  # Limit response text to 500 chars
                            json_err,
                        )
                        self._cache[cache_key] = []
                        continue
            except aiohttp.ClientError as err:
                LOGGER.warning(
                    "Failed to fetch school holidays for zone %s, year %s: %s (URL: %s)",
                    normalized_zone,
                    school_year,
                    err,
                    url,
                )
                self._cache[cache_key] = []
                continue
            except Exception as err:
                import traceback
                LOGGER.error(
                    "Unexpected error fetching school holidays for zone %s, year %s: %s (type: %s). URL: %s. Traceback: %s",
                    normalized_zone,
                    school_year,
                    err,
                    type(err).__name__,
                    url,
                    traceback.format_exc(),
                )
                self._cache[cache_key] = []
                continue

            holidays: list[SchoolHoliday] = []
            records = payload.get("records", [])
            LOGGER.info("Found %d records for zone %s (normalized: %s), year %s", 
                       len(records), zone, normalized_zone, school_year)
            
            # If no records with zone filter, try fetching all and filtering manually
            # Also handle case where API might not return all holidays (e.g., Zone C winter 2025-2026)
            if len(records) == 0 and normalized_zone in ["A", "B", "C"]:
                LOGGER.debug("No records with zone filter, trying without filter and filtering manually")
                url_all = (
                    "https://data.education.gouv.fr/api/records/1.0/search/"
                    f"?dataset=fr-en-calendrier-scolaire"
                    f"&refine.annee_scolaire={school_year}"
                    f"&rows=100"
                )
                try:
                    async with self._session.get(url_all, timeout=aiohttp.ClientTimeout(total=20)) as resp2:
                        resp2.raise_for_status()
                        payload_all = await resp2.json()
                        records_all = payload_all.get("records", [])
                        LOGGER.debug("Found %d total records without zone filter", len(records_all))
                        
                        # Filter manually for the zone
                        for r in records_all:
                            fields = r.get("fields", {})
                            zone_field = fields.get("zones") or fields.get("zone") or ""
                            # Check if zone matches (could be "Zone C", "C", or contain "C")
                            if normalized_zone in str(zone_field) or f"Zone {normalized_zone}" in str(zone_field):
                                records.append(r)
                        LOGGER.info("After manual filtering, found %d records for zone %s", len(records), zone)
                except Exception as err:
                    LOGGER.warning("Failed to fetch all records for manual filtering: %s", err)
            
            if len(records) == 0:
                LOGGER.warning("No records found for zone %s (normalized: %s), year %s. "
                              "This might indicate an API issue or incorrect zone name.", 
                              zone, normalized_zone, school_year)
            
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

        # Manual override for Zone C winter holidays 2025-2026
        # API returns 20/02/2026 23:00 UTC -> 08/03/2026 23:00 UTC
        # Which becomes 21/02/2026 00:00 local -> 09/03/2026 00:00 local
        # Official calendar confirms: 21/02/2026 -> 09/03/2026
        if normalized_zone == "C":
            # Check if we need to add or correct winter holidays 2025-2026
            winter_2026_start = dt_util.parse_datetime("2026-02-21T00:00:00+01:00")
            winter_2026_end = dt_util.parse_datetime("2026-03-09T23:59:59+01:00")
            
            if winter_2026_start and winter_2026_end:
                winter_2026_start = dt_util.as_local(winter_2026_start)
                winter_2026_end = dt_util.as_local(winter_2026_end)
                
                # Check if winter holidays 2025-2026 are already present
                has_winter_2026 = False
                for h in unique_holidays:
                    if "hiver" in h.name.lower() and h.start.year == 2026 and h.start.month == 2:
                        has_winter_2026 = True
                        # Update dates if they're incorrect
                        if h.start != winter_2026_start or h.end != winter_2026_end:
                            LOGGER.info("Correcting Zone C winter holidays 2025-2026 dates: %s -> %s / %s -> %s", 
                                      h.start, winter_2026_start, h.end, winter_2026_end)
                            h.start = winter_2026_start
                            h.end = winter_2026_end
                        break
                
                # Add if missing
                if not has_winter_2026:
                    LOGGER.info("Adding manual override for Zone C winter holidays 2025-2026: %s -> %s", 
                              winter_2026_start, winter_2026_end)
                    unique_holidays.append(
                        SchoolHoliday(
                            name="Vacances d'Hiver",
                            zone=zone,
                            start=winter_2026_start,
                            end=winter_2026_end,
                        )
                    )
                    # Re-sort after adding
                    unique_holidays.sort(key=lambda h: (h.start, h.end))

        LOGGER.info("Returning %d unique holidays for zone %s", len(unique_holidays), zone)
        return unique_holidays

    async def async_test_connection(self, zone: str, year: str | None = None) -> dict[str, Any]:
        """Test the API connection and return diagnostic information."""
        if year is None:
            # Use local timezone for school year determination
            now = dt_util.now()
            year = self._get_school_year(now)
        
        normalized_zone = self._normalize_zone(zone)
        
        result = {
            "url": None,
            "zone": zone,
            "normalized_zone": normalized_zone,
            "school_year": year,
            "success": False,
            "error": None,
            "error_type": None,
            "status_code": None,
            "records_count": 0,
            "holidays_count": 0,
        }
        
        try:
            url = self._api_url.format(zone=normalized_zone, year=year)
            result["url"] = url
        except KeyError as err:
            result["error"] = f"Invalid API URL format: missing placeholder {err}"
            result["error_type"] = "KeyError"
            LOGGER.error("API test failed: %s. URL template: %s", result["error"], self._api_url)
            return result
        except Exception as err:
            result["error"] = f"Error formatting URL: {err}"
            result["error_type"] = type(err).__name__
            LOGGER.error("API test failed: %s", result["error"])
            return result
        
        try:
            LOGGER.info("Testing API connection: %s", url)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                result["status_code"] = resp.status
                resp.raise_for_status()
                try:
                    payload: dict[str, Any] = await resp.json()
                except Exception as json_err:
                    text = await resp.text()
                    result["error"] = f"Failed to parse JSON: {json_err}. Response: {text[:200]}"
                    result["error_type"] = type(json_err).__name__
                    LOGGER.error("API test failed to parse JSON: %s", result["error"])
                    return result
                
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
            result["error_type"] = type(err).__name__
            LOGGER.error("API test failed (ClientError): %s", err)
        except Exception as err:
            import traceback
            result["error"] = str(err)
            result["error_type"] = type(err).__name__
            LOGGER.error("API test unexpected error: %s (type: %s). Traceback: %s", err, type(err).__name__, traceback.format_exc())
        
        return result

    def clear(self) -> None:
        """Drop the local cache."""
        self._cache.clear()
