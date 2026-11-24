import unittest

from report_gettr_duplicates import candidates, normalize


class DuplicateReportTests(unittest.TestCase):
    def test_normalization_and_repost(self):
        self.assertEqual(normalize('RT @User: Climate   change &amp; people https://example.com'),
                         'climate change & people')
        records = [{'text': 'Climate change is a serious problem for people.'},
                   {'text': 'RT @person: CLIMATE change is a serious problem for people. https://example.com'}]
        pair = list(candidates(records))[0]
        self.assertEqual((pair['left_row'], pair['right_row'], pair['similarity']), (1, 2, 1.0))
        self.assertEqual(pair['decision'], '')

    def test_short_and_unrelated_posts_are_not_reported(self):
        records = [{'text': 'Climate change is real'}, {'text': 'Climate change is real!'},
                   {'text': 'Climate change causes flooding in many coastal cities.'},
                   {'text': 'Climate change policies affect different economic sectors.'}]
        self.assertEqual(list(candidates(records)), [])

    def test_added_commentary_and_threshold(self):
        records = [{'text': 'Climate change is affecting many people around the world today.'},
                   {'text': 'Yes! Climate change is affecting many people around the world today.'}]
        self.assertEqual(len(list(candidates(records))), 1)
        self.assertEqual(len(list(candidates(records, threshold=1))), 0)


if __name__ == '__main__':
    unittest.main()