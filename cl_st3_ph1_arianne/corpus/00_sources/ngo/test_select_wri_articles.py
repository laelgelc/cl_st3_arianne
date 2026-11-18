import unittest
from pathlib import Path
import json

from select_wri_articles import END, SEED, SINGLE_PAGES, START, render_log, select


class WriSelectionTests(unittest.TestCase):
    def test_real_manifest(self):
        path = Path(__file__).parent / "wri_list.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        selected = select(records)
        self.assertEqual(selected, select(list(reversed(records))))
        self.assertEqual(len(selected), 67)
        self.assertEqual(len({record["Post URL"] for _, _, record in selected}), 67)
        for page in range(10, 47):
            self.assertEqual(sum(p == page for p, _, _ in selected), 1 if page in SINGLE_PAGES else 2)
        for _, _, record in selected:
            self.assertLessEqual(START.isoformat(), record["Post Date"])
            self.assertLessEqual(record["Post Date"], END.isoformat())
        self.assertEqual(render_log(selected, SEED).count("| wri-p"), 67)

    def test_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "Page 46"):
            select([])
        record = {"Post URL": "https://example.org", "Post Date": "2022-01-01", "Listing Pages": [46]}
        with self.assertRaisesRegex(ValueError, "duplicate URL"):
            select([record, record])
        with self.assertRaises(ValueError):
            select([{**record, "Post Date": "invalid"}])


if __name__ == "__main__":
    unittest.main()