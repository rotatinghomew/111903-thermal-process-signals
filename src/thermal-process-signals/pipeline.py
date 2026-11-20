"""当班分析总装管线。

把交班资料与补收的校时/返工资料合并为一份可追溯的当班结论。所有判断
共用同一套可行对时与同一批合格参考窗口；已发单据只追加、不改写。
"""
from __future__ import annotations

from . import baseline as baseline_mod
from . import clock_sync
from . import detect as detect_mod
from . import genealogy
from . import ledger as ledger_mod
from . import routing
from . import checks as checks_mod
from . import timex
from .clock_sync import CONFIRMED as C_CONFIRMED
from .clock_sync import EXCLUDED as C_EXCLUDED
from .clock_sync import POSSIBLE as C_POSSIBLE


def _merge_status(a: str, b: str) -> str:
    order = {routing.EXCLUDED: 0, routing.POSSIBLE: 1, routing.CONFIRMED: 2}
    return a if order[a] >= order[b] else b


def _clock_to_routing_status(clock_status: str) -> str:
    return {
        C_CONFIRMED: routing.CONFIRMED,
        C_POSSIBLE: routing.POSSIBLE,
        C_EXCLUDED: routing.EXCLUDED,
    }[clock_status]


def run_shift(ledger: dict, audit: dict | None = None) -> dict:
    day = next(r["date"] for r in ledger["reference_log"] if r["purpose"] == "live")

    # 1) 基线：只用当班之前的合格稳定参考，按线/配方分开。
    baselines = baseline_mod.build_baselines(ledger)
    baseline_sources = {
        b.line: [
            {"window": [s, timex.add_minutes(s, 1)], "recipe": b.recipe}
            for s in b.sources[:3]
        ]
        for b in baselines
    }

    # 2) 当班检测：预期工况、无读数、孤立尖峰、持续偏移分开。
    detection = detect_mod.detect(ledger, baselines, day)
    events = detection["events"]

    # 3) 改线路由与批次暴露。
    routes = routing.effective_routes(ledger)
    exposure = routing.lot_exposure(routes, events)

    timings = findings = segment_findings = coincident = None
    if audit is not None:
        timings = clock_sync.feasible_offsets(audit)
        findings = clock_sync.classify_readings(audit, timings, baselines)
        segment_findings = clock_sync.segment_evidence(findings)
        coincident = clock_sync.coincident_pairs(findings)

        # 记录仪证据并入同一暴露表，使用同一套可行对时。
        for entry in exposure.values():
            contact = clock_sync.contact_for_window(
                timings, findings, entry["line"],
                entry["station_window"][0], entry["station_window"][1],
            )
            entry["recorder_contact"] = contact
            if contact["status"] != C_EXCLUDED:
                entry["status"] = _merge_status(
                    entry["status"], _clock_to_routing_status(contact["status"])
                )

    # 4) 不可变台账：已发隔离单冻结，再按当前暴露追加处置。
    book = ledger_mod.DispositionLedger()
    book.import_holds(routing.holds_as_issued(ledger), baseline_sources)
    issued_at = f"{day}T12:00"
    for (lot, line), entry in sorted(exposure.items()):
        already = any(
            o.kind == ledger_mod.HOLD and o.lot_or_item == lot and o.line == line
            for o in book.orders
        )
        if already or entry["status"] == routing.EXCLUDED:
            continue
        window = [entry["station_window"][0], entry["station_window"][1]]
        book.add_hold(
            target=lot,
            line=line,
            reason=f"改线/对时复核后 {line} 暴露等级 {entry['status']}",
            window=window,
            references=baseline_sources.get(line, []),
            issued=issued_at,
            notes=["系统追加建议单，须值班员签认后生效"],
        )

    # 5) 抽检：只按明确覆盖到工况与时间窗的检查解除。
    release_decisions = []
    for inspection in routing.inspections(ledger):
        for lot in {e["lot"] for e in exposure.values()}:
            for line in {e["line"] for e in exposure.values()}:
                decision = routing.evaluate_release(
                    inspection, lot, line, exposure
                )
                decision.update(inspection=inspection["id"], lot=lot, line=line)
                release_decisions.append(decision)
                if decision["releases"]:
                    book.propose_release(
                        target=lot,
                        line=line,
                        reason=f"抽检 {inspection['id']} 完整覆盖且合格，解除提案待签认",
                        references=[
                            {"window": [inspection["begin"], inspection["end"]],
                             "recipe": "inspection"}
                        ],
                        issued=inspection["recorded"],
                    )

    # 6) 返工谱系与实物级接触。
    genealogy_view = None
    followups = None
    if audit is not None:
        stock = genealogy.replay(audit)
        lot_line_status = {
            (lot, line): entry["status"]
            for (lot, line), entry in exposure.items()
        }
        contacts = genealogy.container_contact(audit, stock, lot_line_status)
        # 实物级接触结论先形成隔离单（系统建议、待签认），之后抽检解除才能
        # 在同一理由矩阵上逐理由抵消，而不是清空容器的全部限制。
        for contact in contacts:
            if contact["status"] == genealogy.CONTACT_EXCLUDED:
                continue
            book.add_hold(
                target=contact["item"],
                line=contact["reason_line"],
                reason=f"返工实物 {contact['status']}：{contact['note']}",
                window=[f"{audit['production_day']}T00:00",
                        f"{audit['production_day']}T23:59"],
                references=baseline_sources.get(contact["reason_line"], []),
                issued=issued_at,
                notes=["系统追加建议单，须值班员签认后生效"],
            )
        rework_decisions = [
            genealogy.evaluate_rework_inspection(ins, stock, contacts)
            for ins in audit["rework_inspections"]
        ]
        for decision in rework_decisions:
            if decision.get("releases"):
                book.propose_release(
                    target=decision["item"],
                    line=decision["reason_line"],
                    reason=f"返工抽检 {decision['inspection']} 整箱覆盖合格，解除提案待签认",
                    references=[{"window": [audit["production_day"] + "T00:00",
                                            audit["production_day"] + "T23:59"],
                                 "recipe": "rework-inspection"}],
                    issued=next(i["recorded"] for i in audit["rework_inspections"]
                                if i["id"] == decision["inspection"]),
                )
        uncertain_segments = {
            t.segment_id for t in timings.values() if not t.pinned
        }
        followups = checks_mod.plan(
            audit, contacts, audit["rework_inspections"], timings, uncertain_segments
        )
        genealogy_view = {
            "stock": [c.as_dict() for c in stock.values()],
            "contact": contacts,
            "trace_overrides": genealogy.trace_overrides(audit),
            "inspection_decisions": rework_decisions,
        }

    return {
        "day": day,
        "baselines": [b.as_dict() for b in baselines],
        "expected_phase_windows": detection["expected_phase"],
        "no_signal_gaps": detection["no_signal_gaps"],
        "events": events,
        "effective_routes": routes,
        "corrected_cards": routing.corrected_cards(ledger),
        "exposure": [entry for entry in
                     sorted(exposure.values(), key=lambda e: (e["lot"], e["line"]))],
        "release_decisions": sorted(
            release_decisions, key=lambda d: (d["lot"], d["line"], d["inspection"])
        ),
        "clock": None if timings is None else {
            "segments": [t.as_dict() for t in timings.values()],
            "readings": findings,
            "segment_evidence": segment_findings,
            "coincident_pairs": coincident,
        },
        "genealogy": genealogy_view,
        "followup_checks": followups,
        "ledger": book.snapshot(),
        "active_restrictions": book.active_reasons(),
        "reconfirmation": book.reconfirmation_list(
            exposure, issued_at,
            corrected_routes=routing.corrected_cards(ledger),
            original_routes=ledger["route_log"],
        ),
    }
