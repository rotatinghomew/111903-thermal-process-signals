"""批次在工序中的路径与异常暴露判定。

规则：

* ``corrects`` 引用的卡被更正卡取代；开卡时已发的隔离单不撤回，但待判
  批次按更正后的有效路径计算；
* 有效区间用 ``start_slack_minutes`` 放宽开始时刻（只放宽开始，结束不
  放宽），进料点 ``feed`` 不是炉线，不与炉线异常窗比对；
* 暴露分三档：所有可行路径都相交=``confirmed``，部分相交=``possible``，
  全部不相交=``excluded``；
* 抽检只证明它覆盖的生产区间，同名批次整日不会被一次抽检全盘定性；
* 同一事件对同一批次只产生一条处置，重复窗口可合并。
"""
from __future__ import annotations

from . import timex

CONFIRMED = "confirmed"
POSSIBLE = "possible"
EXCLUDED = "excluded"


def effective_routes(ledger: dict) -> list[dict]:
    """应用改线卡，返回每条批次当前有效的设备停留区间。"""
    rows = ledger["route_log"]
    corrected = {r["corrects"] for r in rows if "corrects" in r}
    effective = []
    for row in rows:
        if row["id"] in corrected:
            continue
        slack = row.get("start_slack_minutes", 0)
        effective.append(
            {
                "id": row["id"],
                "lot": row["lot"],
                "station": row["station"],
                "begin": timex.add_minutes(row["start"], -slack),
                "end": row["end"],
                "nominal_begin": row["start"],
                "slack_minutes": slack,
                "corrects": row.get("corrects"),
                "filed_at": row.get("filed_at"),
            }
        )
    return effective


def corrected_cards(ledger: dict) -> list[dict]:
    return [r for r in ledger["route_log"] if "corrects" in r]


def lot_exposure(routes: list[dict], events: list[dict]) -> dict[tuple[str, str], dict]:
    """返回 (批次, 炉线) 对各事件窗口的暴露结论。"""
    result: dict[tuple[str, str], dict] = {}
    furnace_routes = [r for r in routes if r["station"] != "feed"]
    for route in furnace_routes:
        key = (route["lot"], route["station"])
        entry = result.setdefault(
            key,
            {
                "lot": route["lot"],
                "line": route["station"],
                "station_window": [route["begin"], route["end"]],
                "status": EXCLUDED,
                "events": [],
            },
        )
        for event in events:
            if event["line"] != route["station"]:
                continue
            hit = timex.intersection(
                route["begin"], route["end"], event["begin"], event["end"]
            )
            if not hit:
                continue
            entry["events"].append(
                {
                    "event_id": event["event_id"],
                    "kind": event["kind"],
                    "intersection": list(hit),
                    "event_window": [event["begin"], event["end"]],
                }
            )
            if event["kind"] == "inconclusive":
                entry["status"] = POSSIBLE if entry["status"] == EXCLUDED else entry["status"]
            else:
                entry["status"] = CONFIRMED
    return result


def holds_as_issued(ledger: dict) -> list[dict]:
    """开卡时发出的隔离卡原样保留，供不可变台账引用。"""
    return [dict(card) for card in ledger.get("hold_cards", [])]


def inspections(ledger: dict) -> list[dict]:
    return [dict(row) for row in ledger.get("inspections", [])]


def evaluate_release(inspection: dict, lot: str, line: str, exposure: dict) -> dict:
    """判断一张抽检能否解除某批次在某炉线上的隔离理由。

    覆盖要求：同线、同批次，且抽检的生产区间完整覆盖该批次在该线的
    暴露交集；边界对不齐时保留候疑范围。
    """
    key = (lot, line)
    entry = exposure.get(key)
    if entry is None or inspection.get("line") != line or inspection.get("lot") != lot:
        return {"releases": False, "reason": "抽检未覆盖该批次/炉线"}
    within = inspection["lower"] <= inspection["measured"] <= inspection["upper"]
    if not within:
        return {"releases": False, "reason": "抽检结果超出限值，不能作为放行依据"}
    uncovered = []
    for hit in entry["events"]:
        begin, end = hit["intersection"]
        if timex.parse(inspection["begin"]) > timex.parse(begin) or timex.parse(
            inspection["end"]
        ) < timex.parse(end):
            uncovered.append(hit["event_id"])
    if uncovered:
        return {
            "releases": False,
            "reason": "抽检区间未完整覆盖暴露交集",
            "uncovered_events": uncovered,
            "recommended_targets": _recommend(entry),
        }
    return {"releases": True, "reason": "区间完整覆盖且结果合格"}


def _recommend(entry: dict) -> list[str]:
    """告诉值班员去测哪几批才能真正缩小候疑范围。"""
    return [f"{entry['lot']} 经过 {entry['line']} 的全部在制件"]
