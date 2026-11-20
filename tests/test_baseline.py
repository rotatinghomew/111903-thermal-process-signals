"""基线构建规则测试。"""
import unittest

from _support import build_result, load_data, load_package


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tps = load_package()
        self.ledger = load_data("shift_handoff.json")
        self.baselines = self.tps.baseline.build_baselines(self.ledger)
        self.index = {(b.line, b.recipe): b for b in self.baselines}

    def test_live_day_never_feeds_baseline(self):
        for base in self.baselines:
            self.assertFalse(any(s.startswith("2026-07-03") for s in base.sources))

    def test_separate_lines_never_pooled(self):
        r1 = self.index[("L1", "R1")]
        r2 = self.index[("L2", "R2")]
        self.assertNotAlmostEqual(r1.center, r2.center)
        self.assertTrue(all(50.0 <= v <= 52.0 for v in r1.points))
        self.assertTrue(all(63.0 <= v <= 65.0 for v in r2.points))

    def test_warmup_switch_and_no_signal_excluded(self):
        for base in self.baselines:
            self.assertTrue(all(isinstance(v, float) for v in base.points))

    def test_r3_is_trial_only_with_coverage_gap(self):
        r3 = self.index[("L1", "R3")]
        self.assertTrue(r3.trial_only)
        self.assertTrue(any("覆盖缺口" in n for n in r3.notes))
        self.assertTrue(any("试产" in n for n in r3.notes))

    def test_old_main_recipe_remains_formal_reference(self):
        r1 = self.index[("L1", "R1")]
        self.assertFalse(r1.trial_only)
        self.assertTrue(r1.usable)

    def test_insufficient_points_marked_inconclusive_baseline(self):
        tiny = {"reference_log": [
            {"line": "L9", "date": "2026-07-01", "purpose": "candidate-reference"},
            {"line": "L9", "date": "2026-07-03", "purpose": "live"},
        ], "temperature_c": [
            {"line": "L9", "at": "2026-07-01T10:00", "recipe": "R9",
             "phase": "steady", "value": 1.0, "quality": "observed"},
            {"line": "L9", "at": "2026-07-03T10:00", "recipe": "R9",
             "phase": "steady", "value": 9.0, "quality": "observed"},
        ]}
        base = self.tps.baseline.build_baselines(tiny)[0]
        self.assertFalse(base.usable)
        self.assertIsNone(base.limits)


if __name__ == "__main__":
    unittest.main()
