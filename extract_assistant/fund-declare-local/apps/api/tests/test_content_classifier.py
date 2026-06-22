import tempfile
import unittest
from pathlib import Path

from app.pipeline.content_classifier import classify_content
from app.services.local_store import save_json


class ContentClassifierTest(unittest.TestCase):
    def test_chinaclear_holding_change_doc_not_ambiguous_when_broker_mentioned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            save_json(
                output_dir / "raw_text.json",
                {
                    "full_text": (
                        "中国证券登记结算有限责任公司投资者证券持有变更信息（沪市）\n"
                        "持有人名称：张\n"
                        "结算参与人：广发证券股份有限公司\n"
                        "过户日期 证券代码 证券简称 权益类别"
                    )
                },
            )

            result = classify_content(
                "sample.pdf",
                output_dir,
                original_file_name="【脱敏】-兑息、分红-上交所证券持有变更信息-副本.pdf",
            )

        self.assertEqual(result["content_type"], "chinaclear")
        self.assertFalse(result["manual_review_required"])
        self.assertEqual(result["review_reasons"], [])


if __name__ == "__main__":
    unittest.main()
