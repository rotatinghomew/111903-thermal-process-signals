"""补查方案评估。

把重新校时、核对分箱交接、补做抽检三类办法放到同一视图里，明确每种
办法能缩小哪些候疑范围、即使完成也无法解除哪条独立限制，避免值班员
白做检查。
"""
from __future__ import annotations


def plan(audit: dict, contacts: list[dict], inspection_results: list[dict],
         timings: dict, uncertain_segments: set[str]) -> list[dict]:
    stock_items = {c["item"] for c in contacts}
    plans = []
    for check in audit.get("available_checks", []):
        entry = {"id": check["id"], "kind": check["kind"],
                 "available_at": check["available_at"],
                 "can_resolve": [], "cannot_resolve": []}
        if check["kind"] == "clock_anchor":
            seg = check.get("segment")
            entry["can_resolve"].append(
                f"把连续段 {seg} 的可行偏移收窄到确定值，消除对时不确定导致的"
                "候疑（稳定/预热边界读数可重新归段）"
            )
            entry["cannot_resolve"].append(
                "不能改变已在所有可行对时下确认的持续偏移，也不能替代任何抽检放行"
            )
            if seg not in uncertain_segments:
                entry["cannot_resolve"].append(f"{seg} 偏移已唯一确定，补锚点不新增信息")
        elif check["kind"] == "transfer_tags":
            move_id = check.get("move")
            lost = [c for c in contacts if c["status"] == "possible-contact"]
            entry["can_resolve"].append(
                f"恢复混装移动 {move_id} 的逐件来源，使 {sorted({c['item'] for c in lost})} "
                "可按实际来源批次分别判定，仅含可排除来源的件可退出候疑"
            )
            entry["cannot_resolve"].append(
                "对仍含已接触来源的件无效；也不能解除需要抽检合格才能撤的隔离理由"
            )
        elif check["kind"] == "inspection":
            item, line = check.get("item"), check.get("reason_line")
            target = next((c for c in contacts
                           if c["item"] == item and c["reason_line"] == line), None)
            if target is None:
                entry["cannot_resolve"].append(f"{item} 在 {line} 没有对应隔离理由")
            else:
                entry["can_resolve"].append(
                    f"若对 {item} 整箱 {target['qty']} 件抽检合格，可解除 {line} 这一条理由"
                )
                other = [c["reason_line"] for c in contacts
                         if c["item"] == item and c["reason_line"] != line
                         and c["status"] != "excluded-contact"]
                entry["cannot_resolve"].append(
                    f"不影响其他独立限制：{sorted(other) if other else '无'}"
                )
                entry["cannot_resolve"].append(
                    "若不足整箱且无逐件标识，仍不能指定箱内哪几件，隔离保留"
                )
        plans.append(entry)
    return plans
