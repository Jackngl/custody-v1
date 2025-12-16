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
            windows=windows,
            attributes=attributes,
        )

    async def _build_windows(self, now: datetime) -> list[CustodyWindow]:
        """Generate presence windows from base pattern and vacation/custom rules."""
        pattern_windows = self._generate_pattern_windows(now)
        vacation_windows = await self._generate_vacation_windows(now)
        custom_windows = self._load_custom_rules()

        merged = pattern_windows + vacation_windows + custom_windows
        return [window for window in merged if window.end > now - timedelta(days=1)]

    def _generate_pattern_windows(self, now: datetime) -> list[CustodyWindow]:
        """Create repeating windows from the selected custody type."""
        custody_type = self._config.get("custody_type", "alternate_week")
        from .const import LOGGER
        LOGGER.debug("Generating pattern windows with custody_type: %s", custody_type)
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
        pointer = reference_start

        while pointer < horizon:
            offset = timedelta()
            for segment in pattern:
                segment_start = pointer + offset
                segment_end = segment_start + timedelta(days=segment["days"])
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
        for holiday in holidays:
            start = holiday.start
            end = holiday.end
            if end < now:
                continue
            applied = False
            if summer_rule and summer_rule in SUMMER_RULES and self._is_summer_break(holiday):
                windows.extend(self._summer_windows(holiday, summer_rule))
                applied = True
            if not rule or applied:
                continue

            window_start = start
            if rule == "first_week":
                window_end = min(end, start + timedelta(days=7))
            elif rule == "second_week":
                window_start = start + timedelta(days=7)
                window_end = min(end, window_start + timedelta(days=7))
            elif rule == "first_half":
                window_end = start + (end - start) / 2
            elif rule == "second_half":
                window_start = start + (end - start) / 2
                window_end = end
            elif rule == "even_weeks":
                if int(start.strftime("%U")) % 2 != 0:
                    window_start = start + timedelta(days=7)
                window_end = min(end, window_start + timedelta(days=7))
            elif rule == "odd_weeks":
                if int(start.strftime("%U")) % 2 == 0:
                    window_start = start + timedelta(days=7)
                window_end = min(end, window_start + timedelta(days=7))
            elif rule == "july":
                if start.month != 7 and end.month != 7:
                    continue
                window_end = min(end, datetime(start.year, 7, 31, tzinfo=start.tzinfo))
            elif rule == "august":
                if start.month != 8 and end.month != 8:
                    continue
                window_end = min(end, datetime(start.year, 8, 31, tzinfo=start.tzinfo))
            elif rule == "first_week_even_year":
                if start.year % 2 == 0:
                    window_end = min(end, start + timedelta(days=7))
                else:
                    continue
            elif rule == "first_week_odd_year":
                if start.year % 2 == 1:
                    window_end = min(end, start + timedelta(days=7))
                else:
                    continue
            elif rule == "second_week_even_year":
                if start.year % 2 == 0:
                    window_start = start + timedelta(days=7)
                    window_end = min(end, window_start + timedelta(days=7))
                    if window_end <= window_start:
                        continue
                else:
                    continue
            elif rule == "second_week_odd_year":
                if start.year % 2 == 1:
                    window_start = start + timedelta(days=7)
                    window_end = min(end, window_start + timedelta(days=7))
                    if window_end <= window_start:
                        continue
                else:
                    continue
            else:
                window_end = end

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