from pathlib import Path
import re
import unittest


STATIC_APP = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


class FrontendReviewDirtyTest(unittest.TestCase):
    def test_review_edits_disable_export_until_saved_again(self):
        source = STATIC_APP.read_text(encoding="utf-8")

        self.assertIn("reviewDirty:", source)
        self.assertIn("function markReviewDirty()", source)
        self.assertRegex(
            source,
            re.compile(
                r"const allowed = state\.reviewStatus\?\.excel_export_allowed === true\s*&&\s*state\.reviewDirty !== true",
                re.MULTILINE,
            ),
        )
        self.assertIn('input.addEventListener("input", markReviewDirty)', source)
        self.assertRegex(
            source,
            re.compile(r"function addEditableRow\(key, columns, row, markDirty = true\)"),
        )
        self.assertIn("markReviewDirty();", source)

    def test_ocr_quality_issue_labels_are_business_readable(self):
        source = STATIC_APP.read_text(encoding="utf-8")

        self.assertIn('ocr_partial_failed: "部分页面 OCR 失败"', source)
        self.assertIn('suspected_occlusion: "材料存在遮挡或涂抹"', source)


if __name__ == "__main__":
    unittest.main()
