import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class FakePaddleOcrEngine:
    def __init__(self, result):
        self.result = result
        self.predict_inputs = []

    def predict(self, input):
        self.predict_inputs.append(input)
        return self.result


class LocalOcrClientTest(unittest.TestCase):
    def test_infer_uses_local_paddle_engine_and_preserves_page_results(self):
        from app.services.ocr_client import OcrClient, OCR_REQUEST_OPTIONS

        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            image_path.write_bytes(b"fake image bytes")
            engine = FakePaddleOcrEngine(
                [
                    {
                        "rec_texts": ["证券代码", "000001"],
                        "rec_scores": [0.98, 0.96],
                        "rec_boxes": [[10, 10, 80, 30], [10, 40, 90, 60]],
                    }
                ]
            )

            result = OcrClient(engine=engine).infer(image_path, file_type=1)

        self.assertEqual(engine.predict_inputs, [str(image_path)])
        self.assertEqual(result["ocr_status"], "success")
        self.assertEqual(result["request_options"], OCR_REQUEST_OPTIONS)
        self.assertEqual(result["raw_response"]["ocrResults"][0]["rec_texts"], ["证券代码", "000001"])
        self.assertEqual(result["page_results"][0]["text"], "证券代码\n000001")
        self.assertEqual(result["page_results"][0]["confidence_avg"], 0.97)
        self.assertEqual(
            result["page_results"][0]["blocks"][1],
            {"text": "000001", "confidence": 0.96, "bbox": [10, 40, 90, 60]},
        )

    def test_infer_returns_failed_result_when_local_paddle_raises(self):
        from app.services.ocr_client import OcrClient

        class BrokenEngine:
            def predict(self, input):
                raise RuntimeError("boom")

        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            image_path.write_bytes(b"fake image bytes")

            result = OcrClient(engine=BrokenEngine()).infer(image_path, file_type=1)

        self.assertEqual(result["ocr_status"], "failed")
        self.assertEqual(result["page_results"], [])
        self.assertTrue(result["manual_review_required"])
        self.assertIn("本地 PaddleOCR 调用失败：boom", result["review_reasons"][0])

    def test_infer_accepts_numpy_rec_boxes_from_paddle_result(self):
        import numpy as np

        from app.services.ocr_client import OcrClient

        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            image_path.write_bytes(b"fake image bytes")
            engine = FakePaddleOcrEngine(
                [
                    {
                        "rec_texts": ["000001"],
                        "rec_scores": [0.99],
                        "rec_boxes": np.array([[1, 2, 3, 4]]),
                    }
                ]
            )

            result = OcrClient(engine=engine).infer(image_path, file_type=1)

        self.assertEqual(result["ocr_status"], "success")
        self.assertEqual(result["page_results"][0]["blocks"][0]["bbox"], [1, 2, 3, 4])

    def test_infer_keeps_raw_response_json_serializable(self):
        from app.services.ocr_client import OcrClient

        class NonJsonObject:
            pass

        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            image_path.write_bytes(b"fake image bytes")
            engine = FakePaddleOcrEngine(
                [
                    {
                        "rec_texts": ["000001"],
                        "rec_scores": [0.99],
                        "rec_boxes": [[1, 2, 3, 4]],
                        "debug_object": NonJsonObject(),
                    }
                ]
            )

            result = OcrClient(engine=engine).infer(image_path, file_type=1)

        json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["ocr_status"], "success")
        self.assertIn("NonJsonObject", result["raw_response"]["ocrResults"][0]["debug_object"])


if __name__ == "__main__":
    unittest.main()
