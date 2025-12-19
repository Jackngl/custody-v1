"""Schedule helpers for the Custody Schedule integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


def _easter_date(year: int) -> date:
    """Calculate Easter Sunday date using the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_french_holidays(year: int) -> set[date]:
    """Return set of French public holidays for a given year.
    
    Calculates all official French public holidays (jours fériés).
    Note: Holidays that fall during school vacations are automatically excluded
    from custody extensions (vacations have priority).
    """
    holidays = set()
    
    # Fixed holidays
    holidays.add(date(year, 1, 1))    # Jour de l'An
    holidays.add(date(year, 5, 1))    # Fête du Travail
    holidays.add(date(year, 5, 8))    # Victoire 1945
    holidays.add(date(year, 7, 14))   # Fête Nationale
    holidays.add(date(year, 8, 15))   # Assomption
    holidays.add(date(year, 11, 1))   # Toussaint
    holidays.add(date(year, 11, 11))  # Armistice
    holidays.add(date(year, 12, 25))  # Noël
    
    # Variable holidays based on Easter
    easter = _easter_date(year)
    holidays.add(easter + timedelta(days=1))   # Lundi de Pâques
    holidays.add(easter + timedelta(days=39))  # Jeudi de l'Ascension
    holidays.add(easter + timedelta(days=50))  # Lundi de Pentecôte
    
    return holidays

from .const import (
    ATTR_LOCATION,
    ATTR_NOTES,
    ATTR_ZONE,
    CONF_ARRIVAL_TIME,
    CONF_CUSTOM_RULES,
    CONF_DEPARTURE_TIME,
    CONF_LOCATION,
    CONF_NOTES,
    CONF_REFERENCE_YEAR,
    CONF_SCHOOL_LEVEL,
    CONF_START_DAY,
    CONF_SUMMER_RULE,
    CONF_ZONE,
    SUMMER_RULES,
    VACATION_RULES,
    CUSTODY_TYPES,
)
from .school_holidays import SchoolHolidayClient


@dataclass(slots=True)
class CustodyWindow:
    """Window representing when the child is present."""

    start: datetime
    end: datetime
    label: str
    source: str = "pattern"


@dataclass(slots=True)
class CustodyComputation:
    """Final state consumed by entities."""

    is_present: bool
    next_arrival: datetime | None
    next_departure: datetime | None
    days_remaining: int | None
    current_period: str
    vacation_name: str | None
    next_vacation_name: str | None = None
    next_vacation_start: datetime | None = None
    next_vacation_end: datetime | None = None
    days_until_vacation: int | None = None
    school_holidays_raw: list[dict[str, Any]] = field(default_factory=list)
    windows: list[CustodyWindow] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


