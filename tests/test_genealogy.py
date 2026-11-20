"""返工谱系：拆分守恒、混装失源、签认卡边界与抽检解除。"""
import unittest

from _support import build_result, load_data, load_package


class GenealogyTests(unittest.TestCase):
    def setUp(self):
        self.tps = load_package()
        self.audit = load_data("rework_census.json")
        self.stock = self.tps.genealogy.replay(self.audit)

    def test_quantity_conservation(self):
        total = sum(c.qty for c in self.stock.values())
        self.assertEqual(total, sum(self.audit["initial_counts"].values()))

    def test_split_keeps_origin(self):
        self.assertEqual(self.stock["B82"].origin, {"X8": 45})
        self.assertEqual(self.stock["B92"].origin, {"X9": 20})
        self.assertEqual(self.stock["B81"].qty, 3)

    def test_mixed_containers_lose_item_origin(self):
        for item in ("RW2", "RW3"):
            self.assertEqual(self.stock[item].origin, {})
            self.assertEqual(self.stock[item].origin_lost_qty,
                             self.stock[item].qty)

    def test_signed_trace_excludes_only_named_box_and_line(self):
        result = build_result()
        contact = {(c["item"], c["reason_line"]): c
                   for c in result["genealogy"]["contact"]}
        # B82 签认只走 L2：L1 可排除，L2 仍是接触。
        self.assertEqual(contact[("B82", "L1")]["status"], "excluded-contact")
        self.assertEqual(contact[("B82", "L2")]["status"], "confirmed-contact")
        # 结论不能外推到同批的另一只箱。
        self.assertNotEqual(contact[("B81", "L1")]["status"], "excluded-contact")

    def test_mixed_box_remains_possible_even_though_some_origin_excludable(self):
        result = build_result()
        contact = {(c["item"], c["reason_line"]): c
                   for c in result["genealogy"]["contact"]}
        self.assertEqual(contact[("RW2", "L2")]["status"], "possible-contact")

    def test_full_box_inspection_releases_one_reason_only(self):
        result = build_result()
        decisions = {d["inspection"]: d
                     for d in result["genealogy"]["inspection_decisions"]}
        self.assertTrue(decisions["I81"]["releases"])
        self.assertEqual(decisions["I81"]["reason_line"], "L1")
        # I82 只检 11/17 件且无逐件标识，不能解除。
        self.assertFalse(decisions["I82"]["releases"])
        self.assertIn("17", decisions["I82"]["reason"])

    def test_reworked_physical_items_never_return_to_original_lot(self):
        self.assertNotIn("RW2", self.audit["initial_counts"])
        # 原批号容器已被拆空，现存实物只在新箱里。
        self.assertNotIn("X8", self.stock)
        self.assertNotIn("X9", self.stock)

    def test_rework_release_does_not_clear_independent_other_hold(self):
        result = build_result()
        active = result["active_restrictions"].get("RW2", [])
        # L1 解除提案未签认前，以及 L2 独立理由，都不能因为一次抽检清空。
        lines = {o["line"] for o in active}
        self.assertIn("L2", lines)


if __name__ == "__main__":
    unittest.main()
