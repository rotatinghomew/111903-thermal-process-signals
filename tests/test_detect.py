"""异常检测：预期工况、无读数、孤立尖峰与持续偏移分档。"""
import unittest

from _support import load_data, load_package


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.tps = load_package()
        self.ledger = load_data("shift_handoff.json")
        baselines = self.tps.baseline.build_baselines(self.ledger)
        self.result = self.tps.detect.detect(self.ledger, baselines, "2026-07-03")

    def test_warmup_and_switch_listed_separately_not_alarms(self):
        phases = {(w["line"], w["phase"]) for w in self.result["expected_phase"]}
        self.assertIn(("L1", "switch"), phases)
        self.assertIn(("L2", "warm-up"), phases)
        for event in self.result["events"]:
            self.assertNotIn(event["kind"], ("switch", "warm-up"))

    def test_two_confirmed_sustained_shifts(self):
        kinds = {(e["line"], e["kind"]) for e in self.result["events"]}
        self.assertIn(("L1", "confirmed-shift"), kinds)
        self.assertIn(("L2", "confirmed-shift"), kinds)
        l2 = next(e for e in self.result["events"] if e["line"] == "L2")
        self.assertEqual(len(l2["points"]), 3)
        self.assertEqual(l2["begin"], "2026-07-03T10:16")
        self.assertEqual(l2["end"], "2026-07-03T10:22")

    def test_no_signal_gap_is_its_own_category(self):
        gap = self.result["no_signal_gaps"][0]
        self.assertEqual(gap["line"], "L2")
        self.assertEqual(gap["begin"], "2026-07-03T10:14")
        # 缺测不被当作事件点，也不用缺失数量充当风险。
        self.assertFalse(any(p["quality"] == "no-signal"
                             for e in self.result["events"] for p in e["points"]))

    def test_l1_shift_does_not_include_switch_window(self):
        l1 = next(e for e in self.result["events"] if e["line"] == "L1")
        self.assertGreaterEqual(l1["begin"], "2026-07-03T10:13")

    def test_isolated_spike_when_baseline_usable(self):
        ledger = {
            "reference_log": [
                {"line": "L9", "date": "2026-07-01", "purpose": "candidate-reference"},
                {"line": "L9", "date": "2026-07-03", "purpose": "live"},
            ],
            "temperature_c": [
                *[{"line": "L9", "at": f"2026-07-01T10:{m:02d}", "recipe": "R9",
                   "phase": "steady", "value": 10.0, "quality": "observed"}
                  for m in range(8)],
                {"line": "L9", "at": "2026-07-03T10:00", "recipe": "R9",
                 "phase": "steady", "value": 10.0, "quality": "observed"},
                {"line": "L9", "at": "2026-07-03T10:01", "recipe": "R9",
                 "phase": "steady", "value": 99.0, "quality": "observed"},
                {"line": "L9", "at": "2026-07-03T10:02", "recipe": "R9",
                 "phase": "steady", "value": 10.0, "quality": "observed"},
            ],
        }
        baselines = self.tps.baseline.build_baselines(ledger)
        out = self.tps.detect.detect(ledger, baselines, "2026-07-03")
        self.assertEqual(len(out["events"]), 1)
        self.assertEqual(out["events"][0]["kind"], "isolated-spike")


if __name__ == "__main__":
    unittest.main()
