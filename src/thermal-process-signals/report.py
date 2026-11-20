"""把管线结论渲染成值班员可读的中文报告。"""
from __future__ import annotations

KIND_LABEL = {
    "confirmed-shift": "持续偏移（可确认）",
    "isolated-spike": "孤立尖峰",
    "inconclusive": "不可判断（样本/基线不足）",
    "inconclusive-isolated-point": "单点越界但邻点无读数，不可判断",
    "no-confirmed-anomaly": "无可确认异常",
}
STATUS_LABEL = {
    "confirmed": "确已接触",
    "possible": "仍可能接触",
    "excluded": "可排除",
    "confirmed-contact": "确已接触",
    "possible-contact": "仍可能接触",
    "excluded-contact": "可排除",
}


def render(result: dict) -> str:
    lines: list[str] = []
    lines.append(f"炉线当班分析报告（生产日 {result['day']}）")
    lines.append("=" * 52)

    lines.append("\n一、控制基线（仅当班前合格稳定参考，按线/配方分列）")
    for base in result["baselines"]:
        limits = base["limits"] or "不可用"
        tag = "试产参考" if base["trial_only"] else "正式参考"
        lines.append(
            f"- {base['line']}/{base['recipe']}：{tag}，n={base['n']}，"
            f"中心={base['center']}，控制限={limits}"
        )
        for note in base["notes"]:
            lines.append(f"    · {note}")

    lines.append("\n二、预期工况（不报警）与无读数区段（不计质量风险）")
    for window in result["expected_phase_windows"]:
        lines.append(
            f"- {window['line']} {window['phase']}（配方 {window['recipe']}）："
            f"{window['begin']}–{window['end']}"
        )
    for gap in result["no_signal_gaps"]:
        lines.append(f"- {gap['line']} 无读数：{gap['begin']}–{gap['end']}")

    lines.append("\n三、稳定阶段异常事件")
    if not result["events"]:
        lines.append("- 无")
    for event in result["events"]:
        lines.append(
            f"- {event['event_id']} {event['line']}/{event['recipe']} "
            f"{KIND_LABEL.get(event['kind'], event['kind'])}："
            f"{event['begin']}–{event['end']}，{len(event['points'])} 个越界点"
        )
        for note in event["notes"]:
            lines.append(f"    · {note}")

    lines.append("\n四、改线路由与批次暴露（含开始时刻误差与记录仪对时）")
    for card in result["corrected_cards"]:
        lines.append(
            f"- 改线卡 {card['id']} 取代 {card['corrects']}：批次 {card['lot']} "
            f"有效路径改到 {card['station']}，{card['filed_at']} 才获知；"
            "原工位已发隔离不撤回，待判批次按新路径"
        )
    for entry in result["exposure"]:
        lines.append(
            f"- {entry['lot']} @ {entry['line']}：{STATUS_LABEL[entry['status']]}"
            f"（设备窗口 {entry['station_window'][0]}–{entry['station_window'][1]}）"
        )
        for hit in entry["events"]:
            lines.append(
                f"    · 与 {hit['event_id']}（{KIND_LABEL.get(hit['kind'], hit['kind'])}）"
                f"交集 {hit['intersection'][0]}–{hit['intersection'][1]}"
            )
        rec = entry.get("recorder_contact")
        if rec and rec["contacts"]:
            lines.append(
                f"    · 记录仪接触等级：{STATUS_LABEL[rec['status']]}，"
                f"涉及连续段 {sorted({c['segment'] for c in rec['contacts']})}"
            )

    lines.append("\n五、抽检与解除提案")
    for decision in result["release_decisions"]:
        verdict = "可解除" if decision["releases"] else "不能解除"
        lines.append(
            f"- 抽检 {decision['inspection']} 对 {decision['lot']}/{decision['line']}："
            f"{verdict}（{decision['reason']}）"
        )
        if "recommended_targets" in decision:
            for target in decision["recommended_targets"]:
                lines.append(f"    · 建议补测：{target}")

    if result["clock"]:
        lines.append("\n六、记录仪对时（整段统一可行偏移，禁止逐点挑偏移）")
        for seg in result["clock"]["segments"]:
            rng = seg["feasible_offset_minutes"]
            lines.append(
                f"- {seg['segment']}（{seg['line']}）：可行偏移 {rng[0]}~{rng[1]} 分钟"
                + ("（已唯一）" if seg["pinned"] else "（仅区间，保留候疑）")
            )
        for evidence in result["clock"]["segment_evidence"]:
            lines.append(
                f"- {evidence['segment']} 结论：{KIND_LABEL.get(evidence['verdict'], evidence['verdict'])}；"
                f"对时不确定点 {len(evidence['uncertain_points'])} 个，"
                f"无读数点 {len(evidence['no_reading_points'])} 个"
            )
        for pair in result["clock"]["coincident_pairs"]:
            lines.append(
                f"- 表面报警 {pair['segments'][0]} 与 {pair['segments'][1]} 在现场时刻 "
                f"{pair['shared_wall_minutes']} 可重合：{pair['note']}"
            )

    if result["genealogy"]:
        lines.append("\n七、返工谱系与现存实物")
        for container in result["genealogy"]["stock"]:
            origin = container["known_origin"] or "无逐件来源"
            lines.append(
                f"- {container['item']}：{container['qty']} 件，可溯源={origin}"
                + (f"，{container['note']}" if container["note"] else "")
            )
        for contact in result["genealogy"]["contact"]:
            lines.append(
                f"- {contact['item']} 对 {contact['reason_line']} 理由："
                f"{STATUS_LABEL[contact['status']]}（{contact['note']}）"
            )
        for decision in result["genealogy"]["inspection_decisions"]:
            verdict = "可解除该理由" if decision.get("releases") else "不能解除"
            lines.append(
                f"- 返工抽检 {decision['inspection']}：{verdict}（{decision['reason']}）"
            )

    if result["followup_checks"]:
        lines.append("\n八、补查方案（能排除什么 / 即使完成也解除不了什么）")
        for check in result["followup_checks"]:
            lines.append(f"- {check['id']} {check['kind']}（{check['available_at']} 可取）")
            for item in check["can_resolve"]:
                lines.append(f"    能：{item}")
            for item in check["cannot_resolve"]:
                lines.append(f"    不能：{item}")

    lines.append("\n九、处置台账与仍在限制的范围")
    kind_cn = {"hold": "隔离单", "release-proposal": "解除提案",
               "reconfirmation-needed": "再确认提示"}
    for order in result["ledger"]:
        flag = "（待人工签认）" if order.get("requires_confirmation") else ""
        lines.append(
            f"- [{order['order_id']}] {kind_cn.get(order['kind'], order['kind'])} "
            f"{order['lot_or_item']}/{order['line']} {order['status']}{flag}，"
            f"签发={order['issued']}，确认人={order['authority'] or '无'}"
        )
    lines.append("- 当前仍限制：")
    for target, reasons in result["active_restrictions"].items():
        for reason in reasons:
            lines.append(f"    · {target} 被 {reason['line']} 理由限制（单据 {reason['order_id']}）")
    if result["reconfirmation"]:
        lines.append("- 新分析与旧决策不一致，须再次人工确认：")
        for item in result["reconfirmation"]:
            lines.append(f"    · {item['lot']}/{item['line']}：{item['reason']}")

    return "\n".join(lines)
