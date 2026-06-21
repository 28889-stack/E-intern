from fastapi import APIRouter
from pydantic import BaseModel

from app.services.llm_client import LLMClient


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


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
    context_lines = [
        "你是“问小易”，投资申报复核系统里的业务助手。",
        "你只回答材料上传、系统分析、人工复核、待复核清单、checklist、Excel 导出相关问题。",
        "不要编造当前任务不存在的数据，不要输出接口路径、本地路径、traceback 或技术调试信息。",
        "如果问题涉及具体材料结论，提醒用户以人工复核表格和原始材料为准。",
        '请只输出 JSON，格式为 {"answer":"..."}。',
    ]
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
