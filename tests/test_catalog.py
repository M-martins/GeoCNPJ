import unittest

from backend.catalog import COMPETENCE_RE, ESTABLISHMENT_RE, parse_propfind


XML = b'''<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">
<d:response><d:href>/public.php/webdav/2026-07/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
<d:response><d:href>/public.php/webdav/2026-07/Estabelecimentos0.zip</d:href><d:propstat><d:prop><d:getcontentlength>123</d:getcontentlength><d:getetag>"abc"</d:getetag><d:resourcetype/></d:prop></d:propstat></d:response>
</d:multistatus>'''


class CatalogTests(unittest.TestCase):
    def test_competence_validation(self):
        self.assertTrue(COMPETENCE_RE.fullmatch("2026-07"))
        self.assertFalse(COMPETENCE_RE.fullmatch("2026-13"))
        self.assertTrue(ESTABLISHMENT_RE.fullmatch("Estabelecimentos10.zip"))
        self.assertTrue(ESTABLISHMENT_RE.fullmatch("Estabelecimentos123.zip"))

    def test_propfind_parser_ignores_current_directory(self):
        items = parse_propfind(XML, "2026-07")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Estabelecimentos0.zip")
        self.assertEqual(items[0].size, 123)
        self.assertEqual(items[0].etag, "abc")
        self.assertEqual(items[0].as_dict()["kind"], "establishment")


if __name__ == "__main__": unittest.main()
