import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import select_now_files as selector


class SelectNowFilesTests(unittest.TestCase):
    def test_phrase_matching_and_output_structure(self):
        pattern = selector.build_term_pattern(selector.SEARCH_TERMS)
        self.assertTrue(pattern.search('CLIMATE CHANGE is happening'))
        self.assertFalse(pattern.search('climate changes or microclimate change'))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            source = root / 'input' / 'nested' / 'news.txt'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'Climate Change here\r\nno match\r\nCLIMATE CHANGE again\r\n')
            selector.filter_text_file(source, root / 'input', root / 'output', pattern, logging.getLogger('test'))
            self.assertEqual((root / 'output' / 'nested' / 'news.txt').read_bytes(),
                             b'Climate Change here\nCLIMATE CHANGE again\n')
            source.write_text('no matching text', encoding='utf-8')
            selector.filter_text_file(source, root / 'input', root / 'other', pattern, logging.getLogger('test'))
            self.assertFalse((root / 'other' / 'nested' / 'news.txt').exists())

    def test_rejects_output_inside_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            with patch('select_now_files.parse_args') as args, \
                    patch('select_now_files.configure_logging', return_value=logging.getLogger('test')):
                args.return_value.input = str(root)
                args.return_value.output = str(root / 'output')
                self.assertEqual(selector.main(), 1)
                self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()