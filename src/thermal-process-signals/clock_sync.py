"""记录仪对时与连续段证据分类。

记录仪与工单系统不是同一只钟，仪器重启后开始新的连续段。同一连续段内
所有测点必须使用同一个可行偏移（整分钟，偏移量 = 现场时刻 - 记录仪
时刻）；锚点只给区间时，可行偏移取各锚点约束的交集，禁止为了证明报警
或放行而给每个测点单独挑偏移。

每个测点按可行偏移映射到现场时刻后分三类：

* 所有可行偏移下都落在同一配方/稳定阶段且越界 → 可确认异常；
* 不同可行偏移会落到不同阶段（如稳定 vs 预热）→ 对时不确定区段；
* 记录仪无值 → 无读数区段。

工艺基线只能引用能可靠归到配方与稳定阶段的合格资料。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import timex
from .baseline import Baseline

CONFIRMED = "confirmed"
POSSIBLE = "possible"
EXCLUDED = "excluded"
NO_READING = "no-reading"
UNCERTAIN = "timing-uncertain"
EXPECTED_PHASE = "expected-phase"
STEADY_OK = "steady-in-control"


@dataclass
class SegmentTiming:
    segment_id: str
    device: str
    line: str
    offset_minutes_min: int
    offset_minutes_max: int
    anchors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def pinned(self) -> bool:
        return self.offset_minutes_min == self.offset_minutes_max

    def as_dict(self) -> dict:
        return {
            "segment": self.segment_id,
            "device": self.device,
            "line": self.line,
            "feasible_offset_minutes": [
                self.offset_minutes_min,
                self.offset_minutes_max,
            ],
            "pinned": self.pinned,
            "anchors": self.anchors,
            "notes": self.notes,
        }


def feasible_offsets(audit: dict) -> dict[str, SegmentTiming]:
    """由各锚点的现场时刻区间求每个连续段的可行整数偏移交集。"""
    segments = {s["id"]: s for s in audit["segments"]}
    devices = {d["id"]: d["line"] for d in audit["devices"]}
    timings: dict[str, SegmentTiming] = {}
    for seg_id, seg in segments.items():
        lo, hi = None, None
        anchor_ids = []
        for anchor in audit["anchors"]:
            if anchor["segment"] != seg_id:
                continue
            anchor_ids.append(anchor["id"])
            d_lo = timex.minute_diff(anchor["wall_earliest"], anchor["local"])
            d_hi = timex.minute_diff(anchor["wall_latest"], anchor["local"])
            lo = d_lo if lo is None else max(lo, d_lo)
            hi = d_hi if hi is None else min(hi, d_hi)
        if lo is None or hi is None or lo > hi:
            raise ValueError(f"连续段 {seg_id} 的锚点约束无可行偏移交集")
        timing = SegmentTiming(
            segment_id=seg_id,
            device=seg["device"],
            line=devices[seg["device"]],
            offset_minutes_min=lo,
            offset_minutes_max=hi,
            anchors=anchor_ids,
        )
        if not timing.pinned:
            timing.notes.append("偏移只能约束到区间，对时不确定区段需保留候疑")
        timings[seg_id] = timing
    return timings


class _PhaseIndex:
    def __init__(self, phase_log: list[dict]):
        self.rows = sorted(phase_log, key=lambda r: (r["line"], r["start"]))

    def lookup(self, line: str, wall: str) -> dict | None:
        for row in self.rows:
            if row["line"] != line:
                continue
            if timex.parse(row["start"]) <= timex.parse(wall) < timex.parse(row["end"]):
                return row
        return None


def _wall_minutes(local: str, lo: int, hi: int) -> list[str]:
    return [timex.add_minutes(local, delta) for delta in range(lo, hi + 1)]


def classify_readings(audit: dict, timings: dict[str, SegmentTiming],
                      baselines: list[Baseline]) -> list[dict]:
    phase_index = _PhaseIndex(audit["phase_log"])
    base_index = {(b.line, b.recipe): b for b in baselines}
    findings = []
    for reading in audit["sensor_readings"]:
        timing = timings[reading["segment"]]
        entry = {
            "segment": reading["segment"],
            "line": timing.line,
            "local": reading["local"],
            "value": reading["value"],
            "feasible_wall_window": [
                timex.add_minutes(reading["local"], timing.offset_minutes_min),
                timex.add_minutes(reading["local"], timing.offset_minutes_max),
            ],
        }
        if reading["value"] is None:
            entry.update(classification=NO_READING,
                         note="设备未采到值：无读数区段，不计质量风险")
            findings.append(entry)
            continue

        walls = _wall_minutes(
            reading["local"], timing.offset_minutes_min, timing.offset_minutes_max
        )
        phases = [phase_index.lookup(timing.line, w) for w in walls]
        keys = {(p["recipe"], p["phase"]) if p else None for p in phases}
        if None in keys:
            entry.update(classification=UNCERTAIN,
                         note="部分可行对时下落在工艺阶段记录之外")
            findings.append(entry)
            continue
        if len(keys) > 1:
            entry.update(
                classification=UNCERTAIN,
                feasible_phases=sorted({f"{p['recipe']}/{p['phase']}" for p in phases}),
                note="不同可行偏移落到不同阶段，不能填确切接触结论",
            )
            findings.append(entry)
            continue

        phase = phases[0]
        entry["recipe"] = phase["recipe"]
        entry["phase"] = phase["phase"]
        if phase["phase"] != "steady":
            entry.update(classification=EXPECTED_PHASE,
                         note=f"对时后落在{phase['phase']}，属预期工况，不进基线、不报警")
            findings.append(entry)
            continue

        base = base_index.get((timing.line, phase["recipe"]))
        entry["baseline_eligible"] = bool(base and base.usable and not base.trial_only)
        if base is None or not base.usable or base.limits is None:
            entry.update(classification=UNCERTAIN,
                         note="稳定阶段但无足够合格基线，不可判断")
        elif base.limits[0] <= float(reading["value"]) <= base.limits[1]:
            entry.update(classification=STEADY_OK)
        else:
            note = "所有可行对时下均为稳定阶段且越界"
            if base.trial_only:
                note += "；基线仅试产参考，确认强度受限"
            entry.update(classification=CONFIRMED, note=note)
        findings.append(entry)
    return findings


def segment_evidence(findings: list[dict]) -> list[dict]:
    """把测点级分类汇总成连续段证据，区分孤立尖峰与持续偏移。"""
    by_seg: dict[str, list[dict]] = {}
    for item in findings:
        by_seg.setdefault(item["segment"], []).append(item)
    out = []
    for seg_id, items in sorted(by_seg.items()):
        items.sort(key=lambda x: x["local"])
        confirmed = [x for x in items if x["classification"] == CONFIRMED]
        uncertain = [x for x in items if x["classification"] == UNCERTAIN]
        no_reading = [x for x in items if x["classification"] == NO_READING]
        if len(confirmed) >= 2:
            verdict = "confirmed-shift"
        elif len(confirmed) == 1:
            verdict = "isolated-spike"
            neighbors = [x for x in items if x["local"] != confirmed[0]["local"]
                         and x["classification"] in (NO_READING, UNCERTAIN)]
            if neighbors:
                verdict = "inconclusive-isolated-point"
        else:
            verdict = "no-confirmed-anomaly"
        out.append(
            {
                "segment": seg_id,
                "line": items[0]["line"],
                "verdict": verdict,
                "confirmed_points": confirmed,
                "uncertain_points": uncertain,
                "no_reading_points": no_reading,
            }
        )
    return out


def coincident_pairs(findings: list[dict]) -> list[dict]:
    """检测不同连续段的两个报警测点在可行对时下是否可能重合为同一现场时刻。"""
    pairs = []
    # 任何可能被当成“报警”的测点都要参与重合检查，包括已可靠归入预热的点：
    # 时钟改正可能证明两只钟的表面报警其实是同一现场时刻。
    alarms = [
        x for x in findings
        if x["classification"] in (CONFIRMED, UNCERTAIN, EXPECTED_PHASE)
    ]
    for i, a in enumerate(alarms):
        for b in alarms[i + 1:]:
            # 仪器重启产生不同连续段；同线的两段才可能是同一现场时刻的重复报警。
            if a["segment"] == b["segment"] or a["line"] != b["line"]:
                continue
            if timex.overlaps(*a["feasible_wall_window"], *b["feasible_wall_window"]):
                pairs.append(
                    {
                        "segments": [a["segment"], b["segment"]],
                        "line": a["line"],
                        "locals": [a["local"], b["local"]],
                        "shared_wall_minutes": _shared_minutes(
                            a["feasible_wall_window"], b["feasible_wall_window"]
                        ),
                        "note": "两只钟的表面报警在可行对时下可重合，按同一现场时刻评估",
                    }
                )
    return pairs


def _shared_minutes(window_a: list[str], window_b: list[str]) -> list[str]:
    from datetime import timedelta

    begin = max(timex.parse(window_a[0]), timex.parse(window_b[0]))
    end = min(timex.parse(window_a[1]), timex.parse(window_b[1]))
    if begin > end:
        return []
    out = []
    cur = begin
    while cur <= end:
        out.append(timex.fmt(cur))
        cur = cur + timedelta(minutes=1)
    return out


def contact_for_window(timings: dict[str, SegmentTiming], findings: list[dict],
                       line: str, begin: str, end: str) -> dict:
    """按同一套可行对时判定某设备窗口与连续段证据的接触等级。"""
    status = EXCLUDED
    detail = []
    for item in findings:
        timing = timings[item["segment"]]
        if timing.line != line:
            continue
        lo, hi = timing.offset_minutes_min, timing.offset_minutes_max
        walls = _wall_minutes(item["local"], lo, hi)
        hits = [w for w in walls if timex.overlaps(begin, end, w,
                                                   timex.add_minutes(w, 1))]
        if not hits:
            continue
        all_offsets_hit = len(hits) == (hi - lo + 1)
        if item["classification"] == CONFIRMED:
            rank = CONFIRMED if all_offsets_hit else POSSIBLE
        elif item["classification"] in (UNCERTAIN, NO_READING):
            rank = POSSIBLE
        elif item["classification"] == EXPECTED_PHASE:
            # 已可靠归入预热/换配方的读数不构成稳定过程质量风险。
            continue
        else:
            # 稳定阶段内的在控点同样不构成风险。
            continue
        status = _stronger(status, rank)
        detail.append(
            {
                "segment": item["segment"],
                "local": item["local"],
                "classification": item["classification"],
                "contact": rank,
                "wall_minutes": hits,
            }
        )
    return {"status": status, "contacts": detail}


def _stronger(a: str, b: str) -> str:
    order = {EXCLUDED: 0, POSSIBLE: 1, CONFIRMED: 2}
    return a if order[a] >= order[b] else b
