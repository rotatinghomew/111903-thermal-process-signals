"""当班传感器时序的异常检测。

设计约束：

* 只评估稳定阶段；换配方、预热是已知预期工况，单独列示而不报警；
* 每条线、每个配方用各自基线，不做跨线总体均值；
* 基线不可用时输出 ``inconclusive``（不可判断）而不是确认漂移；
* 缺测(``no-signal``)是设备测不出来，归为无读数区段，不计质量风险，
  也不用“每秒缺多少点”替代风险判断；
* 单点越界为孤立尖峰，相邻窗口持续越界为持续偏移，两类分别处置。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import timex
from .baseline import Baseline

CONFIRMED = "confirmed-shift"
SPIKE = "isolated-spike"
INCONCLUSIVE = "inconclusive"
NO_SIGNAL = "no-signal"
EXPECTED = "expected-phase"


@dataclass
class Event:
    event_id: str
    line: str
    kind: str
    recipe: str
    begin: str
    end: str
    points: list[dict] = field(default_factory=list)
    baseline: dict | None = None
    notes: list[str] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "line": self.line,
            "kind": self.kind,
            "recipe": self.recipe,
            "begin": self.begin,
            "end": self.end,
            "points": self.points,
            "baseline": self.baseline,
            "gaps": self.gaps,
            "notes": self.notes,
        }


def _stable_index(baselines: list[Baseline]) -> dict[tuple[str, str], Baseline]:
    return {(b.line, b.recipe): b for b in baselines}


def _no_signal_gaps(rows: list[dict], step_minutes: int) -> list[dict]:
    gaps = []
    for row in rows:
        if row.get("quality") == "no-signal":
            gaps.append(
                {
                    "line": row["line"],
                    "begin": row["at"],
                    "end": timex.add_minutes(row["at"], step_minutes),
                    "reason": NO_SIGNAL,
                }
            )
    return gaps


def detect(ledger: dict, baselines: list[Baseline], day: str) -> dict:
    index = _stable_index(baselines)
    lines = sorted({r["line"] for r in ledger["temperature_c"]})
    events: list[Event] = []
    expected: list[dict] = []
    gaps: list[dict] = []
    seq = 0

    for line in lines:
        rows = sorted(
            (r for r in ledger["temperature_c"] if r["line"] == line and r["at"].startswith(day)),
            key=lambda r: r["at"],
        )
        observed_times = [r["at"] for r in rows if r.get("quality") != "no-signal"]
        step = timex.dominant_step_minutes(observed_times)
        gaps.extend(_no_signal_gaps(rows, step))

        # 先按阶段连续性分组：预热/换配方是已知预期工况，单独列示不报警。
        groups: list[list[dict]] = []
        for row in rows:
            if groups and groups[-1][-1]["phase"] == row["phase"]:
                groups[-1].append(row)
            else:
                groups.append([row])
        steady: list[dict] = []
        for group in groups:
            if group[0]["phase"] == "steady":
                steady.extend(group)
            else:
                expected.append(_expected_window(group, step))

        # 相邻越界点合并为同一事件；无读数打断相邻性但保留各自归属。
        cluster: list[dict] = []

        def flush() -> None:
            nonlocal seq, cluster
            if not cluster:
                return
            seq += 1
            base = index.get((line, cluster[0]["recipe"]))
            kind = CONFIRMED if len(cluster) >= 2 else SPIKE
            notes: list[str] = []
            if base is None or not base.usable:
                kind = INCONCLUSIVE
                notes.append("无足够合格基线，越界不能确认为漂移")
            elif base.trial_only:
                notes.append("基线仅来自试产参考，确认强度受覆盖缺口限制")
            event = Event(
                event_id=f"E{seq}",
                line=line,
                kind=kind,
                recipe=cluster[0]["recipe"],
                begin=cluster[0]["at"],
                end=timex.add_minutes(cluster[-1]["at"], step),
                points=[
                    {"at": r["at"], "value": r["value"], "quality": r.get("quality")}
                    for r in cluster
                ],
                baseline=base.as_dict() if base else None,
                notes=notes,
            )
            events.append(event)
            cluster = []

        for row in steady:
            if row.get("quality") == "no-signal":
                flush()
                continue
            base = index.get((line, row["recipe"]))
            beyond = bool(base and base.usable and base.limits and not
                          (base.limits[0] <= float(row["value"]) <= base.limits[1]))
            if beyond:
                cluster.append(row)
            else:
                flush()
        flush()

    return {
        "events": [e.as_dict() for e in events],
        "expected_phase": expected,
        "no_signal_gaps": gaps,
    }


def _expected_window(run: list[dict], step_minutes: int) -> dict:
    return {
        "line": run[0]["line"],
        "phase": run[0]["phase"],
        "recipe": run[0]["recipe"],
        "begin": run[0]["at"],
        "end": timex.add_minutes(run[-1]["at"], step_minutes),
    }
