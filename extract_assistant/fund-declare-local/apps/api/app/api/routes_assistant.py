from fastapi import APIRouter
from pydantic import BaseModel

from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


router = APIRouter(prefix="/api/assistant", tags=["assistant"])
ASSISTANT_PROMPT_NAME = "assistant_business_prompt.md"


class AssistantMessage(BaseModel):
    role: str
    content: str


class AssistantChatRequest(BaseModel):
    messages: list[AssistantMessage] = []
    case_id: str | None = None


@router.post("/chat")
def assistant_chat(request: AssistantChatRequest) -> dict:
    messages = _normalized_messages(request.messages)
    latest_question = _latest_user_question(messages)
    if not latest_question:
        return {
            "answer": "请先输入需要咨询的问题。",
            "source": "rule_fallback",
        }

    llm_answer = _try_llm_answer(messages, request.case_id)
    if llm_answer:
        return {
            "answer": llm_answer,
            "source": "llm",
        }

    return {
        "answer": _rule_fallback_answer(latest_question),
        "source": "rule_fallback",
    }


def _try_llm_answer(messages: list[dict], case_id: str | None) -> str:
    context_lines = [_load_assistant_prompt()]
    if case_id:
        context_lines.append("当前前端已有一个任务上下文，但不要向用户暴露任务编号。")

    conversation = "\n".join(
        f"{message['role']}: {message['content']}" for message in messages[-8:]
    )
    result = LLMClient().extract_json(
        "\n".join(context_lines),
        f"对话内容：\n{conversation}",
    )
    if result.get("extract_status") in {"llm_request_failed", "json_parse_failed", "failed"}:
        return ""
    answer = result.get("answer")
    return str(answer).strip() if answer else ""


def _load_assistant_prompt() -> str:
    try:
        return PromptLoader().load(ASSISTANT_PROMPT_NAME)
    except FileNotFoundError:
        return "\n".join(
            [
                "你是“问小易”，投资申报复核系统里的业务问答助手。",
                "你只回答证券投资申报、材料准备、人工复核、待复核清单、checklist 和 Excel 导出相关问题。",
                "不要输出接口路径、本地路径、traceback 或技术调试信息。",
                '请只输出 JSON，格式为 {"answer":"..."}。',
            ]
        )


def _normalized_messages(messages: list[AssistantMessage]) -> list[dict]:
    normalized = []
    for message in messages:
        role = message.role if message.role in {"user", "assistant"} else "user"
        content = message.content.strip()
        if content:
            normalized.append({"role": role, "content": content})
    return normalized


def _latest_user_question(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _rule_fallback_answer(question: str) -> str:
    text = question.lower()
    if "法规" in question or "指引" in question or "依据" in question:
        return "本系统的业务口径参考《基金从业人员证券投资管理指引（试行）》：从业人员本人、配偶、利害关系人应如实申报身份、证券账户、交易账户、交易记录和持仓情况；具体适用仍以公司证券投资管理制度和人工复核结论为准。"
    if "利害关系" in question or "配偶" in question or "父母" in question or "子女" in question:
        return "申报范围通常包括基金从业人员本人、配偶、利害关系人。承担主要抚养或赡养费用的父母、子女，以及实际控制账户、提供具体投资建议、可直接获取账户利益或作为账户资金实际持有人的人员或机构，通常需要重点关注。"
    if "3个月" in question or "三个月" in question or "持有期限" in question or "提前卖" in question:
        return "参考指引口径，基金从业人员本人、配偶、利害关系人持有证券的最短期限原则上不得低于 3 个月；特殊情况提前卖出，应按公司证券投资管理制度履行审批。"
    if "定期" in question or "对账单" in question or "交易流水" in question:
        return "定期报告通常需要覆盖证券投资交易记录和证券账户的证券资产持有情况，并提供证券经纪商出具的对账单或交易流水。系统里请上传账户交易材料，再在人工复核页确认交易、持仓和待复核清单。"
    if "无账户" in question or "未开户" in question or "没有开户" in question:
        return "无账户信息是独立证明事项，表示截至某个时间点没有证券账户或未查询到账户信息；它不同于无持仓、无交易。请重点确认姓名、截止日期和材料来源。"
    if "无持仓" in question or "未持仓" in question:
        return "无持仓表示有账户，但某个查询日没有证券持仓。复核时需要确认证券账号、账户类型和查询日期；缺少这些字段时应进入待复核清单。"
    if "无交易" in question or "没有交易" in question:
        return "无交易表示有账户，但某个期间没有交易记录。复核时需要确认证券账号、账户类型、起止日期和材料来源。"
    if "银行转证券" in question or "证券转银行" in question or "利息" in question or "资金流水" in question:
        return "银行转证券、证券转银行、利息归本等纯资金流水通常不是最终申报重点。本系统主要关注证券账户、持仓，以及买入、卖出、打新、送股等影响持仓或需要证明的事项。"
    if "证券账号" in question or "账号" in question:
        return "如果材料里没有证券账号，相关记录通常需要进入待复核清单。请在人工复核页核对账户类型、证券账号、日期和对应材料。"
    if "材料" in question or "上传" in question:
        return "先填写身份信息，再分别上传身份材料和账户交易材料。材料进入列表后，可以继续添加多份文件，全部准备好后再开始抽取及分析。"
    if "excel" in text or "导出" in question:
        return "Excel 需要先生成复核结果，再完成人工复核并保存。保存复核结果后，导出按钮才会启用。"
    if "复核" in question or "checklist" in text or "问题" in question:
        return "人工复核页可以修改最终申报表、完整表、持仓和身份信息；右侧展示 checklist 和文件级问题归纳，下方展示待复核清单。"
    if "交易" in question or "持仓" in question:
        return "没有交易、没有持仓或未开户也可能是一种有效结果，但仍要能确认账户、期间和材料来源。缺少这些关键信息时会提示人工复核。"
    return "这个问题需要结合材料和复核表格判断。你可以先完成上传和系统分析，再在人工复核页查看待复核清单与文件级问题归纳。"
