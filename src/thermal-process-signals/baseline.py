"""控制基线。

基线只允许使用截至当班时已存在、且能可靠归入指定配方与稳定阶段的合格
参考资料：

* ``reference_log`` 里 ``live`` 当天的读数一律不进基线，处置完才确认的坏
  窗口因此不可能被补成训练数据；
* 预热(``warm-up``)与换配方(``switch``)阶段不代表稳定中心，不进基线；
* 采不到值(``no-signal``)属于设备无读数，不是过程观测，不进基线；
* 参考日里与当日主配方不同的试产块只能给出试产参考，必须标明覆盖缺口；
* 每条线、每个配方分别建基线，不允许跨线合并均值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev

from . import timex

STEADY = "steady"
MIN_QUALIFIED_POINTS = 6


@dataclass
class Baseline:
    line: str
    recipe: str
    points: list[float] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    trial_only: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.points)

    @property
    def usable(self) -> bool:
        return self.n >= MIN_QUALIFIED_POINTS

    @property
    def center(self) -> float | None:
        return mean(self.points) if self.points else None

    @property
    def sigma(self) -> float | None:
        if len(self.points) < 2:
            return None
        return pstdev(self.points)

    @property
    def limits(self) -> tuple[float, float] | None:
        """参考数据按固定模式循环，总体标准差为 0 时回退到观测包络。"""
        if not self.usable or self.center is None:
            return None
        spread = 3 * (self.sigma or 0.0)
        if spread == 0.0:
            return min(self.points), max(self.points)
        return self.center - spread, self.center + spread

    def as_dict(self) -> dict:
        return {
            "line": self.line,
            "recipe": self.recipe,
            "n": self.n,
            "usable": self.usable,
            "trial_only": self.trial_only,
            "center": round(self.center, 3) if self.center is not None else None,
            "sigma": round(self.sigma, 4) if self.sigma is not None else None,
            "limits": [round(v, 3) for v in self.limits] if self.limits else None,
            "sources": self.sources,
            "notes": self.notes,
        }


def _reference_dates(ledger: dict, line: str) -> tuple[set[str], str]:
    candidates, live = set(), ""
    for row in ledger.get("reference_log", []):
        if row["line"] != line:
            continue
        if row["purpose"] == "live":
            live = row["date"]
        else:
            candidates.add(row["date"])
    return candidates, live


def _day_blocks(rows: list[dict]) -> dict[str, list[dict]]:
    blocks: dict[str, list[dict]] = {}
    for row in rows:
        blocks.setdefault(row["at"][:10], []).append(row)
    return blocks


def build_baselines(ledger: dict) -> list[Baseline]:
    """按 (线, 配方) 构建当班开始时可用的控制基线。"""
    out: list[Baseline] = []
    by_line: dict[str, list[dict]] = {}
    for row in ledger["temperature_c"]:
        by_line.setdefault(row["line"], []).append(row)

    for line, rows in sorted(by_line.items()):
        ref_dates, live = _reference_dates(ledger, line)
        blocks = _day_blocks(rows)
        grouped: dict[str, Baseline] = {}
        for day in sorted(d for d in blocks if d in ref_dates):
            day_rows = blocks[day]
            # 该参考日实际运行的稳定配方；只在异配方稳定块（换配方前的
            # 试产）上打试产标记，正式生产过的旧配方仍是合格参考。
            day_steady_recipes = {r["recipe"] for r in day_rows if r["phase"] == STEADY}
            day_main = max(day_steady_recipes,
                           key=lambda rc: sum(1 for r in day_rows if r["recipe"] == rc))
            for recipe in sorted({r["recipe"] for r in day_rows}):
                base = grouped.setdefault(recipe, Baseline(line=line, recipe=recipe))
                is_trial = recipe != day_main
                added = 0
                for row in day_rows:
                    if row["recipe"] != recipe:
                        continue
                    if row["phase"] != STEADY or row.get("quality") == "no-signal":
                        continue
                    base.points.append(float(row["value"]))
                    base.sources.append(row["at"])
                    added += 1
                if is_trial and added:
                    base.notes.append(
                        f"{day} 的 {recipe} 稳定段属于换配方前试产，非当日主配方参考"
                    )
                elif added:
                    base.notes.append(f"{day} 的 {recipe} 为当日主配方正式生产参考")
        # 纯试产 = 所有来源日均为试产；只要有一天正式生产过即按正式基线用。
        for base in grouped.values():
            base.trial_only = not any("正式生产参考" in n for n in base.notes)
        for base in grouped.values():
            if not base.usable:
                base.notes.append(
                    f"合格稳定参考仅 {base.n} 点，少于 {MIN_QUALIFIED_POINTS} 点，"
                    "越界只能提示不可判断，不能单独确认漂移"
                )
            if base.trial_only:
                base.notes.append("仅试产参考：缺少同配方正式生产日，覆盖缺口需在报告中声明")
            elif any("试产" in note for note in base.notes):
                base.notes.append("含部分试产来源，结论以正式参考为主、试产块仅作补充")
            out.append(base)
    return out


def expected_phase_windows(ledger: dict, day: str) -> list[dict]:
    """当班当天的换配方/预热预期窗口，用于把预期切换与实际漂移分开。"""
    rows = sorted(
        (r for r in ledger["temperature_c"] if r["at"].startswith(day) and r["phase"] != STEADY),
        key=lambda r: (r["line"], r["at"]),
    )
    windows: list[dict] = []
    for row in rows:
        key = (row["line"], row["phase"], row["recipe"])
        if windows and (windows[-1]["line"], windows[-1]["phase"], windows[-1]["recipe"]) == key:
            windows[-1]["_times"].append(row["at"])
        else:
            windows.append(
                {
                    "line": row["line"],
                    "phase": row["phase"],
                    "recipe": row["recipe"],
                    "_times": [row["at"]],
                }
            )
    out = []
    for w in windows:
        times = w.pop("_times")
        step = timex.dominant_step_minutes(times)
        out.append(
            {
                "line": w["line"],
                "phase": w["phase"],
                "recipe": w["recipe"],
                "begin": times[0],
                "end": timex.add_minutes(times[-1], step),
            }
        )
    return out
