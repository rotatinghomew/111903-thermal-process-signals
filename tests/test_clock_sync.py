"""记录仪对时：整段统一偏移、三档证据与重合检测。"""
import unittest

from _support import build_result, load_data, load_package


class ClockSyncTests(unittest.TestCase):
    def setUp(self):
        self.tps = load_package()
        self.audit = load_data("rework_census.json")
        self.ledger = load_data("shift_handoff.json")
        self.baselines = self.tps.baseline.build_baselines(self.ledger)
        self.timings = self.tps.clock_sync.feasible_offsets(self.audit)
        self.findings = self.tps.clock_sync.classify_readings(
            self.audit, self.timings, self.baselines
        )
        self.by_local = {(f["segment"], f["local"]): f for f in self.findings}

    def test_feasible_offsets_are_intersected_per_segment(self):
        self.assertEqual(self.timings["A1"].offset_minutes_min, 0)
        self.assertEqual(self.timings["A1"].offset_minutes_max, 2)
        self.assertFalse(self.timings["A1"].pinned)
        self.assertTrue(self.timings["A2"].pinned)
        self.assertEqual(self.timings["A2"].offset_minutes_min, -2)
        self.assertEqual(self.timings["B1"].offset_minutes_min, 0)

    def test_conflicting_anchors_raise(self):
        bad = {
            **self.audit,
            "anchors": [
                {"id": "K1", "segment": "A1", "local": "2026-07-03T10:10",
                 "wall_earliest": "2026-07-03T10:10",
                 "wall_latest": "2026-07-03T10:10", "known": "x"},
                {"id": "K1b", "segment": "A1", "local": "2026-07-03T10:10",
                 "wall_earliest": "2026-07-03T10:30",
                 "wall_latest": "2026-07-03T10:30", "known": "x"},
            ],
        }
        with self.assertRaises(ValueError):
            self.tps.clock_sync.feasible_offsets(bad)

    def test_phase_boundary_readings_are_uncertain_not_forced(self):
        f = self.by_local[("A1", "2026-07-03T10:12")]
        self.assertEqual(f["classification"], "timing-uncertain")
        self.assertIn("R1/steady", f["feasible_phases"])
        self.assertIn("R3/warmup", f["feasible_phases"])

    def test_warmup_readings_never_become_baseline_or_alarm(self):
        f = self.by_local[("A1", "2026-07-03T10:15")]
        self.assertEqual(f["classification"], "expected-phase")
        f2 = self.by_local[("A2", "2026-07-03T10:18")]
        self.assertEqual(f2["classification"], "expected-phase")

    def test_null_reading_is_no_reading_category(self):
        f = self.by_local[("A2", "2026-07-03T10:21")]
        self.assertEqual(f["classification"], "no-reading")

    def test_b1_three_points_confirmed_shift_single_offset(self):
        evidence = {e["segment"]: e
                    for e in self.tps.clock_sync.segment_evidence(self.findings)}
        self.assertEqual(evidence["B1"]["verdict"], "confirmed-shift")
        self.assertEqual(len(evidence["B1"]["confirmed_points"]), 3)
        # 同段全部测点使用同一个偏移，不允许逐点挑。
        self.assertEqual(self.timings["B1"].offset_minutes_min,
                         self.timings["B1"].offset_minutes_max)

    def test_a2_isolated_point_with_neighbour_gap_is_inconclusive(self):
        evidence = {e["segment"]: e
                    for e in self.tps.clock_sync.segment_evidence(self.findings)}
        self.assertEqual(evidence["A2"]["verdict"],
                         "inconclusive-isolated-point")

    def test_coincident_alarms_merge_under_feasible_clock(self):
        pairs = self.tps.clock_sync.coincident_pairs(self.findings)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(set(pairs[0]["segments"]), {"A1", "A2"})
        self.assertIn("2026-07-03T10:16", pairs[0]["shared_wall_minutes"])

    def test_contact_uses_same_feasible_clock(self):
        # X8 的 L2 窗口与 B1 已锁定偏移下的确认点接触。
        contact = self.tps.clock_sync.contact_for_window(
            self.timings, self.findings, "L2",
            "2026-07-03T10:17", "2026-07-03T10:20",
        )
        self.assertEqual(contact["status"], "confirmed")
        # 与任何可行对时都不相交的窗口只能是 excluded。
        none = self.tps.clock_sync.contact_for_window(
            self.timings, self.findings, "L2",
            "2026-07-03T08:00", "2026-07-03T08:30",
        )
        self.assertEqual(none["status"], "excluded")


if __name__ == "__main__":
    unittest.main()
