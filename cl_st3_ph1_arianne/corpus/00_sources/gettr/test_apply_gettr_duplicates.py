import unittest

from apply_gettr_duplicates import apply_decisions


class ApplyDuplicatesTests(unittest.TestCase):
    def test_overlapping_pairs_keep_first_and_unmatched(self):
        records = [{'_id': str(i), 'text': f'text {i}'} for i in range(5)]

        def pair(a, b):
            return {'left_row': a + 1, 'right_row': b + 1,
                    'left_id': records[a]['_id'], 'right_id': records[b]['_id'],
                    'left_text': records[a]['text'], 'right_text': records[b]['text']}

        selected, reviewed = apply_decisions(records, [pair(2, 3), pair(0, 2), pair(3, 4)])
        self.assertEqual([x['_id'] for x in selected], ['0', '1'])
        self.assertTrue(all(x['decision'] == 'remove duplicate' and x['notes'] == 'potential duplicate'
                            for x in reviewed))

    def test_rejects_stale_candidate(self):
        records = [{'_id': 'a', 'text': 'one'}, {'_id': 'b', 'text': 'two'}]
        pair = {'left_row': 1, 'right_row': 2, 'left_id': 'a', 'right_id': 'b',
                'left_text': 'changed', 'right_text': 'two'}
        with self.assertRaises(ValueError):
            apply_decisions(records, [pair])


if __name__ == '__main__':
    unittest.main()