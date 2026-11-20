"""返工车间的拆箱、混装与实物追踪。

关键规则：

* 每次移动按件数守恒重放；``records_origin=false`` 的混装使新容器失去
  逐件来源，签认的分箱卡只能证明该卡覆盖的那只箱，不能外推到同批的
  另一只箱；
* 已返工的实物不撤回原批；容器一旦失去逐件来源，对每个原始隔离理由只
  能给容器级三档结论（确已接触/仍可能接触/可排除）；
* ``item_trace`` 的完整炉线经历(``complete_furnace_trace``)只对卡上
  签认的容器和数量有效；
* 返工抽检只覆盖本次检查的实物、理由和数量；不足整箱且无逐件标识时，
  不能指定箱内具体哪几件，只能按容器级解除。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .clock_sync import CONFIRMED, EXCLUDED, POSSIBLE

CONTACT_CONFIRMED = "confirmed-contact"
CONTACT_POSSIBLE = "possible-contact"
CONTACT_EXCLUDED = "excluded-contact"


@dataclass
class Container:
    item: str
    qty: int
    # 仍可逐件归到原始批号的数量：{批号: 件数}
    origin: dict[str, int] = field(default_factory=dict)
    origin_lost_qty: int = 0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "item": self.item,
            "qty": self.qty,
            "known_origin": dict(self.origin),
            "origin_lost_qty": self.origin_lost_qty,
            "note": self.note,
        }


def replay(audit: dict) -> dict[str, Container]:
    """按移动顺序重放，返回当前现存实物所在容器（已被搬走的容器移除）。"""
    stock: dict[str, Container] = {}
    for lot, qty in audit["initial_counts"].items():
        stock[lot] = Container(item=lot, qty=qty, origin={lot: qty})

    for move in sorted(audit["material_moves"], key=lambda m: m["occurred"]):
        # 先把本次搬出的来源汇总成一个虚拟池：可溯源部分按批号，其余为失源。
        pool_origin: dict[str, int] = {}
        pool_lost = 0
        for parent, qty in move["parents"].items():
            container = stock[parent]
            if qty > container.qty:
                raise ValueError(f"移动 {move['id']} 从 {parent} 搬出数量超过库存")
            from_lost = min(qty, container.origin_lost_qty)
            container.origin_lost_qty -= from_lost
            pool_lost += from_lost
            remain = qty - from_lost
            for lot in sorted(container.origin):
                if remain <= 0:
                    break
                part = min(remain, container.origin[lot])
                container.origin[lot] -= part
                pool_origin[lot] = pool_origin.get(lot, 0) + part
                remain -= part
            container.qty -= qty
            if container.qty == 0 or (not container.origin and container.origin_lost_qty == 0):
                del stock[parent]

        traceable = move.get("records_origin", True)
        if traceable and pool_lost:
            raise ValueError(f"移动 {move['id']} 声称可溯源却包含失源件")
        total_children = sum(move["children"].values())
        total_parents = sum(move["parents"].values())
        if total_children != total_parents:
            raise ValueError(f"移动 {move['id']} 搬入搬出件数不守恒")

        if not traceable:
            for child, qty in move["children"].items():
                stock[child] = Container(
                    item=child, qty=qty, origin={}, origin_lost_qty=qty,
                    note="混装无逐件去向，来源只能按容器级候疑处理",
                )
            continue

        # 可溯源拆分：按件数顺序从来源池切给每个子容器。
        flat: list[tuple[str, int]] = list(pool_origin.items())
        cursor_lot, cursor_qty = 0, 0
        for child, qty in move["children"].items():
            child_origin: dict[str, int] = {}
            need = qty
            while need > 0:
                lot, available = flat[cursor_lot]
                take = min(need, available - cursor_qty)
                child_origin[lot] = child_origin.get(lot, 0) + take
                cursor_qty += take
                need -= take
                if cursor_qty == available:
                    cursor_lot += 1
                    cursor_qty = 0
            stock[child] = Container(item=child, qty=qty, origin=child_origin)
    return stock


def trace_overrides(audit: dict) -> list[dict]:
    """签认的实际炉线经历，只对卡上容器和数量有效，禁止外推。"""
    return [dict(t) for t in audit.get("item_trace", [])]


def container_contact(audit: dict, stock: dict[str, Container],
                      lot_line_status: dict[tuple[str, str], str]) -> list[dict]:
    """评估每个现存容器对每条原始隔离炉线理由的接触等级。"""
    lines = sorted({line for _, line in lot_line_status})
    traced: dict[str, list[dict]] = {}
    for tag in trace_overrides(audit):
        if tag.get("complete_furnace_trace"):
            traced.setdefault(tag["container"], []).append(tag)
    out = []
    for item, container in sorted(stock.items()):
        cards = traced.get(item, [])
        for line in lines:
            # 签认的“当班仅经历这些炉线”覆盖到本容器时，未列炉线可排除；
            # 结论只对卡上签认的容器与数量有效，禁止外推到同批另一只箱。
            if cards and all(tag["line"] != line for tag in cards):
                status = CONTACT_EXCLUDED
                note = (
                    f"签认完整炉线经历（{cards[0]['id']}）未列 {line}，"
                    f"本箱 {item} 可排除该线；结论仅限签认容器，不得外推到同批其他箱"
                )
            elif container.origin:
                statuses = [
                    lot_line_status.get((lot, line), POSSIBLE)
                    for lot in container.origin
                ]
                status = _roll_up(statuses)
                note = "按可溯源组成批次的暴露等级合并"
            else:
                # 失去逐件来源：只要任一来源批次可能接触，整箱保持候疑。
                parent_lots = _parent_lots(audit, item)
                statuses = [
                    lot_line_status.get((lot, line), POSSIBLE) for lot in parent_lots
                ]
                status = CONTACT_POSSIBLE if any(
                    s in (CONFIRMED, POSSIBLE) for s in statuses
                ) else CONTACT_EXCLUDED
                note = "混装后无逐件去向，无法把可排除来源的结论用于本箱放行"
            out.append(
                {
                    "item": item,
                    "qty": container.qty,
                    "reason_line": line,
                    "status": status,
                    "note": note,
                }
            )
    return out


def _roll_up(statuses: list[str]) -> str:
    if any(s == CONFIRMED for s in statuses):
        return CONTACT_CONFIRMED
    if any(s == POSSIBLE for s in statuses):
        return CONTACT_POSSIBLE
    return CONTACT_EXCLUDED


def _parent_lots(audit: dict, item: str) -> set[str]:
    """沿移动树向上找一个容器的全部原始批号来源。"""
    parents = set()

    def walk(node: str) -> None:
        found = False
        for move in audit["material_moves"]:
            if node in move["children"]:
                found = True
                for parent in move["parents"]:
                    if parent in audit["initial_counts"]:
                        parents.add(parent)
                    else:
                        walk(parent)
        if not found and node in audit["initial_counts"]:
            parents.add(node)

    walk(item)
    return parents


def evaluate_rework_inspection(inspection: dict, stock: dict[str, Container],
                               contacts: list[dict]) -> dict:
    """返工抽检能解除哪个容器的哪条隔离理由。

    覆盖整箱（数量等于现存件数）才解除容器级理由；不足整箱且无逐件
    标识时只登记证据，隔离仍保留。
    """
    item = inspection["item"]
    line = inspection["reason_line"]
    container = stock.get(item)
    if container is None:
        return {"inspection": inspection["id"], "releases": False,
                "reason": "容器已不存在，已返工实物不撤回原批"}
    within = inspection["lower"] <= inspection["measured"] <= inspection["upper"]
    if not within:
        return {"inspection": inspection["id"], "releases": False,
                "reason": "抽检结果超出限值"}
    contact = next((c for c in contacts
                    if c["item"] == item and c["reason_line"] == line), None)
    if contact and contact["status"] == CONTACT_EXCLUDED:
        return {"inspection": inspection["id"], "releases": False,
                "reason": "该理由本已可排除，抽检不改变结论"}
    if inspection.get("scope") != "recorded_items_only":
        return {"inspection": inspection["id"], "releases": False,
                "reason": "未知抽检范围"}
    if inspection["qty"] < container.qty:
        return {
            "inspection": inspection["id"],
            "releases": False,
            "reason": f"仅检 {inspection['qty']} 件、整箱 {container.qty} 件且无逐件标识，"
                      "不能指定具体件，容器级隔离保留",
        }
    return {"inspection": inspection["id"], "releases": True, "item": item,
            "reason_line": line, "reason": "整箱覆盖且结果合格，可解除该条理由；"
                                            "其他独立理由不受影响"}
