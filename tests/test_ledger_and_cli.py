"""台账不可变、补查方案与命令行输出测试。"""
import io
import json
import unittest
from contextlib import redirect_stdout

from _support import build_result, load_package


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.result = build_result()

    def test_orders_are_append_only_and_trace_references(self):
        ledger = self.result["ledger"]
        for order in ledger:
            self.assertTrue(order["reference_windows"] or order["kind"] == "release-proposal")
        ids = [o["order_id"] for o in ledger]
        self.assertEqual(len(ids), len(set(ids)))

    def test_proposed_orders_carry_confirmation_requirement(self):
        for order in self.result["ledger"]:
            if order["authority"] is None and order["kind"] == "hold":
                self.assertTrue(order["requires_confirmation"])
        # 已签认的开卡隔离单不允许被系统标记为待确认。
        for card_id in ("H1", "H2"):
            order = next(o for o in self.result["ledger"] if o["order_id"] == card_id)
            self.assertFalse(order["requires_confirmation"])
        # X9 建议单反映客观限制，但必须人工确认后才成为正式处置。
        x9 = self.result["active_restrictions"]["X9"]
        self.assertTrue(all(o["requires_confirmation"] for o in x9))

    def test_independent_reasons_count_separately(self):
        x8 = self.result["active_restrictions"]["X8"]
        self.assertEqual(len(x8), 2)

    def test_followup_checks_state_what_they_cannot_resolve(self):
        by_id = {c["id"]: c for c in self.result["followup_checks"]}
        self.assertTrue(any("不能替代" in t or "不能改变" in t
                            for t in by_id["F71"]["cannot_resolve"]))
        self.assertTrue(any("抽检" in t for t in by_id["F72"]["cannot_resolve"]))
        # F73 即使完成也不影响 RW3 的 L2 独立限制。
        self.assertTrue(any("L2" in t for t in by_id["F73"]["cannot_resolve"]))


class CliTests(unittest.TestCase):
    def test_report_json_is_serializable_and_complete(self):
        tps = load_package()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = tps.__main__.main(["report", "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        for key in ("baselines", "events", "exposure", "clock", "genealogy",
                    "ledger", "active_restrictions", "followup_checks"):
            self.assertIn(key, payload)

    def test_text_report_mentions_three_evidence_classes(self):
        tps = load_package()
        buf = io.StringIO()
        with redirect_stdout(buf):
            tps.__main__.main(["report"])
        text = buf.getvalue()
        self.assertIn("无读数", text)
        self.assertIn("不可判断", text)
        self.assertIn("持续偏移", text)

    def test_version_command(self):
        tps = load_package()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = tps.__main__.main(["version"])
        self.assertEqual(rc, 0)
        self.assertIn("0.1.0", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
