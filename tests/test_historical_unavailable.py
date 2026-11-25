import json, tempfile, unittest
from pathlib import Path
import url_lifecycle

ROOT = Path(url_lifecycle.__file__).parent
REAL = json.loads((ROOT / 'url.lifecycle').read_text())


class HistoricalUnavailableTests(unittest.TestCase):
    def render(self, entry):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            policy = {'host': REAL['host'], 'site_name': REAL['site_name'], 'detail_prefix': 'p',
                      'captured_public_urls': [entry['canonical_url']], 'retained_references': [entry]}
            (root / 'url.lifecycle').write_text(json.dumps(policy))
            (root / 'data.json').write_text('{"items": []}')
            (root / 'sitemap.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>')
            url_lifecycle.render_retained(root)
            self.assertEqual(url_lifecycle.verify(root)['explicitly_retired'], [])
            return (root / 'p' / entry['slug'] / 'index.html').read_text()

    def test_unavailable_publisher_is_labelled_as_provenance_not_reviewed_docs(self):
        entry = next(e for e in REAL['retained_references'] if e.get('source_status') == 'historical_unavailable')
        body = self.render(entry)
        self.assertIn('Publisher availability checked', body)
        self.assertIn('Sources and provenance', body)
        self.assertNotIn('Primary documentation reviewed', body)
        self.assertIn('"@type": "CreativeWork"', body)

    def test_unknown_source_status_is_rejected(self):
        entry = dict(next(e for e in REAL['retained_references'] if e.get('source_status') == 'historical_unavailable'))
        entry['source_status'] = 'gone'
        with self.assertRaises(ValueError):
            self.render(entry)

    def test_available_references_keep_primary_documentation_label(self):
        entry = next(e for e in REAL['retained_references'] if 'source_status' not in e)
        self.assertIn('Primary documentation reviewed', self.render(entry))


if __name__ == '__main__':
    unittest.main()
