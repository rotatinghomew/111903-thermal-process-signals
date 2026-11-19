"""检查合成资料可读。"""
import json
from pathlib import Path
import unittest

class FixtureTest(unittest.TestCase):
    def test_sample_is_json_object(self):
        path = Path(__file__).parents[1] / "data" / "sample.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(value, dict)
        self.assertTrue(value)

    def test_shift_records_keep_original_and_corrected_route(self):
        path = Path(__file__).parents[1] / 'data' / 'shift_handoff.json'
        ledger = json.loads(path.read_text(encoding='utf-8'))
        paths = {row['id']: row for row in ledger['route_log']}
        correction = next(row for row in paths.values() if 'corrects' in row)
        original = paths[correction['corrects']]
        self.assertEqual(original['lot'], correction['lot'])
        self.assertNotEqual(original['station'], correction['station'])
        first, second = ledger['hold_cards']
        self.assertEqual(first['lot'], second['lot'])
        self.assertNotEqual(first['line'], second['line'])
        self.assertLess(second['issued'], correction['filed_at'])
        self.assertTrue(any(row['station'] == 'feed' and row['lot'] == original['lot'] for row in paths.values()))
        self.assertTrue(any(row['phase'] == 'steady' and row['recipe'] == 'R3' and row['at'] < correction['start'][:10]
                            for row in ledger['temperature_c']))
        self.assertTrue(any(row['quality'] == 'no-signal' and row['value'] is None
                            for row in ledger['temperature_c']))

if __name__ == "__main__":
    unittest.main()
