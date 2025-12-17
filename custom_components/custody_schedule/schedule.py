"""Schedule helpers for the Custody Schedule integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

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
    CONF_VACATION_RULE,
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
        now = dt_util.utcnow()
        until = now + duration if duration else None
        self._presence_override = {"state": state, "until": until}

    def clear_override(self) -> None:
        """Remove manual override."""
        self._presence_override = None

    async def async_calculate(self, now: datetime) -> CustodyComputation:
        """Build the schedule state used by entities."""
        now_local = dt_util.as_local(now)
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
        
        Priority: Vacation rules > Custom rules > Normal pattern rules
        If a vacation period overlaps with a normal pattern window, the normal window
        is completely replaced by the vacation window for the entire vacation period.
        """
        pattern_windows = self._generate_pattern_windows(now)
        vacation_windows = await self._generate_vacation_windows(now)
        custom_windows = self._load_custom_rules()

        # Filter out pattern windows that overlap with vacation periods
        # Vacation rules have priority and completely replace normal rules during vacations
        # We need to create filter windows that cover entire vacation periods
        filtered_pattern_windows = self._filter_windows_by_vacations(pattern_windows, vacation_windows)
        
        # Separate display windows from filter windows
        vacation_display_windows = [w for w in vacation_windows if w.source != "vacation_filter"]
        
        # Merge: vacation windows (highest priority), then custom, then filtered pattern
        merged = vacation_display_windows + custom_windows + filtered_pattern_windows
        return [window for window in merged if window.end > now - timedelta(days=1)]
    
    def _filter_windows_by_vacations(
        self, pattern_windows: list[CustodyWindow], vacation_windows: list[CustodyWindow]
    ) -> list[CustodyWindow]:
        """Remove pattern windows that overlap with vacation periods.
        
        Vacation periods completely replace normal custody rules.
        If a pattern window overlaps (even partially) with any vacation window,
        it is removed entirely.
        """
        if not vacation_windows:
            return pattern_windows
        
        # Build a list of vacation periods (start, end) for quick overlap checking
        vacation_periods = [(vw.start, vw.end) for vw in vacation_windows]
        
        filtered = []
        for pattern_window in pattern_windows:
            # Check if this pattern window overlaps with any vacation period
            overlaps = False
            for vac_start, vac_end in vacation_periods:
                # Check for overlap: windows overlap if one starts before the other ends
                if pattern_window.start < vac_end and pattern_window.end > vac_start:
                    overlaps = True
                    break
            
            if not overlaps:
                filtered.append(pattern_window)
        
        return filtered

    def _generate_pattern_windows(self, now: datetime) -> list[CustodyWindow]:
        """Create repeating windows from the selected custody type."""
        custody_type = self._config.get("custody_type", "alternate_week")
        type_def = CUSTODY_TYPES.get(custody_type) or CUSTODY_TYPES["alternate_week"]
        horizon = now + timedelta(days=90)

        # Cas particulier : week-ends basés sur la parité ISO des semaines
        if custody_type in ("even_weekends", "odd_weekends"):
            windows: list[CustodyWindow] = []
            pointer = self._reference_start(now, custody_type)
            while pointer < horizon:
                iso_week = pointer.isocalendar().week
                is_even = iso_week % 2 == 0
                if (custody_type == "even_weekends" and is_even) or (
                    custody_type == "odd_weekends" and not is_even
                ):
                    saturday = pointer + timedelta(days=5)
                    sunday = pointer + timedelta(days=7)
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(saturday, self._arrival_time),
                            end=self._apply_time(sunday, self._departure_time),
                            label="Custody period",
                        )
                    )
                pointer += timedelta(days=7)
            return windows

        cycle_days = type_def["cycle_days"]
        pattern = type_def["pattern"]
        windows: list[CustodyWindow] = []
        reference_start = self._reference_start(now, custody_type)
        
        # For alternate_weekend, _reference_start returns the Friday that starts the "on" period
        # But the pattern starts with "off" period, so we need to go back 12 days
        if custody_type == "alternate_weekend":
            # Go back to the start of the cycle (12 days before the "on" period)
            pointer = reference_start - timedelta(days=12)
        else:
            pointer = reference_start

        while pointer < horizon:
            offset = timedelta()
            for segment in pattern:
                segment_start = pointer + offset
                # For alternate_weekend with 2 days "on", it means Friday to Sunday
                # So we need segment_start + 2 days to get to Sunday (Fri=0, Sat=1, Sun=2)
                if custody_type == "alternate_weekend" and segment["state"] == "on":
                    segment_end = segment_start + timedelta(days=2)  # Friday -> Sunday
                else:
                    # For other cases: if segment is N days, it spans from day 0 to day N-1
                    segment_end = segment_start + timedelta(days=segment["days"] - 1)
                if segment["state"] == "on":
                    windows.append(
                        CustodyWindow(
                            start=self._apply_time(segment_start, self._arrival_time),
                            end=self._apply_time(segment_end, self._departure_time),
                            label="Custody period",
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
        rule = (
            self._config.get(CONF_VACATION_RULE)
            if self._config.get(CONF_VACATION_RULE) in VACATION_RULES
            else None
        )
        # Get school level for adjusting vacation start dates
        school_level = self._config.get(CONF_SCHOOL_LEVEL, "primary")
        
        for holiday in holidays:
            # Adjust start date based on school level (Friday for primary, Saturday for middle/high)
            start = self._adjust_vacation_start(holiday.start, school_level)
            end = holiday.end
            if end < now:
                continue
            applied = False
            if summer_rule and summer_rule in SUMMER_RULES and self._is_summer_break(holiday):
                windows.extend(self._summer_windows(holiday, summer_rule))
                applied = True
            if not rule or applied:
                continue

            # Apply arrival/departure times to vacation windows
            # For most rules, we use the configured arrival/departure times
            window_start = start
            if rule == "first_week":
                window_start = self._apply_time(start, self._arrival_time)
                window_end = min(end, start + timedelta(days=7))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "second_week":
                window_start = start + timedelta(days=7)
                window_start = self._apply_time(window_start, self._arrival_time)
                window_end = min(end, window_start + timedelta(days=7))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "first_half":
                window_start = self._apply_time(start, self._arrival_time)
                window_end = start + (end - start) / 2
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "second_half":
                window_start = start + (end - start) / 2
                window_start = self._apply_time(window_start, self._arrival_time)
                window_end = self._apply_time(end, self._departure_time)
            elif rule == "even_weeks":
                if int(start.strftime("%U")) % 2 != 0:
                    window_start = start + timedelta(days=7)
                window_start = self._apply_time(window_start, self._arrival_time)
                window_end = min(end, window_start + timedelta(days=7))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "odd_weeks":
                if int(start.strftime("%U")) % 2 == 0:
                    window_start = start + timedelta(days=7)
                window_start = self._apply_time(window_start, self._arrival_time)
                window_end = min(end, window_start + timedelta(days=7))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "even_weekends":
                # Week-ends des semaines paires (samedi-dimanche)
                # Trouver le samedi de la semaine de début
                # (5 - start.weekday()) % 7 calcule correctement :
                # - 0 si samedi (ce samedi)
                # - 1-5 si lundi-vendredi (samedi de cette semaine)
                # - 6 si dimanche (samedi de la semaine suivante)
                days_until_saturday = (5 - start.weekday()) % 7
                saturday = start + timedelta(days=days_until_saturday)
                # Use isocalendar() for reliable week number (ISO week: Monday=1, Sunday=7)
                # Get the ISO week number and check parity
                _, iso_week, _ = saturday.isocalendar()
                # Si la semaine ISO du samedi est impaire, passer à la semaine suivante
                if iso_week % 2 != 0:
                    saturday += timedelta(days=7)
                sunday = saturday + timedelta(days=1)
                window_start = self._apply_time(saturday, self._arrival_time)
                window_end = min(end, self._apply_time(sunday, self._departure_time))
            elif rule == "odd_weekends":
                # Week-ends des semaines impaires (samedi-dimanche)
                # Trouver le samedi de la semaine de début
                # (5 - start.weekday()) % 7 calcule correctement :
                # - 0 si samedi (ce samedi)
                # - 1-5 si lundi-vendredi (samedi de cette semaine)
                # - 6 si dimanche (samedi de la semaine suivante)
                days_until_saturday = (5 - start.weekday()) % 7
                saturday = start + timedelta(days=days_until_saturday)
                # Use isocalendar() for reliable week number (ISO week: Monday=1, Sunday=7)
                # Get the ISO week number and check parity
                _, iso_week, _ = saturday.isocalendar()
                # Si la semaine ISO du samedi est paire, passer à la semaine suivante
                if iso_week % 2 == 0:
                    saturday += timedelta(days=7)
                sunday = saturday + timedelta(days=1)
                window_start = self._apply_time(saturday, self._arrival_time)
                window_end = min(end, self._apply_time(sunday, self._departure_time))
            elif rule == "july":
                if start.month != 7 and end.month != 7:
                    continue
                window_start = self._apply_time(start, self._arrival_time)
                window_end = min(end, datetime(start.year, 7, 31, tzinfo=start.tzinfo))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "august":
                if start.month != 8 and end.month != 8:
                    continue
                window_start = self._apply_time(start, self._arrival_time)
                window_end = min(end, datetime(start.year, 8, 31, tzinfo=start.tzinfo))
                window_end = self._apply_time(window_end, self._departure_time)
            elif rule == "first_week_even_year":
                if start.year % 2 == 0:
                    # Use first half with exact midpoint time (not departure time)
                    window_start = self._apply_time(start, self._arrival_time)
                    window_end = start + (end - start) / 2
                    # Keep exact midpoint time, don't apply departure_time
                else:
                    continue
            elif rule == "first_week_odd_year":
                if start.year % 2 == 1:
                    # Use first half with exact midpoint time (not departure time)
                    window_start = self._apply_time(start, self._arrival_time)
                    window_end = start + (end - start) / 2
                    # Keep exact midpoint time, don't apply departure_time
                else:
                    continue
            elif rule == "second_week_even_year":
                if start.year % 2 == 0:
                    # Use second half: starts at exact midpoint, ends at Sunday 19:00
                    window_start = start + (end - start) / 2
                    window_start = self._apply_time(window_start, self._arrival_time)
                    # End is always Sunday at departure_time (19:00) for vacation sharing
                    window_end = self._apply_time(end, self._departure_time)
                    if window_end <= window_start:
                        continue
                else:
                    continue
            elif rule == "second_week_odd_year":
                if start.year % 2 == 1:
                    # Use second half: starts at exact midpoint, ends at Sunday 19:00
                    window_start = start + (end - start) / 2
                    window_start = self._apply_time(window_start, self._arrival_time)
                    # End is always Sunday at departure_time (19:00) for vacation sharing
                    window_end = self._apply_time(end, self._departure_time)
                    if window_end <= window_start:
                        continue
                else:
                    continue
            else:
                window_start = self._apply_time(start, self._arrival_time)
                window_end = self._apply_time(end, self._departure_time)

            if window_end <= window_start:
                continue

            windows.append(
                CustodyWindow(
                    start=window_start,
                    end=window_end,
                    label=f"{holiday.name} ({rule})",
                    source="vacation",
                )
            )
            
            # Add a filter window covering the entire vacation period
            # This ensures normal pattern windows are removed during the entire vacation
            # Find Monday of the week containing the vacation start
            monday_start_week = start - timedelta(days=start.weekday())
            # Find Sunday of the week containing the vacation end
            sunday_end_week = end - timedelta(days=end.weekday()) + timedelta(days=6)
            windows.append(
                CustodyWindow(
                    start=monday_start_week,
                    end=sunday_end_week + timedelta(days=1),
                    label=f"{holiday.name} - Période complète (filtrage)",
                    source="vacation_filter",
                )
            )
        return windows

    def _is_summer_break(self, holiday) -> bool:
        """Detect if the holiday relates to the summer break."""
        name = holiday.name.lower()
        return "été" in name or holiday.start.month in (7, 8) or holiday.end.month in (7, 8)

    def _summer_windows(self, holiday, rule: str) -> list[CustodyWindow]:
        """Return windows aligned with the summer rule."""
        start = holiday.start
        end = holiday.end
        windows: list[CustodyWindow] = []

        if rule == "july_first_half":
            window_end = min(end, datetime(start.year, 7, 31, tzinfo=start.tzinfo))
            windows.append(
                CustodyWindow(
                    start=start,
                    end=window_end,
                    label="Vacances juillet - 1ère moitié",
                    source="summer",
                )
            )
        elif rule == "july_second_half":
            window_start = datetime(start.year, 7, 16, tzinfo=start.tzinfo)
            windows.append(
                CustodyWindow(
                    start=window_start,
                    end=datetime(start.year, 7, 31, tzinfo=start.tzinfo),
                    label="Vacances juillet - 2ème moitié",
                    source="summer",
                )
            )
        elif rule in ("july_even_weeks", "july_odd_weeks"):
            windows.extend(
                self._summer_week_parity_windows(
                    start=start, end=end, target_parity=0 if rule == "july_even_weeks" else 1, month=7
                )
            )
        elif rule == "august_first_half":
            window_end = datetime(start.year, 8, 15, tzinfo=start.tzinfo)
            windows.append(
                CustodyWindow(
                    start=datetime(start.year, 8, 1, tzinfo=start.tzinfo),
                    end=window_end,
                    label="Vacances août - 1ère moitié",
                    source="summer",
                )
            )
        elif rule == "august_second_half":
            window_start = datetime(start.year, 8, 16, tzinfo=start.tzinfo)
            windows.append(
                CustodyWindow(
                    start=window_start,
                    end=min(end, datetime(start.year, 8, 31, tzinfo=start.tzinfo)),
                    label="Vacances août - 2ème moitié",
                    source="summer",
                )
            )
        elif rule in ("august_even_weeks", "august_odd_weeks"):
            windows.extend(
                self._summer_week_parity_windows(
                    start=start, end=end, target_parity=0 if rule == "august_even_weeks" else 1, month=8
                )
            )
        elif rule == "july_even_year":
            # Juillet entier pour les années paires
            if start.year % 2 == 0:
                july_start = datetime(start.year, 7, 1, tzinfo=start.tzinfo)
                july_end = datetime(start.year, 7, 31, 23, 59, 59, tzinfo=start.tzinfo)
                if july_end >= start and july_start <= end:
                    windows.append(
                        CustodyWindow(
                            start=max(start, july_start),
                            end=min(end, july_end),
                            label="Vacances juillet - années paires",
                            source="summer",
                        )
                    )
        elif rule == "july_odd_year":
            # Juillet entier pour les années impaires
            if start.year % 2 == 1:
                july_start = datetime(start.year, 7, 1, tzinfo=start.tzinfo)
                july_end = datetime(start.year, 7, 31, 23, 59, 59, tzinfo=start.tzinfo)
                if july_end >= start and july_start <= end:
                    windows.append(
                        CustodyWindow(
                            start=max(start, july_start),
                            end=min(end, july_end),
                            label="Vacances juillet - années impaires",
                            source="summer",
                        )
                    )
        elif rule == "august_even_year":
            # Août entier pour les années paires
            if start.year % 2 == 0:
                august_start = datetime(start.year, 8, 1, tzinfo=start.tzinfo)
                august_end = datetime(start.year, 8, 31, 23, 59, 59, tzinfo=start.tzinfo)
                if august_end >= start and august_start <= end:
                    windows.append(
                        CustodyWindow(
                            start=max(start, august_start),
                            end=min(end, august_end),
                            label="Vacances août - années paires",
                            source="summer",
                        )
                    )
        elif rule == "august_odd_year":
            # Août entier pour les années impaires
            if start.year % 2 == 1:
                august_start = datetime(start.year, 8, 1, tzinfo=start.tzinfo)
                august_end = datetime(start.year, 8, 31, 23, 59, 59, tzinfo=start.tzinfo)
                if august_end >= start and august_start <= end:
                    windows.append(
                        CustodyWindow(
                            start=max(start, august_start),
                            end=min(end, august_end),
                            label="Vacances août - années impaires",
                            source="summer",
                        )
                    )
        else:
            windows.append(CustodyWindow(start=start, end=end, label=holiday.name, source="summer"))

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

        if custody_type in ("even_weekends", "odd_weekends"):
            target_parity = 0 if custody_type == "even_weekends" else 1
            base = self._first_monday_with_week_parity(reference_year, target_parity)
        elif custody_type == "alternate_weekend":
            # For alternate_weekend, the pattern is: 12 days off, 2 days on
            # The "on" period is the weekend (Friday-Sunday)
            # We need to find the Friday that starts the next "on" period
            from .const import LOGGER
            start_day = WEEKDAY_LOOKUP.get(self._config.get(CONF_START_DAY, "friday").lower(), 4)
            
            # Find the next Friday from now
            days_to_friday = (start_day - now.weekday()) % 7
            if days_to_friday == 0:
                # Today is Friday
                if now.time() < self._arrival_time:
                    days_to_friday = 0  # Use today
                else:
                    days_to_friday = 7  # Use next Friday
            
            next_friday = now + timedelta(days=days_to_friday)
            next_friday = next_friday.replace(hour=0, minute=0, second=0, microsecond=0)
            
            LOGGER.debug("alternate_weekend: now=%s, days_to_friday=%d, next_friday=%s", 
                        now, days_to_friday, next_friday)
            
            # For alternate_weekend, we need to determine which Friday in the 2-week cycle
            # The cycle alternates every 2 weeks: week 1 (off), week 2 (on)
            # We use the reference year to determine the cycle phase
            # Find the first Friday of the reference year
            anchor = datetime(reference_year, 1, 1, tzinfo=self._tz)
            days_to_first_friday = (start_day - anchor.weekday()) % 7
            if days_to_first_friday == 0:
                days_to_first_friday = 7
            first_friday_ref = anchor + timedelta(days=days_to_first_friday)
            
            # Calculate how many weeks since the first Friday of reference year
            weeks_since_ref = (next_friday - first_friday_ref).days // 7
            # Determine which week in the 2-week cycle (0 or 1)
            cycle_week = weeks_since_ref % 2
            
            LOGGER.debug("alternate_weekend: first_friday_ref=%s, weeks_since_ref=%d, cycle_week=%d, reference_year=%d", 
                        first_friday_ref, weeks_since_ref, cycle_week, reference_year)
            
            # The "on" period depends on the reference year parity:
            # - If reference year is even: cycle_week == 0 means "on"
            # - If reference year is odd: cycle_week == 1 means "on"
            is_even_year = reference_year % 2 == 0
            is_on_period = (cycle_week == 0) if is_even_year else (cycle_week == 1)
            
            if not is_on_period:
                # We're in the "off" period, go to next Friday (which will be "on")
                LOGGER.debug("alternate_weekend: in 'off' period, moving to next Friday (on)")
                next_friday += timedelta(days=7)  # Next Friday
            else:
                LOGGER.debug("alternate_weekend: already at 'on' period")
            
            LOGGER.debug("alternate_weekend: final reference_start=%s", next_friday)
            return next_friday
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
                        label=f"Semaine {'paire' if target_parity == 0 else 'impaire'} {week_start.isocalendar().week}",
                        source="summer",
                    )
                )
            cursor = week_end
        return windows

    def _apply_time(self, dt_value: datetime, target: time) -> datetime:
        """Attach the configured time to a datetime."""
        return dt_value.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)

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
            if holiday.start <= now <= holiday.end:
                return "vacation", holiday.name

        return "school", None

    async def _get_next_vacation(self, now: datetime) -> tuple[str | None, datetime | None, datetime | None, int | None, list[dict[str, Any]]]:
        """Return information about the next upcoming vacation.
        
        If currently in vacation, returns the current vacation.
        Otherwise, returns the next vacation that hasn't started yet.
        
        Adjusts the start date based on school level:
        - Primary: Friday afternoon (departure time) - API already returns Friday
        - Middle/High: Saturday at arrival time
        
        Returns:
            (name, start_date, end_date, days_until, raw_holidays_list)
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
        
        # Sort holidays by start date
        sorted_holidays = sorted(holidays, key=lambda h: h.start)
        
        # Build raw holidays list for debugging/display
        # Filter to only show holidays that haven't ended yet
        school_holidays_raw = []
        for holiday in sorted_holidays:
            # Only include holidays that haven't ended yet (end date is in the future)
            if holiday.end < now:
                continue
            
            # Format dates in French format without time
            start_date_fr = holiday.start.strftime("%d %B %Y")
            end_date_fr = holiday.end.strftime("%d %B %Y")
            
            # French weekday names
            weekday_fr = {
                "Monday": "Lundi",
                "Tuesday": "Mardi", 
                "Wednesday": "Mercredi",
                "Thursday": "Jeudi",
                "Friday": "Vendredi",
                "Saturday": "Samedi",
                "Sunday": "Dimanche"
            }
            
            school_holidays_raw.append({
                "name": holiday.name,
                "start": start_date_fr,
                "end": end_date_fr,
                "start_weekday": weekday_fr.get(holiday.start.strftime("%A"), holiday.start.strftime("%A")),
                "end_weekday": weekday_fr.get(holiday.end.strftime("%A"), holiday.end.strftime("%A")),
            })
        
        # Get school level (default to primary)
        school_level = self._config.get(CONF_SCHOOL_LEVEL, "primary")
        
        # First, check if we're currently in a vacation
        current_vacation = None
        adjusted_start = None
        for holiday in sorted_holidays:
            # Adjust start date based on school level
            adjusted_start = self._adjust_vacation_start(holiday.start, school_level)
            if adjusted_start <= now <= holiday.end:
                current_vacation = holiday
                break
        
        if current_vacation:
            # We're in vacation, return current vacation info with adjusted start
            return (
                current_vacation.name,
                adjusted_start,
                current_vacation.end,
                0,  # Already in vacation
                school_holidays_raw,
            )
        
        # Not in vacation, find the next one
        next_vacation = None
        for holiday in sorted_holidays:
            adjusted_start = self._adjust_vacation_start(holiday.start, school_level)
            LOGGER.debug("Checking holiday: %s, official_start=%s, adjusted_start=%s, now=%s", 
                        holiday.name, holiday.start, adjusted_start, now)
            if adjusted_start > now:
                next_vacation = holiday
                LOGGER.debug("Found next vacation: %s, adjusted_start=%s", holiday.name, adjusted_start)
                break
        
        if not next_vacation:
            LOGGER.warning("No next vacation found after %s. Total holidays: %d", now, len(sorted_holidays))
            if sorted_holidays:
                LOGGER.debug("Last holiday: %s (ends %s)", sorted_holidays[-1].name, sorted_holidays[-1].end)
            return None, None, None, None, school_holidays_raw
        
        # Calculate days until vacation using adjusted start
        delta = adjusted_start - now
        days_until = max(0, round(delta.total_seconds() / 86400, 2))
        
        return (
            next_vacation.name,
            adjusted_start,
            next_vacation.end,
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