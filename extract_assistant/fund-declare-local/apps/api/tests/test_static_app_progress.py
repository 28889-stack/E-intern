import sys
import unittest
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class StaticAppProgressTest(unittest.TestCase):
    def test_analysis_progress_does_not_stall_at_78_or_move_backward(self):
        app_js = (API_ROOT / "app/static/app.js").read_text(encoding="utf-8")

        self.assertNotIn(
            'beginAnalysisProgress("读取材料与识别内容", 16, 78)',
            app_js,
        )
        self.assertIn("function advanceAnalysisProgress", app_js)
        self.assertNotIn('setAnalysisProgress(72, "智能抽取中")', app_js)

    def test_assistant_fallback_has_business_rule_answers(self):
        app_js = (API_ROOT / "app/static/app.js").read_text(encoding="utf-8")

        for phrase in [
            "基金从业人员证券投资管理指引",
            "利害关系人",
            "3 个月",
            "无账户信息是独立证明事项",
            "银行转证券、证券转银行、利息归本",
        ]:
            self.assertIn(phrase, app_js)

    def test_review_page_renders_business_tables_in_requested_order_with_descriptions(self):
        app_js = (API_ROOT / "app/static/app.js").read_text(encoding="utf-8")

        identity_index = app_js.index('renderIdentityTable(data["身份信息"]')
        holding_index = app_js.index('renderEditableTable("持仓"')
        final_index = app_js.index('renderEditableTable("最终申报表"')
        full_index = app_js.index('renderEditableTable("完整表"')

        self.assertLess(identity_index, holding_index)
        self.assertLess(holding_index, final_index)
        self.assertLess(final_index, full_index)
        self.assertIn("对持仓造成影响的变动类型，如交易、打新等，可直接申报。", app_js)
        self.assertIn(
            "完整表记录证券/基金相关交易及权益事件，剔除账户利息、银证转账等纯资金流水。",
            app_js,
        )


if __name__ == "__main__":
    unittest.main()
