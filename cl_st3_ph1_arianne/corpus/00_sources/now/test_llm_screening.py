import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import llm_screening as screening


VALID = {
    "category": "CORE",
    "confidence": 0.9,
    "climate_role": "central",
    "main_topic": "climate",
    "climate_relevance": "direct",
    "reason": "relevant",
    "multi_article_or_snippet_issue": False,
    "recommended_for_main_corpus": True,
}


class ScreeningTests(unittest.TestCase):
    def test_validation(self):
        screening.validate_screening_response(screening.parse_llm_json_response("```json\n" + json.dumps(VALID) + "\n```"))
        for field, value in [("confidence", True), ("confidence", float("nan")),
                             ("climate_role", "other"), ("category", "OTHER"),
                             ("climate_relevance", None), ("recommended_for_main_corpus", 1)]:
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                screening.validate_screening_response({**VALID, field: value})
        with self.assertRaises(ValueError):
            screening.validate_screening_response({**VALID, "category": "EXCLUDE"})
        with self.assertRaises(ValueError):
            screening.validate_screening_response({k: v for k, v in VALID.items() if k != "climate_role"})

    def test_api_retry_never_sends_temperature(self):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ValueError("Unsupported parameter max_output_tokens")
            return SimpleNamespace(output_text=json.dumps(VALID), model="mock")

        response = screening.call_openai_with_retries(
            SimpleNamespace(responses=SimpleNamespace(create=create)), model="mock", prompt="text",
            temperature=0.7, max_output_tokens=500, max_retries=0, retry_backoff_seconds=0,
        )
        self.assertEqual(response[2:], (False, False))
        self.assertTrue(all("temperature" not in call for call in calls))
        self.assertNotIn("max_output_tokens", calls[-1])

    def test_workflow_resume_and_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "article.txt").write_text("article", encoding="utf-8")
            (root / "prompt.md").write_text("Screen <<<ARTICLE_TEXT>>>", encoding="utf-8")
            row = {"article_id": "1", "filepath": "article.txt", "group": "2021", "country_code": "us"}
            manifest = root / "manifest.ndjson"
            manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
            output = root / "output"
            argv = ["llm_screening.py", "--manifest", "manifest.ndjson", "--prompt", "prompt.md", "--output", "output"]
            calls = []

            def create(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(output_text=json.dumps(VALID), model="mock")

            client = SimpleNamespace(responses=SimpleNamespace(create=create))
            original_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(screening, "make_openai_client", return_value=client), patch.object(sys, "argv", argv):
                    self.assertEqual(screening.main(), 0)
                result_file = output / "screening_json/2021/us/1.json"
                original = result_file.read_bytes()
                result = json.loads(original)
                self.assertEqual(result["model"]["configured_model"], "gpt-6-luna")
                self.assertFalse(result["temperature_sent_to_api"])
                self.assertEqual(json.loads((output / "climate_now_screened.ndjson").read_text())["llm_screening"], VALID)
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(screening, "make_openai_client", return_value=client), patch.object(sys, "argv", argv + ["--resume"]):
                    self.assertEqual(screening.main(), 0)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(result_file.read_bytes(), original)
                    (root / "article.txt").write_text("changed", encoding="utf-8")
                    self.assertEqual(screening.main(), 1)
                    self.assertEqual(result_file.read_bytes(), original)
                manifest.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
                with patch.object(sys, "argv", argv + ["--dry-run"]):
                    self.assertEqual(screening.main(), 1)
            finally:
                os.chdir(original_cwd)

    def test_invalid_manifest_null_fields(self):
        config = SimpleNamespace(article_id_field="article_id", filepath_field="filepath")
        self.assertIsNotNone(screening.validate_manifest_row(config, {"article_id": None, "filepath": "x"}))
        self.assertIsNotNone(screening.validate_manifest_row(config, {"article_id": "x", "filepath": None}))
        self.assertEqual(screening.safe_path_part("..", "unknown"), "unknown")
        self.assertEqual(screening.safe_path_part(".", "unknown"), "unknown")


if __name__ == "__main__":
    unittest.main()