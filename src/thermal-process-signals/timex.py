"""工厂本地时间工具。

所有记录使用同一时区的朴素 ``YYYY-MM-DDTHH:MM`` 字符串，停留区间一律
左闭右开。本模块只做分钟粒度的解析、比较和区间运算。
"""
from __future__ import annotations

from datetime import datetime, timedelta

FMT = "%Y-%m-%dT%H:%M"


def parse(value: str) -> datetime:
    return datetime.strptime(value, FMT)


def fmt(value: datetime) -> str:
    return value.strftime(FMT)


def add_minutes(value: str, minutes: int) -> str:
    return fmt(parse(value) + timedelta(minutes=minutes))


def minute_diff(later: str, earlier: str) -> int:
    return int((parse(later) - parse(earlier)).total_seconds() // 60)


def overlaps(begin_a: str, end_a: str, begin_b: str, end_b: str) -> bool:
    """左闭右开区间是否相交。"""
    return parse(begin_a) < parse(end_b) and parse(begin_b) < parse(end_a)


def intersection(begin_a: str, end_a: str, begin_b: str, end_b: str) -> tuple[str, str] | None:
    begin = max(parse(begin_a), parse(begin_b))
    end = min(parse(end_a), parse(end_b))
    if begin < end:
        return fmt(begin), fmt(end)
    return None


def dominant_step_minutes(times: list[str]) -> int:
    """取相邻采样间隔的中位数，作为该线的正常采样节奏。"""
    stamps = sorted(parse(t) for t in times)
    gaps = [int((b - a).total_seconds() // 60) for a, b in zip(stamps, stamps[1:])]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return 1
    gaps.sort()
    return gaps[len(gaps) // 2]
