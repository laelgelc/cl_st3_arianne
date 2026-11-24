import unittest
from datetime import datetime, timezone

from create_gettr_manifest import select


def millis(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


class ManifestTests(unittest.TestCase):
    def test_boundaries_and_word_count(self):
        text = 'Climate change is affecting our planet and its people.'
        for timestamp, expected in [(millis(2015, 11, 1), True),
                                    (millis(2022, 12, 1) - 1, True),
                                    (millis(2015, 11, 1) - 1, False),
                                    (millis(2022, 12, 1), False)]:
            result = select({'cdate': timestamp, 'txt': text}, set())
            self.assertEqual(result is not None, expected)
            if result:
                self.assertEqual(result['text'], text)
                self.assertEqual(result['word_count'], 9)

    def test_duplicates_missing_and_language(self):
        seen = set()
        record = {'cdate': millis(2021, 7, 1), 'txt': 'Climate change affects people across the world.'}
        self.assertIsNotNone(select(record, seen))
        self.assertIsNone(select(record, seen))
        for text in ['', None, 'The weather is changing.',
                     'Le changement climatique climate change menace notre planète et notre avenir.']:
            self.assertIsNone(select({'cdate': record['cdate'], 'txt': text}, set()))
        self.assertIsNone(select({'txt': record['txt']}, set()))


if __name__ == '__main__':
    unittest.main()