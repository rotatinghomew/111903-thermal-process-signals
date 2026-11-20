"""跨对时稳健性与降级运行测试。"""
import unittest

from _support import load_data, load_package


class ClockRobustReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tps = load_package()
        self.audit = load_data("rework_census.json")
        self.ledger = load_data("shift_handoff.json")

    def test_inspection_valid_for_all_feasible_origins_is_robust(self):
        """抽检在所有尚可成立的来源上都有效时，才能作为混装箱放行依据。"""
        result = self.tps.pipeline.run_shift(self.ledger, self.audit)
        decisions = {d["inspection"]: d
                     for d in result["genealogy"]["inspection_decisions"]}
        # I81 整箱 17 件全部覆盖、结果在限内：对任一可能来源都成立。
        self.assertTrue(decisions["I81"]["releases"])
        # I82 只有 11/17 件：存在覆盖不到的可能来源件，不能放行。
        self.assertFalse(decisions["I82"]["releases"])

    def test_pipeline_runs_without_clock_and_rework_data(self):
        result = self.tps.pipeline.run_shift(self.ledger, None)
        self.assertIsNone(result["clock"])
        self.assertIsNone(result["genealogy"])
        self.assertIsNone(result["followup_checks"])
        # 没有对时资料时，当班检测与路由结论仍完整。
        self.assertEqual(len(result["events"]), 2)
        self.assertIn(("X8", "L1"),
                      {(e["lot"], e["line"]) for e in result["exposure"]})

    def test_possible_clock_contact_downgrades_confirmed_to_pending(self):
        """记录仪只给区间对时时，设备窗口证据再强也只能保留候疑。"""
        result = self.tps.pipeline.run_shift(self.ledger, self.audit)
        x8_l1 = next(e for e in result["exposure"]
                     if e["lot"] == "X8" and e["line"] == "L1")
        # 设备级路线已确认接触，但记录仪对时仅区间，接触明细必须标 possible。
        self.assertEqual(x8_l1["recorder_contact"]["contacts"][0]["contact"],
                         "possible")

    def test_no_reading_never_used_as_baseline_point(self):
        baselines = self.tps.baseline.build_baselines(self.ledger)
        for base in baselines:
            self.assertTrue(all(isinstance(v, float) for v in base.points))
        # 无读数窗口与异常事件分别记录，互不冒充。
        result = self.tps.pipeline.run_shift(self.ledger, self.audit)
        self.assertTrue(result["no_signal_gaps"])
        self.assertFalse(any(
            p["quality"] == "no-signal"
            for e in result["events"] for p in e["points"]
        ))


if __name__ == "__main__":
    unittest.main()
