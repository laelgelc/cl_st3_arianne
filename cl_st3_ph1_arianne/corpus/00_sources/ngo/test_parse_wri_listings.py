import tempfile
import unittest
from pathlib import Path

from parse_wri_listings import build_manifest, parse_listing


class WriListingTests(unittest.TestCase):
    def test_saved_listing_examples(self):
        path = Path(__file__).parent / "wri_listings" / "wri-p10.html"
        records = parse_listing(path)
        self.assertEqual(len(records), 20)
        self.assertEqual(records[0]["Title"], "4 Things to Know About New Developments in Carbon Dioxide Removal")
        self.assertEqual(records[0]["Post Date"], "2023-04-10")
        self.assertEqual(records[0]["Post URL"], "https://www.wri.org/insights/emerging-carbon-removal-approaches")
        self.assertEqual(records[0]["Post Tags"], "carbon removal, Climate")
        self.assertEqual(records[1]["Post Tags"], "Equity & Governance, Climate Equity, Urban Development")
        self.assertEqual(records[0]["Listing Pages"], [10])
        self.assertIsNone(records[0]["Authors"])

    def test_deduplication_and_invalid_page(self):
        source = Path(__file__).parent / "wri_listings" / "wri-p10.html"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            html = source.read_text(encoding="utf-8")
            (path / "wri-p10.html").write_text(html, encoding="utf-8")
            (path / "wri-p11.html").write_text(html, encoding="utf-8")
            records = build_manifest(path)
            self.assertEqual(len(records), 20)
            self.assertEqual(records[0]["Listing Pages"], [10, 11])
            (path / "wri-p11.html").write_text("<html></html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No result cards"):
                build_manifest(path)


if __name__ == "__main__":
    unittest.main()