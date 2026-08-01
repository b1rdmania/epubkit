import unittest

from lxml import etree

from metadata_handler import extract_metadata, format_filename


class FormatFilenameTests(unittest.TestCase):
    def test_presets(self):
        self.assertEqual(
            format_filename("The Book", "A. Writer", "original", original_filename="upload.epub"),
            "upload.epub",
        )
        self.assertEqual(
            format_filename("The Book", "A. Writer", "title-author"),
            "The Book - A. Writer.epub",
        )
        self.assertEqual(
            format_filename("The Book", "A. Writer", "author-title"),
            "A. Writer - The Book.epub",
        )
        self.assertEqual(
            format_filename("The Book", "A. Writer", "title"),
            "The Book.epub",
        )

    def test_custom_template_supports_metadata_and_original_name(self):
        self.assertEqual(
            format_filename(
                "The Book",
                "A/Writer",
                "custom",
                "{year} - {title} - {author} [{original}]",
                "source.epub",
                "2026",
            ),
            "2026 - The Book - A-Writer [source].epub",
        )

    def test_missing_metadata_and_unsafe_names_fall_back_safely(self):
        self.assertEqual(format_filename("", "", "title-author"), "optimized.epub")
        self.assertEqual(
            format_filename("", "", "original", original_filename="../../.epub"),
            "optimized.epub",
        )

    def test_custom_template_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "Unknown filename template field"):
            format_filename("Book", "Writer", "custom", "{series}")

    def test_custom_template_rejects_formatting_options(self):
        with self.assertRaisesRegex(ValueError, "do not support formatting options"):
            format_filename("Book", "Writer", "custom", "{title:>20}")

    def test_extract_metadata_includes_publication_year(self):
        opf = etree.fromstring(b"""
            <package xmlns="http://www.idpf.org/2007/opf">
                <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                    <dc:title>Book</dc:title>
                    <dc:date>2026-07-31</dc:date>
                </metadata>
            </package>
        """)
        self.assertEqual(extract_metadata(etree.ElementTree(opf))["year"], "2026")


if __name__ == "__main__":
    unittest.main()
