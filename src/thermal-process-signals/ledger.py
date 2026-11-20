"""电子处置单台账（只追加，不改写）。

已经发出的隔离单与解除单不可修改；复盘员按后来修正的实际路径重新
估计时，只能追加新分析，并把与旧决策不一致、须再次人工确认的批次
及原因列出来。每条处置单都记录当班使用的参考窗口、当前仍限制的
批次以及确认人。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

HOLD = "hold"
RELEASE = "release-proposal"
RECONFIRM = "reconfirmation-needed"


@dataclass
class Order:
    order_id: str
    kind: str
    lot_or_item: str
    line: str
    reason: str
    evidence_window: list[str]
    reference_windows: list[dict]
    issued: str
    authority: str | None
    status: str = "active"
    supersedes: str | None = None
    requires_confirmation: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class DispositionLedger:
    def __init__(self) -> None:
        self.orders: list[Order] = []
        self._seq = 0

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:03d}"

    def import_holds(self, hold_cards: list[dict], baseline_sources: dict[str, list[dict]]) -> None:
        """开卡时已发的隔离单原样入账，证据窗口冻结。"""
        for card in hold_cards:
            self.orders.append(
                Order(
                    order_id=card["id"],
                    kind=HOLD,
                    lot_or_item=card["lot"],
                    line=card["line"],
                    reason=f"{card['line']} 异常工况隔离",
                    evidence_window=[card["begin"], card["end"]],
                    reference_windows=baseline_sources.get(card["line"], []),
                    issued=card["issued"],
                    authority=card["authority"],
                )
            )
            self._seq = max(self._seq, int(card["id"][1:]))

    def add_hold(self, target: str, line: str, reason: str, window: list[str],
                 references: list[dict], issued: str, authority: str | None = None,
                 notes: list[str] | None = None) -> Order:
        order = Order(
            order_id=self._next_id("H"),
            kind=HOLD,
            lot_or_item=target,
            line=line,
            reason=reason,
            evidence_window=list(window),
            reference_windows=references,
            issued=issued,
            authority=authority,
            # 无签认人的系统建议单仍反映客观限制，但必须人工确认后才算正式处置。
            requires_confirmation=authority is None,
            notes=notes or [],
        )
        self.orders.append(order)
        return order

    def propose_release(self, target: str, line: str, reason: str,
                        references: list[dict], issued: str,
                        authority: str | None = None) -> Order:
        """解除只是提案：必须有确认人后才真正恢复流转。"""
        order = Order(
            order_id=self._next_id("R"),
            kind=RELEASE,
            lot_or_item=target,
            line=line,
            reason=reason,
            evidence_window=[],
            reference_windows=references,
            issued=issued,
            authority=authority,
            status="proposed" if authority is None else "confirmed",
        )
        self.orders.append(order)
        return order

    def active_reasons(self) -> dict[str, list[dict]]:
        """当前仍限制每个对象的理由矩阵；独立理由分别计数。"""
        matrix: dict[str, dict[str, Order]] = {}
        for order in self.orders:
            if order.kind == HOLD and order.status == "active":
                matrix.setdefault(order.lot_or_item, {})[order.line] = order
            elif order.kind == RELEASE and order.status == "confirmed":
                matrix.get(order.lot_or_item, {}).pop(order.line, None)
        return {
            target: [order.as_dict() for order in sorted(by_line.values(), key=lambda o: o.line)]
            for target, by_line in sorted(matrix.items())
            if by_line
        }

    def reconfirmation_list(self, current_exposure: dict[tuple[str, str], dict],
                            known_at: str, corrected_routes: list[dict] | None = None,
                            original_routes: list[dict] | None = None) -> list[dict]:
        """新分析与旧决策不一致时，只追加提示，绝不改写已发单据。"""
        items = []
        for (lot, line), entry in sorted(current_exposure.items()):
            has_hold = any(
                o.kind == HOLD and o.lot_or_item == lot and o.line == line
                for o in self.orders
            )
            if entry["status"] == "confirmed" and not has_hold:
                items.append(
                    {
                        "lot": lot,
                        "line": line,
                        "reason": "更正路径显示该批次确在异常窗内经过，但无对应隔离单",
                        "exposure": entry,
                        "must_keep_pending": True,
                    }
                )
            if has_hold and entry["status"] == "excluded":
                items.append(
                    {
                        "lot": lot,
                        "line": line,
                        "reason": "更正路径显示该批次不经过该线异常窗，旧隔离单仍有效，"
                                  "须人工复核后另发解除单，原单不得直接改写",
                        "exposure": entry,
                    }
                )
        # 改线卡把批次从某炉线移走：旧路径上的怀疑在新路径下已不成立，
        # 但旧单据/旧报警不自动撤回，必须人工再确认。
        if corrected_routes and original_routes:
            effective_keys = set(current_exposure)
            original_by_id = {r["id"]: r for r in original_routes}
            for new_route in corrected_routes:
                old = original_by_id.get(new_route.get("corrects", ""))
                if not old or old["station"] == "feed":
                    continue
                key = (old["lot"], old["station"])
                if key not in effective_keys:
                    items.append(
                        {
                            "lot": old["lot"],
                            "line": old["station"],
                            "reason": (
                                f"改线卡 {new_route['id']}（{new_route['filed_at']} 获知）"
                                f"把批次从 {old['station']} 改到 {new_route['station']}，"
                                "原工位报警不自动撤回，须人工再确认是否解除"
                            ),
                        }
                    )
        return items

    def snapshot(self) -> list[dict]:
        return [o.as_dict() for o in self.orders]
