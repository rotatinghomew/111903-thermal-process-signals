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

    def test_rework_material_references_and_recorder_segments_are_consistent(self):
        path = Path(__file__).parents[1] / 'data' / 'rework_census.json'
        audit = json.loads(path.read_text(encoding='utf-8'))
        segments = {row['id']: row for row in audit['segments']}
        for row in audit['sensor_readings'] + audit['anchors']:
            segment = segments[row['segment']]
            self.assertLessEqual(segment['first_local'], row['local'])
            self.assertLessEqual(row['local'], segment['last_local'])
        material = dict(audit['initial_counts'])
        for move in audit['material_moves']:
            self.assertEqual(sum(move['parents'].values()), sum(move['children'].values()))
            for parent, quantity in move['parents'].items():
                self.assertLessEqual(quantity, material[parent])
                material[parent] -= quantity
            self.assertFalse(set(move['children']) & material.keys())
            material.update(move['children'])
        for inspection in audit['rework_inspections']:
            self.assertLessEqual(inspection['qty'], material[inspection['item']])
        for trace in audit['item_trace']:
            self.assertLessEqual(trace['qty'], material[trace['container']])

if __name__ == "__main__":
    unittest.main()
