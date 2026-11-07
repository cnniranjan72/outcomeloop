"""Sim time helpers. Sim minute 0 == D0 00:00 == 2027-01-04T00:00+05:30 (IST)."""
from __future__ import annotations

import datetime as dt

D0 = dt.date(2027, 1, 4)
_day_cache: dict[str, int] = {}


def ts_to_minute(ts: str) -> int:
    """'2027-01-05T09:07:00+05:30' -> sim minute (fast path: slices, cached date)."""
    d = ts[:10]
    day = _day_cache.get(d)
    if day is None:
        day = (dt.date.fromisoformat(d) - D0).days
        _day_cache[d] = day
    return day * 1440 + int(ts[11:13]) * 60 + int(ts[14:16])


def minute_to_label(m: int) -> str:
    day, mod = divmod(m, 1440)
    return f"D{day} {mod // 60:02d}:{mod % 60:02d}"


def label_to_minute(s: str) -> int:
    """'D3 14:00' or ISO ts or int string -> sim minute."""
    s = s.strip()
    if s.lstrip("-").isdigit():
        return int(s)
    if s[0] in "dD":
        day, hm = s.split()
        h, mi = hm.split(":")
        return int(day[1:]) * 1440 + int(h) * 60 + int(mi)
    return ts_to_minute(s)


def hour_of(m: int) -> int:
    return (m % 1440) // 60


def next_working(t: int, hours: list[int]) -> int:
    lo, hi = hours
    day, mod = divmod(t, 1440)
    if mod < lo * 60:
        return day * 1440 + lo * 60
    if mod >= hi * 60:
        return (day + 1) * 1440 + lo * 60
    return t
