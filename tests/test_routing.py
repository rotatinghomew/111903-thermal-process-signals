"""改线路由、暴露三档与抽检解除规则。"""
import unittest

from _support import build_result, load_data, load_package


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tps = load_package()
        self.ledger = load_data("shift_handoff.json")
        self.result = build_result()
        self.exposure = {(e["lot"], e["line"]): e for e in self.result["exposure"]}

    def test_correction_replaces_original_card(self):
        routes = {(r["id"]): r for r in self.result["effective_routes"]}
        self.assertNotIn("P5", routes)
        p6 = routes["P6"]
        self.assertEqual(p6["station"], "L1")
        # start_slack_minutes=2 只放宽开始时刻。
        self.assertEqual(p6["begin"], "2026-07-03T10:11")
        self.assertEqual(p6["end"], "2026-07-03T10:19")

    def test_feed_station_never_judged_against_furnace_events(self):
        self.assertNotIn(("X8", "feed"), self.exposure)

    def test_lot_exposure_statuses(self):
        self.assertEqual(self.exposure[("X8", "L1")]["status"], "confirmed")
        self.assertEqual(self.exposure[("X8", "L2")]["status"], "confirmed")
        self.assertEqual(self.exposure[("X9", "L1")]["status"], "confirmed")
        # X9 改线后不再有 L2 有效区间。
        self.assertNotIn(("X9", "L2"), self.exposure)

    def test_x8_intersections_match_half_open_windows(self):
        x8_l2 = self.exposure[("X8", "L2")]
        hit = x8_l2["events"][0]["intersection"]
        self.assertEqual(hit, ["2026-07-03T10:17", "2026-07-03T10:20"])

    def test_inspection_releases_only_covered_reason(self):
        decision = next(
            d for d in self.result["release_decisions"]
            if d["lot"] == "X8" and d["line"] == "L1"
        )
        self.assertTrue(decision["releases"])
        # 同一张抽检不能解除另一条独立的 L2 理由。
        other = next(
            d for d in self.result["release_decisions"]
            if d["lot"] == "X8" and d["line"] == "L2"
        )
        self.assertFalse(other["releases"])

    def test_x8_still_restricted_by_independent_l2_hold(self):
        active = self.result["active_restrictions"]["X8"]
        self.assertEqual({o["line"] for o in active}, {"L1", "L2"})

    def test_original_hold_cards_remain_immutable(self):
        ids = [o["order_id"] for o in self.result["ledger"]]
        self.assertIn("H1", ids)
        h1 = next(o for o in self.result["ledger"] if o["order_id"] == "H1")
        self.assertEqual(h1["evidence_window"],
                         ["2026-07-03T10:13", "2026-07-03T10:18"])

    def test_reconfirmation_lists_rerouted_l2(self):
        items = {(i["lot"], i["line"]) for i in self.result["reconfirmation"]}
        self.assertIn(("X9", "L2"), items)

    def test_boundary_inspection_keeps_suspect_range(self):
        routes = self.tps.routing.effective_routes(self.ledger)
        baselines = self.tps.baseline.build_baselines(self.ledger)
        events = self.tps.detect.detect(self.ledger, baselines, "2026-07-03")["events"]
        exposure = self.tps.routing.lot_exposure(routes, events)
        # 抽检结束早于暴露交集结束一分钟，必须保留候疑并给出补测目标。
        narrow = {
            "id": "Ix", "line": "L1", "lot": "X8",
            "begin": "2026-07-03T10:13", "end": "2026-07-03T10:16",
            "method": "抽测", "measured": 20.0, "lower": 19, "upper": 22,
            "recorded": "2026-07-03T11:30",
        }
        decision = self.tps.routing.evaluate_release(narrow, "X8", "L1", exposure)
        self.assertFalse(decision["releases"])
        self.assertIn("E1", decision["uncovered_events"])
        self.assertTrue(decision["recommended_targets"])


if __name__ == "__main__":
    unittest.main()