WEEKDAY_LOOKUP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class CustodyScheduleManager:
    """Encapsulate schedule calculations and overrides."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], holidays: SchoolHolidayClient) -> None:
        self._hass = hass
        self._config = config
        self._holidays = holidays
        self._manual_windows: list[CustodyWindow] = []
        self._presence_override: dict[str, Any] | None = None
        self._tz = dt_util.get_time_zone(str(hass.config.time_zone))

        self._arrival_time = self._parse_time(config.get(CONF_ARRIVAL_TIME, "08:00"))
        self._departure_time = self._parse_time(config.get(CONF_DEPARTURE_TIME, "19:00"))

    def update_config(self, new_config: dict[str, Any]) -> None:
        """Update stored config (used when options change)."""
        self._config = {**self._config, **new_config}
        self._arrival_time = self._parse_time(self._config.get(CONF_ARRIVAL_TIME, "08:00"))
        self._departure_time = self._parse_time(self._config.get(CONF_DEPARTURE_TIME, "19:00"))

    def set_manual_windows(self, ranges: Iterable[dict[str, Any]]) -> None:
        """Store manual presence windows defined via service."""
        windows: list[CustodyWindow] = []
        for rng in ranges:
            start_val = rng.get("start")
            end_val = rng.get("end")
            start = start_val if isinstance(start_val, datetime) else dt_util.parse_datetime(start_val)
            end = end_val if isinstance(end_val, datetime) else dt_util.parse_datetime(end_val)
            label = rng.get("label", "Manual custody")
            if not start or not end or end <= start:
                continue
            windows.append(
                CustodyWindow(
                    start=dt_util.as_local(start),
                    end=dt_util.as_local(end),
                    label=label,
                    source="manual",
                )
            )
        self._manual_windows = windows

    def override_presence(self, state: str, duration: timedelta | None = None) -> None:
        """Force the presence state for an optional duration."""
        now = dt_util.now()
        until = now + duration if duration else None
        self._presence_override = {"state": state, "until": until}

    def clear_override(self) -> None:
        """Remove manual override."""
        self._presence_override = None

    async def async_calculate(self, now: datetime) -> CustodyComputation:
        """Build the schedule state used by entities."""
        # now is already in local time (from dt_util.now()), no need to convert
        now_local = now if now.tzinfo else dt_util.as_local(now)
        windows = await self._build_windows(now_local)
        windows.extend(self._manual_windows)
        windows.sort(key=lambda window: window.start)

        current_window = next((window for window in windows if window.start <= now_local < window.end), None)
        next_window = next((window for window in windows if window.start > now_local), None)

        override_state = self._evaluate_override(now_local)
        is_present = override_state if override_state is not None else current_window is not None

        next_arrival = None
        next_departure = None
        if is_present:
            current = current_window if current_window else self._build_virtual_window(now_local)
            next_departure = current.end
            if override_state is True and self._presence_override and self._presence_override["until"]:
                next_departure = self._presence_override["until"]
            elif current_window is None:
                next_departure = now_local
            next_arrival = next_window.start if next_window else None
        else:
            next_arrival = (
                current_window.end
                if current_window and current_window.end > now_local
                else (next_window.start if next_window else None)
            )

        days_remaining = None
        target_dt = next_departure if is_present else next_arrival
        if target_dt:
            delta = target_dt - now_local
            days_remaining = max(0, round(delta.total_seconds() / 86400, 2))

        period, vacation_name = await self._determine_period(now_local)
        
        # Get next vacation information and raw holidays data
        next_vacation_name, next_vacation_start, next_vacation_end, days_until_vacation, school_holidays_raw = await self._get_next_vacation(now_local)

        attributes = {
            ATTR_LOCATION: self._config.get(CONF_LOCATION),
            ATTR_NOTES: self._config.get(CONF_NOTES),
            ATTR_ZONE: self._config.get(CONF_ZONE),
        }

        return CustodyComputation(
            is_present=is_present,
            next_arrival=next_arrival,
            next_departure=next_departure,
            days_remaining=days_remaining,
            current_period=period,
            vacation_name=vacation_name,
            next_vacation_name=next_vacation_name,
            next_vacation_start=next_vacation_start,
            next_vacation_end=next_vacation_end,
            days_until_vacation=days_until_vacation,
            school_holidays_raw=school_holidays_raw,
            windows=windows,
            attributes=attributes,
        )

    async def _build_windows(self, now: datetime) -> list[CustodyWindow]:
        """Generate presence windows from base pattern and vacation/custom rules.
        
        Two separate planning systems:
        1. Weekend/Pattern planning: Based on custody_type (even_weekends, alternate_week, etc.)
        2. Vacation planning: Based on vacation_rule (first_week_odd_year, first_half, etc.)
        
        Priority: Vacation rules > Custom rules > Normal pattern rules
        Vacation periods completely replace normal pattern windows during their entire duration.
        """
        # 1. Generate vacation windows first (needed to check overlaps for public holidays)
        # This creates custody windows during school holidays (e.g., first half, second half)
        # Also creates filter windows that cover the entire vacation period
        vacation_windows = await self._generate_vacation_windows(now)
        
        # 2. Generate weekend/pattern windows based on custody_type
        # This creates the normal weekend schedule (e.g., even weekends, alternate weekends)
        # Pass vacation_windows to check if weekends/weeks fall during vacations before applying public holidays
        pattern_windows = self._generate_pattern_windows(now, vacation_windows)
        
        # 3. Load custom windows (manual overrides)
        custom_windows = self._load_custom_rules()

        # 4. Remove pattern windows that overlap with vacation periods
        # Vacation rules have priority: they completely replace normal rules during vacations
        # Filter windows ensure all weekends/weeks during vacations are removed
        filtered_pattern_windows = self._filter_windows_by_vacations(pattern_windows, vacation_windows)
        
        # 5. Separate display windows from filter windows
        # Filter windows are only used for filtering, not displayed in the final schedule
        vacation_display_windows = [w for w in vacation_windows if w.source != "vacation_filter"]
        
        # 6. Merge in priority order: vacation windows (highest), then custom, then filtered pattern
        merged = vacation_display_windows + custom_windows + filtered_pattern_windows
        return [window for window in merged if window.end > now - timedelta(days=1)]
    
    def _filter_windows_by_vacations(
        self, pattern_windows: list[CustodyWindow], vacation_windows: list[CustodyWindow]
    ) -> list[CustodyWindow]:
        """Remove pattern windows (weekends/weeks) that overlap with vacation periods.
        
        This implements the priority rule: vacations override weekends/weeks.
        Vacation periods completely replace normal custody rules.
        
        Args:
            pattern_windows: Normal weekend/week windows from custody_type
            vacation_windows: Vacation windows including filter windows (source="vacation_filter")
        
        Returns:
            Filtered pattern windows with vacation overlaps removed
        """
        if not vacation_windows:
            return pattern_windows
        
        # Build a list of vacation periods (start, end) for quick overlap checking
        # This includes both actual vacation windows and filter windows
        # Filter windows cover the entire vacation period to ensure all weekends are removed
        vacation_periods = [(vw.start, vw.end) for vw in vacation_windows]
        
        filtered = []
        for pattern_window in pattern_windows:
            # Check if this pattern window (weekend/week) overlaps with any vacation period
            overlaps = False
            for vac_start, vac_end in vacation_periods:
                # Check for overlap: windows overlap if one starts before the other ends
                if pattern_window.start < vac_end and pattern_window.end > vac_start:
                    overlaps = True
                    break
            
            # Only keep pattern windows that don't overlap with vacations
            if not overlaps:
                filtered.append(pattern_window)
        
        return filtered

    def _is_in_vacation_period(self, check_date: datetime, vacation_windows: list[CustodyWindow]) -> bool:
        """Check if a date falls within any vacation period.
        
        Args:
            check_date: Date to check
            vacation_windows: List of vacation windows (including filter windows)
        
        Returns:
            True if the date is within a vacation period, False otherwise
        """
        if not vacation_windows:
            return False
        
        for vac_window in vacation_windows:
            if vac_window.start <= check_date <= vac_window.end:
                return True
        return False

    def _generate_pattern_windows(self, now: datetime, vacation_windows: list[CustodyWindow] = None) -> list[CustodyWindow]:
        """Create repeating windows from the selected custody type.
        
        Args:
            now: Current datetime
            vacation_windows: List of vacation windows to check for overlaps (public holidays not applied during vacations)
        """
        if vacation_windows is None:
            vacation_windows = []
        
        custody_type = self._config.get("custody_type", "alternate_week")
        type_def = CUSTODY_TYPES.get(custody_type) or CUSTODY_TYPES["alternate_week"]
        horizon = now + timedelta(days=90)

        # Cas particulier : week-ends basés sur la parité ISO des semaines
        if custody_type == "alternate_weekend":
            windows: list[CustodyWindow] = []
            pointer = self._reference_start(now, custody_type)
            
            # Get French holidays for current and next year
            holidays = get_french_holidays(now.year) | get_french_holidays(now.year + 1)
            
            # Get reference_year to determine parity (even = even weeks, odd = odd weeks)
            reference_year = self._config.get(CONF_REFERENCE_YEAR, "even")
            target_parity = 0 if reference_year == "even" else 1  # 0 = even, 1 = odd
            
            while pointer < horizon:
                iso_week = pointer.isocalendar().week
                week_parity = iso_week % 2  # 0 = even, 1 = odd
                if week_parity == target_parity:
                    # Weekend: Friday 16:15 -> Sunday 19:00
                    # pointer is Monday of the week, so:
                    # Friday = pointer + 4, Saturday = pointer + 5, Sunday = pointer + 6
                    friday = pointer + timedelta(days=4)
                    sunday = pointer + timedelta(days=6)
                    monday = pointer + timedelta(days=7)
                    thursday = pointer + timedelta(days=3)
                    
                    # Default start/end
                    window_start = friday
                    window_end = sunday
                    label_suffix = ""
                    
                    # Check if weekend falls during vacation period
                    # If yes, don't apply public holiday extensions (vacations dominate)
                    weekend_in_vacation = (
                        self._is_in_vacation_period(friday, vacation_windows) or
                        self._is_in_vacation_period(sunday, vacation_windows) or
                        self._is_in_vacation_period(monday, vacation_windows)
                    )
                    
                    # Only apply public holidays if NOT during vacation period
                    if not weekend_in_vacation:
                        friday_is_holiday = friday.date() in holidays
                        monday_is_holiday = monday.date() in holidays
                        
                        if friday_is_holiday:
                            # Vendredi férié: start Thursday instead
                            window_start = thursday
                            label_suffix = " + Vendredi férié"
                        
                        if monday_is_holiday:
                            # Lundi férié: extend to Monday
                            window_end = monday
                            label_suffix = " + Lundi férié" if not label_suffix else " + Pont"
                    
                    # Get label from custody type definition
                    type_label = CUSTODY_TYPES.get(custody_type, {}).get("label", "Garde")
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(window_start, self._arrival_time),
                            end=self._apply_time(window_end, self._departure_time),
                            label=f"Garde - {type_label}{label_suffix}",
                            source="pattern",
                        )
                    )
                pointer += timedelta(days=7)
            return windows

        # Cas particulier : semaines alternées basées sur la parité ISO des semaines
        if custody_type == "alternate_week_parity":
            windows: list[CustodyWindow] = []
            pointer = self._reference_start(now, custody_type)
            
            # Get French holidays for current and next year
            holidays = get_french_holidays(now.year) | get_french_holidays(now.year + 1)
            
            # Get reference_year to determine parity (even = even weeks, odd = odd weeks)
            reference_year = self._config.get(CONF_REFERENCE_YEAR, "even")
            target_parity = 0 if reference_year == "even" else 1  # 0 = even, 1 = odd
            
            while pointer < horizon:
                iso_week = pointer.isocalendar().week
                week_parity = iso_week % 2  # 0 = even, 1 = odd
                if week_parity == target_parity:
                    # Week: Monday to Sunday (7 days)
                    monday = pointer
                    sunday = pointer + timedelta(days=6)
                    next_monday = pointer + timedelta(days=7)
                    previous_friday = pointer - timedelta(days=3)
                    
                    # Default start/end
                    window_start = monday
                    window_end = sunday
                    label_suffix = ""
                    
                    # Check if week falls during vacation period
                    # If yes, don't apply public holiday extensions (vacations dominate)
                    week_in_vacation = (
                        self._is_in_vacation_period(monday, vacation_windows) or
                        self._is_in_vacation_period(sunday, vacation_windows) or
                        self._is_in_vacation_period(next_monday, vacation_windows)
                    )
                    
                    # Only apply public holidays if NOT during vacation period
                    if not week_in_vacation:
                        # Check if Monday is a holiday (extend from previous Friday)
                        monday_is_holiday = monday.date() in holidays
                        # Check if Friday is a holiday (extend to next Monday)
                        friday = pointer + timedelta(days=4)
                        friday_is_holiday = friday.date() in holidays
                        
                        if monday_is_holiday:
                            # Lundi férié: start previous Friday instead
                            window_start = previous_friday
                            label_suffix = " + Lundi férié"
                        
                        if friday_is_holiday:
                            # Vendredi férié: extend to next Monday
                            window_end = next_monday
                            label_suffix = " + Vendredi férié" if not label_suffix else " + Pont"
                    
                    # Get label from custody type definition
                    type_label = CUSTODY_TYPES.get(custody_type, {}).get("label", "Garde")
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(window_start, self._arrival_time),
                            end=self._apply_time(window_end, self._departure_time),
                            label=f"Garde - {type_label}{label_suffix}",
                            source="pattern",
                        )
                    )
                pointer += timedelta(days=7)
            return windows

        cycle_days = type_def["cycle_days"]
        pattern = type_def["pattern"]
        windows: list[CustodyWindow] = []
        reference_start = self._reference_start(now, custody_type)
        pointer = reference_start

        while pointer < horizon:
            offset = timedelta()
            for segment in pattern:
                segment_start = pointer + offset
                # For other cases: if segment is N days, it spans from day 0 to day N-1
                segment_end = segment_start + timedelta(days=segment["days"] - 1)
                if segment["state"] == "on":
                    # Get label from custody type definition
                    type_label = CUSTODY_TYPES.get(custody_type, {}).get("label", "Garde")
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(segment_start, self._arrival_time),
                            end=self._apply_time(segment_end, self._departure_time),
                            label=f"Garde - {type_label}",
                            source="pattern",
                        )
                    )
                offset += timedelta(days=segment["days"])
            pointer += timedelta(days=cycle_days)

        return windows

    async def _generate_vacation_windows(self, now: datetime) -> list[CustodyWindow]:
        """Optional windows driven by vacation rules."""
        zone = self._config.get(CONF_ZONE)
        if not zone:
            return []

        holidays = await self._holidays.async_list(zone, now.year)
        windows: list[CustodyWindow] = []
        summer_rule = self._config.get(CONF_SUMMER_RULE)
        # vacation_rule is now automatic based on reference_year
        # For non-summer holidays, use automatic parity logic: odd year = first part, even year = second part
        rule = None  # Will be determined automatically based on reference_year and holiday type

        for holiday in holidays:
            start, end, midpoint = self._effective_holiday_bounds(holiday)
            if end < now:
                continue

            # Always add a filter window covering the full effective vacation period.
            # This enforces: vacances scolaires > garde normale (no weekend/week pattern windows inside holidays).
            windows.append(
                CustodyWindow(
                    start=start,
                    end=end,
                    label=f"{holiday.name} - Période complète (filtrage)",
                    source="vacation_filter",
                )
            )

            applied = False
            if summer_rule and summer_rule in SUMMER_RULES and self._is_summer_break(holiday):
                windows.extend(self._summer_windows(holiday, summer_rule))
                applied = True

            if applied:
                continue

            # Automatic vacation rule based on reference_year parity
            # Get reference_year to determine automatic rule
            reference_year = self._config.get(CONF_REFERENCE_YEAR, "even")
            is_even_year = start.year % 2 == 0
            
            # Determine automatic rule: if reference_year is "even", apply second part logic in even years
            # If reference_year is "odd", apply first part logic in odd years
            # Default: use first_half/second_half logic for automatic splitting
            if reference_year == "even":
                # Even reference: apply second part (second_half) in even years
                rule = "second_half" if is_even_year else None
            else:
                # Odd reference: apply first part (first_half) in odd years
                rule = "first_half" if not is_even_year else None

            if not rule:
                continue

            window_start = start
            window_end = end

            if rule == "first_week":
                # 1ère semaine : uniquement en années impaires
                if not is_even_year:
                    window_start = self._apply_time(start, self._arrival_time)
                    window_end = min(end, start + timedelta(days=7))
                    window_end = self._apply_time(window_end, self._departure_time)
                else:
                    # Année paire : pas de garde (car c'est la 2ème partie)
                    continue
            elif rule == "second_week":
                # 2ème semaine : uniquement en années paires
                if is_even_year:
                    window_start = start + timedelta(days=7)
                    window_start = self._apply_time(window_start, self._arrival_time)
                    window_end = min(end, window_start + timedelta(days=7))
                    window_end = self._apply_time(window_end, self._departure_time)
                else:
                    # Année impaire : pas de garde (car c'est la 1ère partie)
                    continue
            elif rule == "first_half":
                # 1ère moitié : uniquement en années impaires
                if not is_even_year:
                    window_start = start
                    window_end = midpoint
                else:
                    # Année paire : pas de garde (car c'est la 2ème partie)
                    continue
            elif rule == "second_half":
                # 2ème moitié : uniquement en années paires
                if is_even_year:
                    window_start = midpoint
                    window_end = end
                else:
                    # Année impaire : pas de garde (car c'est la 1ère partie)
                    continue
            elif rule == "even_weeks":
                window_start = start
                if int(start.strftime("%U")) % 2 != 0:
                    window_start = start + timedelta(days=7)
                window_start = self._apply_time(window_start, self._arrival_time)
                window_end = min(end, window_start + timedelta(days=7))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "odd_weeks":
                window_start = start
                if int(start.strftime("%U")) % 2 == 0:
                    window_start = start + timedelta(days=7)
                window_start = self._apply_time(window_start, self._arrival_time)
                window_end = min(end, window_start + timedelta(days=7))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "even_weekends":
                days_until_saturday = (5 - start.weekday()) % 7
                saturday = start + timedelta(days=days_until_saturday)
                _, iso_week, _ = saturday.isocalendar()
                if iso_week % 2 != 0:
                    saturday += timedelta(days=7)
                sunday = saturday + timedelta(days=1)
                window_start = self._apply_time(saturday, self._arrival_time)
                window_end = min(end, self._apply_time(sunday, self._departure_time))
            elif rule == "odd_weekends":
                days_until_saturday = (5 - start.weekday()) % 7
                saturday = start + timedelta(days=days_until_saturday)
                _, iso_week, _ = saturday.isocalendar()
                if iso_week % 2 == 0:
                    saturday += timedelta(days=7)
                sunday = saturday + timedelta(days=1)
                window_start = self._apply_time(saturday, self._arrival_time)
                window_end = min(end, self._apply_time(sunday, self._departure_time))
            elif rule == "july":
                # Juillet complet selon reference_year (pair/impair)
                if start.month != 7 and end.month != 7:
                    continue
                reference_year = self._config.get(CONF_REFERENCE_YEAR, "even")
                # reference_year "even" = années paires, "odd" = années impaires
                is_target_year = (start.year % 2 == 0) if reference_year == "even" else (start.year % 2 == 1)
                if not is_target_year:
                    continue
                window_start = self._apply_time(start, self._arrival_time)
                window_end = min(end, datetime(start.year, 7, 31, tzinfo=start.tzinfo))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "august":
                # Août complet selon reference_year (pair/impair)
                if start.month != 8 and end.month != 8:
                    continue
                reference_year = self._config.get(CONF_REFERENCE_YEAR, "even")
                # reference_year "even" = années paires, "odd" = années impaires
                is_target_year = (start.year % 2 == 0) if reference_year == "even" else (start.year % 2 == 1)
                if not is_target_year:
                    continue
                window_start = self._apply_time(start, self._arrival_time)
                window_end = min(end, datetime(start.year, 8, 31, tzinfo=start.tzinfo))
                window_end = self._apply_time(window_end, self._departure_time)
            else:
                window_start = self._apply_time(start, self._arrival_time)
                window_end = self._apply_time(end, self._departure_time)

            if window_end <= window_start:
                continue

            windows.append(
                CustodyWindow(
                    start=window_start,
                    end=window_end,
                    label=f"Vacances scolaires - {holiday.name} ({rule})",
                    source="vacation",
                )
            )
        return windows

    def _is_summer_break(self, holiday) -> bool:
        """Detect if the holiday relates to the summer break."""
        name = holiday.name.lower()
        return "été" in name or holiday.start.month in (7, 8) or holiday.end.month in (7, 8)

    def _summer_windows(self, holiday, rule: str) -> list[CustodyWindow]:
        """Return windows aligned with the summer rule."""
        # Use effective vacation bounds (Friday 16:15 -> Sunday 19:00) for consistent behavior
        start, end, midpoint = self._effective_holiday_bounds(holiday)
        windows: list[CustodyWindow] = []
        is_even_year = start.year % 2 == 0

        if rule == "summer_parity_auto":
            # Règle spéciale : Année paire = Août, Année impaire = Juillet
            # Cette règle est basée UNIQUEMENT sur la parité de l'année, pas sur reference_year
            # reference_year s'applique uniquement aux vacances non-été
            
            # Simple logic: even year = August (full month), odd year = July (full month)
            if is_even_year:
                # Année paire : Août complet
                august_start = datetime(start.year, 8, 1, tzinfo=start.tzinfo)
                august_end = datetime(start.year, 8, 31, 23, 59, 59, tzinfo=start.tzinfo)
                if august_end >= start and august_start <= end:
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(max(start, august_start), self._arrival_time),
                            end=self._force_vacation_end(min(end, august_end)),
                            label="Vacances scolaires - Août complet (année paire)",
                            source="summer",
                        )
                    )
            else:
                # Année impaire : Juillet complet
                july_start = datetime(start.year, 7, 1, tzinfo=start.tzinfo)
                july_end = datetime(start.year, 7, 31, 23, 59, 59, tzinfo=start.tzinfo)
                if july_end >= start and july_start <= end:
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(max(start, july_start), self._arrival_time),
                            end=self._apply_time(min(end, july_end), self._departure_time),
                            label="Vacances scolaires - Juillet complet (année impaire)",
                            source="summer",
                        )
                    )
        elif rule == "july_first_half":
            # 1ère moitié de juillet (1-15 juillet)
            window_start = datetime(start.year, 7, 1, tzinfo=start.tzinfo)
            window_end = datetime(start.year, 7, 15, 23, 59, 59, tzinfo=start.tzinfo)
            if window_end >= start and window_start <= end:
                windows.append(
                    CustodyWindow(
                        start=self._apply_time(max(start, window_start), self._arrival_time),
                        end=min(end, window_end),
                        label="Vacances scolaires - Juillet (1ère moitié)",
                        source="summer",
                    )
                )
        elif rule == "july_second_half":
            # 2ème moitié de juillet (16-31 juillet)
            window_start = datetime(start.year, 7, 16, tzinfo=start.tzinfo)
            window_end = datetime(start.year, 7, 31, 23, 59, 59, tzinfo=start.tzinfo)
            if window_end >= start and window_start <= end:
                windows.append(
                    CustodyWindow(
                        start=self._apply_time(max(start, window_start), self._arrival_time),
                        end=self._apply_time(min(end, window_end), self._departure_time),
                        label="Vacances scolaires - Juillet (2ème moitié)",
                        source="summer",
                    )
                )
        elif rule == "august_first_half":
            # 1ère moitié d'août (1-15 août)
            window_start = datetime(start.year, 8, 1, tzinfo=start.tzinfo)
            window_end = datetime(start.year, 8, 15, 23, 59, 59, tzinfo=start.tzinfo)
            if window_end >= start and window_start <= end:
                windows.append(
                    CustodyWindow(
                        start=self._apply_time(max(start, window_start), self._arrival_time),
                        end=min(end, window_end),
                        label="Vacances scolaires - Août (1ère moitié)",
                        source="summer",
                    )
                )
        elif rule == "august_second_half":
            # 2ème moitié d'août (16-31 août)
            window_start = datetime(start.year, 8, 16, tzinfo=start.tzinfo)
            window_end = datetime(start.year, 8, 31, 23, 59, 59, tzinfo=start.tzinfo)
            if window_end >= start and window_start <= end:
                windows.append(
                    CustodyWindow(
                        start=self._apply_time(max(start, window_start), self._arrival_time),
                        end=self._force_vacation_end(min(end, window_end)),
                        label="Vacances scolaires - Août (2ème moitié)",
                        source="summer",
                    )
                )

        valid_windows = [window for window in windows if window.end > window.start]
        return valid_windows

    def _load_custom_rules(self) -> list[CustodyWindow]:
        """Transform custom ISO ranges configured via options."""
        custom_rules = self._config.get(CONF_CUSTOM_RULES) or []
        windows: list[CustodyWindow] = []
        for rule in custom_rules:
            start = dt_util.parse_datetime(rule.get("start"))
            end = dt_util.parse_datetime(rule.get("end"))
            label = rule.get("label", "Custom rule")
            if not start or not end or end <= start:
                continue
            windows.append(
                CustodyWindow(
                    start=dt_util.as_local(start),
                    end=dt_util.as_local(end),
                    label=label,
                    source="custom",
                )
            )
        return windows

    def _reference_start(self, now: datetime, custody_type: str) -> datetime:
        """Return the datetime used as anchor for the cycle."""
        reference_year = now.year
        desired = self._config.get(CONF_REFERENCE_YEAR, "even")
        if desired == "even" and reference_year % 2 != 0:
            reference_year -= 1
        elif desired == "odd" and reference_year % 2 == 0:
            reference_year -= 1

        if custody_type in ("alternate_weekend", "alternate_week_parity"):
            # Use reference_year to determine parity (even = even weeks, odd = odd weeks)
            target_parity = 0 if desired == "even" else 1
            base = self._first_monday_with_week_parity(reference_year, target_parity)
        else:
            base = datetime(reference_year, 1, 1, tzinfo=self._tz)

        start_day = WEEKDAY_LOOKUP.get(self._config.get(CONF_START_DAY, "monday").lower(), 0)
        delta = (start_day - base.weekday()) % 7
        return base + timedelta(days=delta)

    def _first_monday_with_week_parity(self, year: int, parity: int) -> datetime:
        """Return the first Monday of the ISO week with the requested parity (0 even / 1 odd)."""
        candidate = datetime(year, 1, 1, tzinfo=self._tz)
        # Go to next Monday
        candidate += timedelta(days=(7 - candidate.weekday()) % 7)
        while candidate.isocalendar().week % 2 != parity:
            candidate += timedelta(days=7)
        return candidate

    def _summer_week_parity_windows(
        self, start: datetime, end: datetime, target_parity: int, month: int
    ) -> list[CustodyWindow]:
        """Slice summer into week chunks based on even/odd parity."""
        windows: list[CustodyWindow] = []
        cursor = start
        while cursor < end:
            if cursor.month != month:
                cursor += timedelta(days=1)
                continue
            week_start = cursor - timedelta(days=cursor.weekday())
            week_end = min(end, week_start + timedelta(days=7))
            if week_start.isocalendar().week % 2 == target_parity:
                windows.append(
                    CustodyWindow(
                        start=week_start,
                        end=week_end,
                        label=f"Vacances scolaires - Semaine {'paire' if target_parity == 0 else 'impaire'} {week_start.isocalendar().week}",
                        source="summer",
                    )
                )
            cursor = week_end
        return windows

    def _apply_time(self, dt_value: datetime, target: time) -> datetime:
        """Attach the configured time to a datetime."""
        return dt_value.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)

    def _effective_holiday_bounds(self, holiday) -> tuple[datetime, datetime, datetime]:
        """Return (effective_start, effective_end, midpoint) for a holiday.

        Custom vacation custody rules:
        - Effective start: previous Friday at arrival_time (e.g., school pickup Friday 16:15),
          even if the API indicates a Saturday start.
        - Effective end: previous Sunday at departure_time (e.g., Sunday 19:00),
          even if the API indicates a Monday reprise at 00:00.
        - Midpoint: exact half between effective start and effective end (midpoint time overrides standard times).
        """
        start_dt = dt_util.as_local(holiday.start)
        end_dt = dt_util.as_local(holiday.end)

        start_date = start_dt.date()
        end_date = end_dt.date()

        # If the API returns an end at 00:00, it's typically the "reprise" day (exclusive end)
        if end_dt.hour == 0 and end_dt.minute == 0 and end_dt.second == 0:
            end_date = end_date - timedelta(days=1)

        # Effective start is the previous Friday (school pickup)
        effective_start_date = start_date
        while effective_start_date.weekday() != 4:  # Friday
            effective_start_date -= timedelta(days=1)

        # Effective end is the previous Sunday (end of vacation before school resumes)
        effective_end_date = end_date
        while effective_end_date.weekday() != 6:  # Sunday
            effective_end_date -= timedelta(days=1)

        effective_start = datetime.combine(effective_start_date, self._arrival_time, start_dt.tzinfo)
        effective_end = datetime.combine(effective_end_date, self._departure_time, end_dt.tzinfo)

        # Safety fallback: avoid inverted windows on unexpected API shapes
        if effective_end <= effective_start:
            effective_start = self._apply_time(start_dt, self._arrival_time)
            effective_end = self._apply_time(end_dt, self._departure_time)

        midpoint = effective_start + (effective_end - effective_start) / 2
        return effective_start, effective_end, midpoint

    def _parse_time(self, value: str) -> time:
        """Parse HH:MM strings into a time object."""
        try:
            hour, minute = value.split(":")
            return time(int(hour), int(minute))
        except (ValueError, AttributeError):
            return time(8, 0)

    async def _determine_period(self, now: datetime) -> tuple[str, str | None]:
        """Return ('school'|'vacation', holiday_name)."""
        zone = self._config.get(CONF_ZONE)
        if not zone:
            return "school", None

        holidays = await self._holidays.async_list(zone, now.year)
        for holiday in holidays:
            effective_start, effective_end, _mid = self._effective_holiday_bounds(holiday)
            if effective_start <= now <= effective_end:
                return "vacation", holiday.name

        return "school", None

    async def _get_next_vacation(
        self, now: datetime
    ) -> tuple[str | None, datetime | None, datetime | None, int | None, list[dict[str, Any]]]:
        """Return information about the next upcoming vacation (custody-focused).

        Uses the *effective* vacation bounds (custom rules):
        - Start: previous Friday at arrival_time (pickup at school)
        - End: previous Sunday at departure_time (return Sunday evening)
        - Midpoint: exact half (time is preserved and overrides standard times)

        Returned start/end correspond to the next *custody segment* during that vacation
        (e.g., if rule is "second_half", start is the midpoint, not the vacation start).
        """
        from .const import LOGGER
        
        zone = self._config.get(CONF_ZONE)
        if not zone:
            LOGGER.warning("No zone configured, cannot fetch school holidays")
            return None, None, None, None, []

        LOGGER.debug("Fetching holidays for zone=%s, year=%s", zone, now.year)
        holidays = await self._holidays.async_list(zone, now.year)
        LOGGER.debug("Retrieved %d holidays from API", len(holidays))
        
        if not holidays:
            LOGGER.warning("No holidays found for zone %s, year %s", zone, now.year)
        
        # Sort holidays by effective start date (more relevant than raw API start)
        sorted_holidays = sorted(holidays, key=lambda h: self._effective_holiday_bounds(h)[0])
        
        # Build raw holidays list for debugging/display
        # Filter to only show holidays from current calendar year onwards
        # This includes holidays from current school year and previous school year if they're in current year
        school_holidays_raw = []
        
        weekday_fr = {
            "Monday": "Lundi",
            "Tuesday": "Mardi",
            "Wednesday": "Mercredi",
            "Thursday": "Jeudi",
            "Friday": "Vendredi",
            "Saturday": "Samedi",
            "Sunday": "Dimanche",
        }

        for holiday in sorted_holidays:
            effective_start, effective_end, _midpoint = self._effective_holiday_bounds(holiday)

            # Only show upcoming/current holidays (based on effective end)
            if effective_end < now:
                continue
            school_holidays_raw.append(
                {
                    "name": holiday.name,
                    "official_start": dt_util.as_local(holiday.start).strftime("%d %B %Y"),
                    "official_end": dt_util.as_local(holiday.end).strftime("%d %B %Y"),
                    "official_start_weekday": weekday_fr.get(
                        dt_util.as_local(holiday.start).strftime("%A"),
                        dt_util.as_local(holiday.start).strftime("%A"),
                    ),
                    "official_end_weekday": weekday_fr.get(
                        dt_util.as_local(holiday.end).strftime("%A"),
                        dt_util.as_local(holiday.end).strftime("%A"),
                    ),
                    "effective_start": effective_start.strftime("%d %B %Y %H:%M"),
                    "effective_end": effective_end.strftime("%d %B %Y %H:%M"),
                }
            )

        # vacation_rule is now automatic based on reference_year
        reference_year = self._config.get(CONF_REFERENCE_YEAR, "even")
        summer_rule = self._config.get(CONF_SUMMER_RULE) if self._config.get(CONF_SUMMER_RULE) in SUMMER_RULES else None

        def _custody_segment_for_holiday(holiday_obj) -> tuple[datetime, datetime]:
            eff_start, eff_end, mid = self._effective_holiday_bounds(holiday_obj)

            # Summer special-case
            if summer_rule and self._is_summer_break(holiday_obj):
                # All summer rules (summer_parity_auto, july_first_half, etc.) generate their own windows
                # via _summer_windows method; fall back to the full effective interval for segment calculation
                return eff_start, eff_end

            # Automatic vacation rule based on reference_year parity
            is_even_year = eff_start.year % 2 == 0
            if reference_year == "even":
                # Even reference: even years = second part (second_half)
                if is_even_year:
                    return mid, eff_end
                else:
                    # Odd years: no custody (first part goes to other parent)
                    return eff_start, eff_start  # No custody
            else:
                # Odd reference: odd years = first part (first_half)
                if not is_even_year:
                    return eff_start, mid
                else:
                    # Even years: no custody (second part goes to other parent)
                    return eff_start, eff_start  # No custody

            # For other rules (weekends parity, july/august slices, etc.), default to the full effective interval
            return eff_start, eff_end
        
        # First, check if we're currently in a vacation (effective bounds)
        for holiday in sorted_holidays:
            eff_start, eff_end, _mid = self._effective_holiday_bounds(holiday)
            if eff_start <= now <= eff_end:
                seg_start, seg_end = _custody_segment_for_holiday(holiday)
                return (
                    holiday.name,
                    seg_start,
                    seg_end,
                    0,
                    school_holidays_raw,
                )
        
        # Not in vacation, find the next custody segment start
        next_vacation = None
        next_seg_start: datetime | None = None
        next_seg_end: datetime | None = None
        for holiday in sorted_holidays:
            seg_start, seg_end = _custody_segment_for_holiday(holiday)
            LOGGER.debug(
                "Checking holiday (custody segment): %s, seg_start=%s, seg_end=%s, now=%s",
                holiday.name,
                seg_start,
                seg_end,
                now,
            )
            if seg_start > now:
                next_vacation = holiday
                next_seg_start = seg_start
                next_seg_end = seg_end
                LOGGER.debug("Found next vacation custody segment: %s, start=%s", holiday.name, next_seg_start)
                break
        
        if not next_vacation:
            LOGGER.warning("No next vacation found after %s. Total holidays: %d", now, len(sorted_holidays))
            if sorted_holidays:
                LOGGER.debug("Last holiday: %s (ends %s)", sorted_holidays[-1].name, sorted_holidays[-1].end)
            return None, None, None, None, school_holidays_raw
        
        if next_seg_start is None or next_seg_end is None:
            return None, None, None, None, school_holidays_raw

        delta = next_seg_start - now
        days_until = max(0, round(delta.total_seconds() / 86400, 2))
        
        return (
            next_vacation.name,
            next_seg_start,
            next_seg_end,
            days_until,
            school_holidays_raw,
        )
    
    def _adjust_vacation_start(self, official_start: datetime, school_level: str) -> datetime:
        """Adjust vacation start date based on school level.
        
        - Primary: Friday afternoon (departure time)
          - L'API retourne le vendredi à 23h UTC, qui devient samedi 00h en heure locale
          - On extrait la date et on s'assure que c'est un vendredi (si c'est samedi, on recule d'1 jour)
        - Middle/High: Saturday at arrival time
          - Si l'API retourne samedi, on l'utilise directement
          - Sinon, on trouve le samedi suivant
        
        Args:
            official_start: Official vacation start date from API (en heure locale après conversion)
            school_level: "primary", "middle", or "high"
        
        Returns:
            Adjusted start datetime
        """
        from .const import LOGGER
        
        if school_level == "primary":
            # Primary: Friday afternoon at departure time
            # L'API retourne le vendredi à 23h UTC, qui devient samedi 00h en heure locale
            # On extrait la date et on s'assure que c'est un vendredi
            date_only = official_start.date()
            weekday = date_only.weekday()  # 0=Monday, 4=Friday, 5=Saturday
            weekday_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            
            LOGGER.debug("Adjusting vacation start for primary: official_start=%s (%s), weekday=%d", 
                        official_start, weekday_names[weekday], weekday)
            
            # Si c'est samedi (5), c'est que l'API a retourné vendredi 23h UTC qui est devenu samedi 00h local
            # On recule d'1 jour pour avoir le vendredi
            if weekday == 5:  # Saturday
                date_only = date_only - timedelta(days=1)
                LOGGER.debug("Was Saturday, adjusted to Friday: %s", date_only)
            # Si c'est déjà vendredi (4), on l'utilise directement
            
            # Créer un nouveau datetime avec la date corrigée et l'heure d'arrivée (vendredi sortie d'école)
            # Pour les vacances, on utilise l'heure d'arrivée car c'est le moment où l'enfant arrive
            friday_datetime = datetime.combine(date_only, self._arrival_time, official_start.tzinfo)
            LOGGER.debug("Final adjusted datetime: %s", friday_datetime)
            return friday_datetime
        else:
            # Middle/High: Saturday at arrival time
            # If official_start is Saturday, use it; otherwise find the next Saturday
            if official_start.weekday() == 5:  # Saturday
                saturday = official_start
            else:
                # Find the next Saturday
                days_to_saturday = (5 - official_start.weekday()) % 7
                if days_to_saturday == 0:
                    days_to_saturday = 7
                saturday = official_start + timedelta(days=days_to_saturday)
            return self._apply_time(saturday, self._arrival_time)

    def _force_vacation_end(self, official_end: datetime) -> datetime:
        """Force the vacation end to Sunday 19:00 if it falls on a Monday (school resume)."""
        # API end is usually Monday 00:00 (which is Sunday night)
        # If it's Monday 00:00, move to Sunday departure_time
        if official_end.weekday() == 0 and official_end.hour == 0 and official_end.minute == 0:
            sunday = official_end - timedelta(days=1)
            return self._apply_time(sunday, self._departure_time)
        
        # Also handle cases where it might be Monday at some other time or Sunday at 00:00
        # The key is: if the vacation ends at the start of a Monday, custody ends Sunday evening
        if official_end.weekday() == 0: # Monday
            sunday = official_end - timedelta(days=official_end.weekday() + 1 if official_end.weekday() < 6 else 0)
            # Actually, just get the Sunday before this Monday
            sunday = official_end - timedelta(days=1)
            return self._apply_time(sunday, self._departure_time)
            
        return self._apply_time(official_end, self._departure_time)

    def _evaluate_override(self, now: datetime) -> bool | None:
        """Return override state if active."""
        if not self._presence_override:
            return None
        until: datetime | None = self._presence_override["until"]
        if until and now > dt_util.as_local(until):
            self._presence_override = None
            return None
        return self._presence_override["state"] == "on"

    def _build_virtual_window(self, now: datetime) -> CustodyWindow:
        """Fallback window when override requests presence without schedule."""
        return CustodyWindow(start=now, end=now + timedelta(hours=1), label="Override", source="override")