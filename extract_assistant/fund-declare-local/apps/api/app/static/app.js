const statusText = document.getElementById("status-text");
const statusDot = document.getElementById("status-dot");
const llmHealthButton = document.getElementById("llm-health-button");
const llmHealthProxyButton = document.getElementById("llm-health-proxy-button");
const llmHealthResult = document.getElementById("llm-health-result");
const chatbotToggle = document.getElementById("chatbot-toggle");
const cuteChatbot = document.querySelector(".cute-chatbot");
const chatbotPanel = document.getElementById("chatbot-panel");
const chatbotClose = document.getElementById("chatbot-close");
const chatbotReset = document.getElementById("chatbot-reset");
const chatbotHeader = document.querySelector(".chatbot-header");
const chatbotMessages = document.getElementById("chatbot-messages");
const chatbotForm = document.getElementById("chatbot-form");
const chatbotInput = document.getElementById("chatbot-input");
const createCaseForm = document.getElementById("create-case-form");
const createCaseEntryButton = document.getElementById("create-case-entry-button");
const caseNameInput = document.getElementById("case-name");
const casePhoneInput = document.getElementById("case-phone");
const caseRelationLabelInput = document.getElementById("case-relation-label");
const createCaseResult = document.getElementById("create-case-result");
const identityUploadForm = document.getElementById("identity-upload-form");
const identityUploadCaseIdInput = document.getElementById("identity-upload-case-id");
const identityFileInput = document.getElementById("identity-file");
const identityFileSummary = document.getElementById("identity-file-summary");
const identityFileResult = document.getElementById("identity-file-result");
const accountUploadForm = document.getElementById("account-upload-form");
const accountUploadCaseIdInput = document.getElementById("account-upload-case-id");
const accountFileInput = document.getElementById("account-file");
const accountFileSummary = document.getElementById("account-file-summary");
const accountFileResult = document.getElementById("account-file-result");
const extractFileIdInput = document.getElementById("extract-file-id");
const viewExtractInputButton = document.getElementById("view-extract-input-button");
const rerunExtractButton = document.getElementById("rerun-extract-button");
const caseFilesListForm = document.getElementById("case-files-list-form");
const filesListCaseIdInput = document.getElementById("files-list-case-id");
const filesListModuleSelect = document.getElementById("files-list-module");
const caseFilesListSummary = document.getElementById("case-files-list-summary");
const caseFilesListResult = document.getElementById("case-files-list-result");
const finalizeForm = document.getElementById("finalize-form");
const finalizeCaseIdInput = document.getElementById("finalize-case-id");
const finalizeSummary = document.getElementById("finalize-summary");
const finalizeResult = document.getElementById("finalize-result");
const downloadExcelLink = document.getElementById("download-excel-link");
const reviewCaseIdInput = document.getElementById("review-case-id");
const loadReviewButton = document.getElementById("load-review-button");
const saveReviewButton = document.getElementById("save-review-button");
const exportReviewedExcelButton = document.getElementById("export-reviewed-excel-button");
const reviewStatusSummary = document.getElementById("review-status-summary");
const reviewTables = document.getElementById("review-tables");
const reviewChecklist = document.getElementById("review-checklist");
const reviewFileIssues = document.getElementById("review-file-issues");
const reviewResult = document.getElementById("review-result");
const debugFileForm = document.getElementById("debug-file-form");
const debugFileInput = document.getElementById("debug-file");
const debugFileResult = document.getElementById("debug-file-result");

const reviewTableConfigs = {
  最终申报表: {
    title: "最终申报表",
    columns: ["账户类型", "证券账号", "证券代码", "证券名称", "变动类型", "日期", "成交数量", "成交单价", "收付金额"],
  },
  完整表: {
    title: "完整表",
    columns: ["账户类型", "证券账号", "证券代码", "证券名称", "变动类型", "起始日期", "终止日期", "日期", "成交数量", "成交单价", "收付金额", "数据来源"],
  },
  待复核问题: {
    title: "待复核问题",
    columns: ["序号", "待复核原因", "问题描述", "对应材料"],
  },
  持仓: {
    title: "持仓",
    columns: ["账户类型", "证券账号", "证券代码", "证券名称", "持有数量", "市值", "查询结果所属日期", "币种"],
  },
};
const identityReviewColumns = ["姓名", "电话", "关系类型", "身份证姓名", "身份证号码", "地址", "有效期起", "有效期止"];
const checklistReviewColumns = ["checklist条件", "状态", "说明"];
let currentReviewData = null;
let currentReviewPayload = null;
let chatbotDragState = null;
let chatbotIsSubmitting = false;
let chatbotMessagesState = [
  {
    role: "assistant",
    content: "你好，我是小易。可以问我材料准备、复核状态、待复核问题或 Excel 导出的事项。",
  },
];

function setStatus(kind, message) {
  statusText.textContent = message;
  statusDot.className = `status-dot status-dot--${kind}`;
}

function openCreateCaseForm() {
  createCaseForm.classList.remove("is-hidden");
  createCaseEntryButton?.setAttribute("aria-expanded", "true");
  caseNameInput.focus();
}

function toggleChatbot(forceOpen) {
  const shouldOpen =
    typeof forceOpen === "boolean"
      ? forceOpen
      : !cuteChatbot.classList.contains("is-open");
  cuteChatbot.classList.toggle("is-open", shouldOpen);
  chatbotPanel.setAttribute("aria-hidden", String(!shouldOpen));
  chatbotToggle.setAttribute("aria-expanded", String(shouldOpen));
  if (shouldOpen) {
    renderChatbotMessages();
    chatbotInput.focus();
  }
}

function startChatbotDrag(event) {
  const pointer = event.touches?.[0] || event;
  if (!pointer || !cuteChatbot) {
    return;
  }
  const interactiveTarget = event.target.closest("input, button, a, select, textarea");
  if (interactiveTarget && interactiveTarget !== chatbotToggle) {
    return;
  }

  const rect = cuteChatbot.getBoundingClientRect();
  chatbotDragState = {
    startY: pointer.clientY,
    startTop: rect.top,
    moved: false,
  };
  cuteChatbot.classList.add("is-dragging");
  document.addEventListener("mousemove", dragChatbot);
  document.addEventListener("mouseup", stopChatbotDrag);
  document.addEventListener("touchmove", dragChatbot, { passive: false });
  document.addEventListener("touchend", stopChatbotDrag);
}

function dragChatbot(event) {
  if (!chatbotDragState || !cuteChatbot) {
    return;
  }
  const pointer = event.touches?.[0] || event;
  if (!pointer) {
    return;
  }
  event.preventDefault();

  const deltaY = pointer.clientY - chatbotDragState.startY;
  const nextTop = clamp(
    chatbotDragState.startTop + deltaY,
    8,
    window.innerHeight - cuteChatbot.offsetHeight - 8,
  );

  chatbotDragState.moved =
    chatbotDragState.moved || Math.abs(deltaY) > 4;
  cuteChatbot.style.top = `${nextTop}px`;
}

function stopChatbotDrag() {
  if (!chatbotDragState || !cuteChatbot) {
    return;
  }
  if (chatbotDragState.moved) {
    chatbotToggle.dataset.justDragged = "true";
    window.setTimeout(() => {
      delete chatbotToggle.dataset.justDragged;
    }, 140);
  }
  chatbotDragState = null;
  cuteChatbot.classList.remove("is-dragging");
  document.removeEventListener("mousemove", dragChatbot);
  document.removeEventListener("mouseup", stopChatbotDrag);
  document.removeEventListener("touchmove", dragChatbot);
  document.removeEventListener("touchend", stopChatbotDrag);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function renderChatbotMessages() {
  chatbotMessages.replaceChildren();
  for (const message of chatbotMessagesState) {
    const item = document.createElement("article");
    item.className = `chatbot-message chatbot-message-${message.role}`;
    const label = document.createElement("span");
    label.className = "chatbot-message-label";
    label.textContent = message.role === "user" ? "你" : "小易";
    const content = document.createElement("p");
    content.textContent = message.content;
    item.append(label, content);
    chatbotMessages.appendChild(item);
  }
  chatbotMessages.scrollTop = chatbotMessages.scrollHeight;
}

function normalizeChatbotMessages(messages) {
  const normalized = (messages || [])
    .filter((message) => message && ["user", "assistant"].includes(message.role))
    .map((message) => ({
      role: message.role,
      content: String(message.content || ""),
    }))
    .filter((message) => message.content);

  return normalized.length
    ? normalized
    : [
        {
          role: "assistant",
          content: "你好，我是小易。可以问我材料准备、复核状态、待复核问题或 Excel 导出的事项。",
        },
      ];
}

function loadChatbotSession() {
  renderChatbotMessages();
}

function resetChatbotSession() {
  chatbotMessagesState = normalizeChatbotMessages([]);
  renderChatbotMessages();
}

function submitChatbotQuestion(question) {
  const content = question.trim();
  if (!content || chatbotIsSubmitting) {
    return;
  }

  chatbotIsSubmitting = true;
  chatbotInput.disabled = true;
  chatbotMessagesState.push({
    role: "user",
    content,
  });
  chatbotMessagesState.push({
    role: "assistant",
    content: buildChatbotReply(content),
  });
  renderChatbotMessages();
  chatbotIsSubmitting = false;
  chatbotInput.disabled = false;
  chatbotInput.focus();
}

function buildChatbotReply(question) {
  const text = question.toLowerCase();
  if (question.includes("证券账号") || question.includes("账号")) {
    return "如果材料里只有资金账号、没有证券账号，这类记录应进入人工复核，不能直接作为最终申报表的可核验记录。";
  }
  if (question.includes("材料") || question.includes("上传")) {
    return "身份材料走左侧“身份材料上传”，账户交易材料走“账户交易材料上传”。上传后可在右侧文件列表查看 module、content_type 和抽取状态。";
  }
  if (question.includes("excel") || question.includes("导出")) {
    return "当前流程是先生成 final_result，再加载并保存人工复核结果 reviewed_final_result，保存后才可以下载 Excel。";
  }
  if (question.includes("复核") || question.includes("checklist") || question.includes("待复核问题")) {
    return "复核区可以编辑最终申报表、完整表、持仓和身份信息；待复核问题用于定位材料和问题原因，checklist结果只读。";
  }
  if (text.includes("hello") || text.includes("hi")) {
    return "你好，我在这里帮你快速确认申报流程。可以问我上传、复核或导出 Excel 的问题。";
  }
  return "这个问题建议结合当前材料、复核表格和公司制度人工确认。本轮 UI 合入只保留前端流程提示，不接入新的问答后端。";
}

async function checkApiHealth() {
  try {
    const response = await fetch("/api/health", {
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error("Health check failed");
    }

    setStatus("ok", "后端服务正常");
  } catch {
    setStatus("error", "后端服务未连接");
  }
}

async function checkLlmHealth() {
  llmHealthResult.textContent = "正在检查 LLM...";

  try {
    const response = await fetch("/api/llm/health", {
      headers: {
        Accept: "application/json",
      },
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "LLM 健康检查失败");
    }

    llmHealthResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    llmHealthResult.textContent = error.message || "LLM 健康检查失败";
  }
}

async function createCase(event) {
  event.preventDefault();

  const name = caseNameInput.value.trim();
  const phone = casePhoneInput.value.trim();
  const relationTypeLabel = caseRelationLabelInput.value.trim() || "员工本人";

  if (!name || !phone) {
    createCaseResult.textContent = "请填写姓名和手机号";
    return;
  }

  createCaseResult.textContent = "正在创建任务...";

  try {
    const response = await fetch("/api/cases", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        name,
        phone,
        relation_type: "custom",
        relation_type_label: relationTypeLabel,
      }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "创建任务失败");
    }

    identityUploadCaseIdInput.value = data.case_id;
    accountUploadCaseIdInput.value = data.case_id;
    filesListCaseIdInput.value = data.case_id;
    finalizeCaseIdInput.value = data.case_id;
    reviewCaseIdInput.value = data.case_id;
    setDownloadExcelLink(data.case_id);
    updateRerunExtractButtonState();
    createCaseResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    createCaseResult.textContent = error.message || "创建任务失败";
  }
}

async function uploadIdentityFile(event) {
  return uploadCaseFileForModule(event, {
    caseIdInput: identityUploadCaseIdInput,
    fileInput: identityFileInput,
    summaryContainer: identityFileSummary,
    resultContainer: identityFileResult,
    endpointSuffix: "identity-info/files",
    pendingText: "正在上传并处理身份材料...",
  });
}

async function uploadAccountFile(event) {
  return uploadCaseFileForModule(event, {
    caseIdInput: accountUploadCaseIdInput,
    fileInput: accountFileInput,
    summaryContainer: accountFileSummary,
    resultContainer: accountFileResult,
    endpointSuffix: "account-info/files",
    pendingText: "正在上传并处理账户交易材料...",
  });
}

async function uploadCaseFileForModule(event, config) {
  event.preventDefault();

  const caseId = config.caseIdInput.value.trim();
  if (!caseId) {
    config.resultContainer.textContent = "请填写 case_id";
    return;
  }

  if (!config.fileInput.files.length) {
    config.resultContainer.textContent = "请选择一个或多个文件";
    return;
  }

  const files = Array.from(config.fileInput.files);
  const results = [];
  config.summaryContainer.replaceChildren();
  config.resultContainer.textContent = `${config.pendingText}（0/${files.length}）`;

  for (const [index, file] of files.entries()) {
    config.resultContainer.textContent = `${config.pendingText}（${index + 1}/${files.length}：${file.name}）`;
    try {
      const data = await uploadSingleCaseFile(caseId, config.endpointSuffix, file);
      results.push({
        ok: true,
        file_name: file.name,
        data,
      });
    } catch (error) {
      results.push({
        ok: false,
        file_name: file.name,
        error: error.message || "上传处理失败",
      });
    }
    renderCaseFileSummaries(results, config.summaryContainer);
  }

  const successfulResults = results.filter((result) => result.ok);
  const lastSuccessfulFile = successfulResults[successfulResults.length - 1]?.data?.file;
  if (lastSuccessfulFile?.file_id) {
    extractFileIdInput.value = lastSuccessfulFile.file_id;
  }
  if (successfulResults.length) {
    filesListCaseIdInput.value = caseId;
    finalizeCaseIdInput.value = caseId;
    reviewCaseIdInput.value = caseId;
    setDownloadExcelLink(caseId);
  }
  updateRerunExtractButtonState();
  config.resultContainer.textContent = JSON.stringify(
    {
      case_id: caseId,
      selected_count: files.length,
      uploaded_count: successfulResults.length,
      failed_count: results.length - successfulResults.length,
      results,
    },
    null,
    2,
  );
}

async function uploadSingleCaseFile(caseId, endpointSuffix, file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(
    `/api/cases/${encodeURIComponent(caseId)}/${endpointSuffix}`,
    {
      method: "POST",
      body: formData,
    },
  );
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || `${file.name} 上传处理失败`);
  }

  return data;
}

async function viewExtractInput() {
  const caseId = getActiveCaseId();
  const fileId = extractFileIdInput.value.trim();

  if (!caseId || !fileId) {
    accountFileResult.textContent = "请填写 case_id 和 file_id";
    return;
  }

  accountFileResult.textContent = "正在读取抽取输入...";

  try {
    const response = await fetch(
      `/api/cases/${encodeURIComponent(caseId)}/files/${encodeURIComponent(fileId)}/extract-input`,
      {
        headers: {
          Accept: "application/json",
        },
      },
    );
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "读取抽取输入失败");
    }

    accountFileResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    accountFileResult.textContent = error.message || "读取抽取输入失败";
  }
}

async function rerunExtract() {
  const caseId = getActiveCaseId();
  const fileId = extractFileIdInput.value.trim();

  if (!caseId || !fileId) {
    accountFileResult.textContent = "请填写 case_id 和 file_id";
    return;
  }

  accountFileResult.textContent = "正在重跑抽取...";

  try {
    const response = await fetch(
      `/api/cases/${encodeURIComponent(caseId)}/files/${encodeURIComponent(fileId)}/extract`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      },
    );
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "重跑抽取失败");
    }

    renderCaseFileSummary(data.file || {}, accountFileSummary);
    accountFileResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    accountFileResult.textContent = error.message || "重跑抽取失败";
  }
}

async function listCaseFiles(event) {
  event.preventDefault();

  const caseId = filesListCaseIdInput.value.trim();
  if (!caseId) {
    caseFilesListResult.textContent = "请填写 case_id";
    return;
  }

  caseFilesListResult.textContent = "正在查询文件列表...";
  caseFilesListSummary.replaceChildren();

  try {
    const module = filesListModuleSelect.value;
    const query = module ? `?module=${encodeURIComponent(module)}` : "";
    const response = await fetch(
      `/api/cases/${encodeURIComponent(caseId)}/files${query}`,
      {
        headers: {
          Accept: "application/json",
        },
      },
    );
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "查询文件列表失败");
    }

    renderCaseFilesList(data);
    caseFilesListResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    caseFilesListResult.textContent = error.message || "查询文件列表失败";
  }
}

async function finalizeCase(event) {
  event.preventDefault();

  const caseId = finalizeCaseIdInput.value.trim();
  if (!caseId) {
    finalizeResult.textContent = "请填写 case_id";
    return;
  }

  finalizeSummary.replaceChildren();
  resetDownloadExcelLink();
  finalizeResult.textContent = "正在生成最终产物...";

  try {
    const response = await fetch(
      `/api/cases/${encodeURIComponent(caseId)}/finalize`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      },
    );
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "生成最终产物失败");
    }

    renderFinalizeSummary(data);
    reviewCaseIdInput.value = caseId;
    currentReviewData = null;
    currentReviewPayload = null;
    saveReviewButton.disabled = true;
    exportReviewedExcelButton.disabled = true;
    resetDownloadExcelLink();
    finalizeResult.textContent = JSON.stringify(data, null, 2);
    await loadReviewData();
  } catch (error) {
    finalizeResult.textContent = error.message || "生成最终产物失败";
  }
}

function renderCaseFileSummary(file, container) {
  container.replaceChildren();
  addSummaryItem("file_id", file.file_id, container);
  addSummaryItem("route_type", file.route_type, container);
  addSummaryItem("module", file.module, container);
  addSummaryItem("content_type", file.content_type, container);
  addSummaryItem("process_status", file.process_status, container);
  addSummaryItem("extract_status", file.extract_status, container);
  addSummaryItem("manual_review_required", file.manual_review_required, container);
  addSummaryItem("review_reasons", (file.review_reasons || []).join("；"), container);
}

function renderCaseFileSummaries(results, container) {
  container.replaceChildren();
  const successfulResults = results.filter((result) => result.ok);
  addSummaryItem("selected_count", results.length, container);
  addSummaryItem("uploaded_count", successfulResults.length, container);
  addSummaryItem("failed_count", results.length - successfulResults.length, container);

  for (const result of results) {
    const item = document.createElement("div");
    item.className = `upload-summary-item${result.ok ? "" : " is-error"}`;
    if (!result.ok) {
      item.textContent = `${result.file_name}: ${result.error}`;
      container.appendChild(item);
      continue;
    }

    const file = result.data?.file || {};
    item.textContent = [
      `file_name=${result.file_name}`,
      `file_id=${file.file_id || ""}`,
      `module=${file.module || ""}`,
      `content_type=${file.content_type || ""}`,
      `process_status=${file.process_status || ""}`,
      `extract_status=${file.extract_status || ""}`,
      `manual_review_required=${file.manual_review_required ?? ""}`,
      `review_reasons=${(file.review_reasons || []).join("；")}`,
    ].join("; ");
    container.appendChild(item);
  }
}

function renderCaseFilesList(data) {
  caseFilesListSummary.replaceChildren();
  const summary = data.summary || {};
  addSummaryItem(
    "identity_info_file_count",
    summary.identity_info_file_count,
    caseFilesListSummary,
  );
  addSummaryItem(
    "account_info_file_count",
    summary.account_info_file_count,
    caseFilesListSummary,
  );

  const files = data.files || [];
  if (!files.length) {
    addSummaryItem("files", "无匹配文件", caseFilesListSummary);
    return;
  }

  for (const file of files) {
    addSummaryItem(
      `${file.file_no || ""} ${file.file_id || "file"}`.trim(),
      [
        `original_file_name=${file.original_file_name || ""}`,
        `module=${file.module || ""}`,
        `content_type=${file.content_type || ""}`,
        `route_type=${file.route_type || ""}`,
        `process_status=${file.process_status || ""}`,
        `extract_status=${file.extract_status || ""}`,
        `manual_review_required=${file.manual_review_required ?? ""}`,
        `review_reasons=${(file.review_reasons || []).join("；")}`,
      ].join("; "),
      caseFilesListSummary,
    );
  }
}

function renderFinalizeSummary(data) {
  finalizeSummary.replaceChildren();
  addSummaryItem("final_result_path", data.final_result_path, finalizeSummary);
  addSummaryItem("message", data.message, finalizeSummary);
  addSummaryItem(
    "excel_export_allowed",
    data.review_status?.excel_export_allowed,
    finalizeSummary,
  );

  const summary = data.summary || {};
  addSummaryItem("complete_row_count", summary.complete_row_count, finalizeSummary);
  addSummaryItem("file_issue_count", summary.file_issue_count, finalizeSummary);
  addSummaryItem(
    "final_declaration_row_count",
    summary.final_declaration_row_count,
    finalizeSummary,
  );
  addSummaryItem("manual_review_required", summary.manual_review_required, finalizeSummary);
}

function addSummaryItem(label, value, container) {
  const item = document.createElement("div");
  item.textContent = `${label}: ${value ?? ""}`;
  container.appendChild(item);
}

function getActiveCaseId() {
  return (
    accountUploadCaseIdInput.value.trim() ||
    identityUploadCaseIdInput.value.trim() ||
    filesListCaseIdInput.value.trim() ||
    finalizeCaseIdInput.value.trim() ||
    reviewCaseIdInput.value.trim()
  );
}

function setDownloadExcelLink(caseId, enabled = false) {
  downloadExcelLink.href = `/api/cases/${encodeURIComponent(caseId)}/export/excel`;
  if (enabled) {
    downloadExcelLink.textContent = "下载 Excel";
    downloadExcelLink.classList.remove("is-disabled");
    downloadExcelLink.setAttribute("aria-disabled", "false");
  } else {
    downloadExcelLink.textContent = "下载 Excel（请先保存人工复核结果）";
    downloadExcelLink.classList.add("is-disabled");
    downloadExcelLink.setAttribute("aria-disabled", "true");
  }
}

function resetDownloadExcelLink() {
  downloadExcelLink.href = "#";
  downloadExcelLink.textContent = "下载 Excel（请先保存人工复核结果）";
  downloadExcelLink.classList.add("is-disabled");
  downloadExcelLink.setAttribute("aria-disabled", "true");
}

function updateRerunExtractButtonState() {
  const disabled = !getActiveCaseId() || !extractFileIdInput.value.trim();
  viewExtractInputButton.disabled = disabled;
  rerunExtractButton.disabled = disabled;
}

function initFilePickerLabels() {
  for (const input of document.querySelectorAll(".file-picker input[type='file']")) {
    input.addEventListener("change", () => {
      const labelText = input.closest(".file-picker")?.querySelector("span");
      if (!labelText) {
        return;
      }

      labelText.textContent = input.files.length
        ? input.files[0].name
        : "选择文件";
    });
  }
}

async function loadReviewData() {
  const caseId = reviewCaseIdInput.value.trim() || getActiveCaseId();
  if (!caseId) {
    reviewResult.textContent = "请填写 case_id";
    return;
  }

  reviewCaseIdInput.value = caseId;
  reviewResult.textContent = "正在加载复核数据...";
  reviewStatusSummary.replaceChildren();
  reviewTables.replaceChildren();
  reviewChecklist.replaceChildren();
  reviewFileIssues.replaceChildren();

  try {
    const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/review`, {
      headers: {
        Accept: "application/json",
      },
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "加载复核数据失败");
    }

    currentReviewData = payload.data || {};
    currentReviewPayload = payload;
    renderReviewStatus(payload.review_status || {});
    renderReviewData(currentReviewData, payload);
    saveReviewButton.disabled = false;
    exportReviewedExcelButton.disabled = payload.review_status?.excel_export_allowed !== true;
    setDownloadExcelLink(caseId, payload.review_status?.excel_export_allowed === true);
    reviewResult.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    const message = error.message || "加载复核数据失败";
    reviewResult.textContent = message.includes("final_result.json 不存在")
      ? "final_result.json 不存在，请先点击右侧“生成 final_result”，生成成功后再加载复核数据。"
      : message;
    saveReviewButton.disabled = true;
    exportReviewedExcelButton.disabled = true;
    currentReviewPayload = null;
    resetDownloadExcelLink();
  }
}

async function saveReviewData() {
  const caseId = reviewCaseIdInput.value.trim() || getActiveCaseId();
  if (!caseId) {
    reviewResult.textContent = "请填写 case_id";
    return;
  }

  const data = collectReviewData();
  reviewResult.textContent = "正在保存复核结果...";

  try {
    const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/review`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(data),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "保存复核结果失败");
    }

    currentReviewData = data.review_data;
    if (currentReviewPayload?.review_status) {
      currentReviewPayload.review_status = payload.review_status || {};
    }
    renderReviewStatus(payload.review_status || {});
    exportReviewedExcelButton.disabled = false;
    setDownloadExcelLink(caseId, true);
    reviewResult.textContent = `复核结果已保存，可以导出 Excel\n${JSON.stringify(payload, null, 2)}`;
  } catch (error) {
    reviewResult.textContent = error.message || "保存复核结果失败";
  }
}

async function exportReviewedExcel() {
  const caseId = reviewCaseIdInput.value.trim() || getActiveCaseId();
  if (!caseId) {
    reviewResult.textContent = "请填写 case_id";
    return;
  }

  reviewResult.textContent = "正在导出 Excel...";

  try {
    const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/export/excel`);
    if (!response.ok) {
      let message = "导出 Excel 失败";
      try {
        const payload = await response.json();
        message = payload.detail || message;
      } catch {
        // Keep default message for non-JSON errors.
      }
      if (response.status === 409) {
        message = "请先保存人工复核结果，再导出 Excel";
      }
      throw new Error(message);
    }

    const blob = await response.blob();
    downloadBlob(blob, `${caseId}_final.xlsx`);
    reviewResult.textContent = "Excel 已开始下载";
  } catch (error) {
    reviewResult.textContent = error.message || "导出 Excel 失败";
  }
}

function renderReviewStatus(status) {
  reviewStatusSummary.replaceChildren();
  addSummaryItem("review_saved", status.review_saved, reviewStatusSummary);
  addSummaryItem("review_saved_at", status.review_saved_at, reviewStatusSummary);
  addSummaryItem("excel_export_allowed", status.excel_export_allowed, reviewStatusSummary);
  addSummaryItem("review_source", status.review_source, reviewStatusSummary);
}

function renderReviewData(data, payload = currentReviewPayload) {
  reviewTables.replaceChildren();
  for (const [key, config] of Object.entries(reviewTableConfigs)) {
    renderEditableReviewTable(key, config.title, config.columns, getReviewRows(data, key));
  }
  renderIdentityReviewTable(data["身份信息"] || data.identity_info || {});
  renderChecklistTable(data["checklist结果"] || data.checklist_rows || []);
  renderFileIssueSummaries(payload || {});
}

function getReviewRows(data, key) {
  if (!data) {
    return [];
  }
  if (key === "待复核问题") {
    return data["待复核问题"] || data.review_issue_rows || [];
  }
  return data[key] || [];
}

function renderEditableReviewTable(key, title, columns, rows) {
  const section = document.createElement("section");
  section.className = "review-table-block";
  section.dataset.reviewKey = key;

  const heading = document.createElement("h3");
  heading.textContent = title;
  section.appendChild(heading);

  const actions = document.createElement("div");
  actions.className = "button-row";
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.textContent = "新增一行";
  addButton.addEventListener("click", () => addEditableRow(key, columns, {}));
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.textContent = "删除选中行";
  deleteButton.addEventListener("click", () => deleteSelectedRows(key));
  actions.append(addButton, deleteButton);
  section.appendChild(actions);

  const wrapper = document.createElement("div");
  wrapper.className = "review-table-wrapper";
  const table = document.createElement("table");
  table.className = "review-table";
  table.dataset.reviewKey = key;
  table.dataset.columns = JSON.stringify(columns);
  table.innerHTML = `<thead><tr><th>选择</th>${columns.map((column) => `<th>${column}</th>`).join("")}</tr></thead><tbody></tbody>`;
  wrapper.appendChild(table);
  section.appendChild(wrapper);
  reviewTables.appendChild(section);

  for (const row of rows) {
    addEditableRow(key, columns, row);
  }
}

function renderIdentityReviewTable(identityInfo) {
  const columns = [
    ...identityReviewColumns,
    ...Object.keys(identityInfo).filter(
      (column) => column !== "_meta" && !identityReviewColumns.includes(column),
    ),
  ];
  renderEditableReviewTable("身份信息", "身份信息", columns, [identityInfo]);
}

function renderChecklistTable(rows) {
  const section = document.createElement("section");
  section.className = "review-table-block";
  const heading = document.createElement("h3");
  heading.textContent = "法律 checklist 结果";
  section.appendChild(heading);

  const wrapper = document.createElement("div");
  wrapper.className = "review-table-wrapper";
  const table = document.createElement("table");
  table.className = "review-table";
  table.innerHTML = `<thead><tr>${checklistReviewColumns.map((column) => `<th>${column}</th>`).join("")}</tr></thead><tbody></tbody>`;
  const tbody = table.querySelector("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const column of checklistReviewColumns) {
      const td = document.createElement("td");
      td.textContent = row[column] || "";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  wrapper.appendChild(table);
  section.appendChild(wrapper);
  reviewChecklist.replaceChildren(section);
}

function renderFileIssueSummaries(payload) {
  reviewFileIssues.replaceChildren();
  const summaries = normalizeObjectArray(
    payload.file_issue_summaries || payload.trace?.file_issue_summaries,
  );
  const issues = normalizeObjectArray(payload.file_issues || payload.trace?.file_issues);

  if (!summaries.length && !issues.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "未发现文件级 OCR、解析、抽取或关键字段缺失问题。";
    reviewFileIssues.appendChild(empty);
    return;
  }

  const header = document.createElement("div");
  header.className = "file-issue-overview";
  header.append(
    createFileIssueMetric("归纳文件", summaries.length || issues.length),
    createFileIssueMetric("原始问题", issues.length),
  );
  reviewFileIssues.appendChild(header);

  const issueByFileId = new Map();
  for (const issue of issues) {
    const fileId = issue.file_id || "";
    if (fileId) {
      issueByFileId.set(fileId, issue);
    }
  }

  const cards = summaries.length
    ? summaries
    : issues.map((issue) => ({
        file_id: issue.file_id || "",
        file_no: issue.file_no || "",
        file_name: issue.file_name || "",
        status: issue.severity === "error" ? "异常" : "需人工复核",
        summary: (issue.evidence || []).join("；") || "该文件存在待核对问题。",
        issue_types: issue.issue_types || [],
        suggested_action: issue.suggested_action || "请核对该文件的处理和抽取结果。",
      }));

  for (const summary of cards) {
    reviewFileIssues.appendChild(renderFileIssueCard(summary, issueByFileId.get(summary.file_id)));
  }
}

function createFileIssueMetric(label, value) {
  const item = document.createElement("div");
  item.className = "file-issue-metric";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value ?? 0;
  item.append(labelNode, valueNode);
  return item;
}

function renderFileIssueCard(summary, rawIssue) {
  const card = document.createElement("article");
  const status = normalizeFileIssueStatus(summary.status || rawIssue?.severity);
  card.className = `file-issue-card file-issue-card--${status.className}`;

  const header = document.createElement("div");
  header.className = "file-issue-card-header";
  const title = document.createElement("strong");
  title.textContent = [summary.file_no ? `#${summary.file_no}` : "", summary.file_name || summary.file_id || "未知文件"]
    .filter(Boolean)
    .join(" ");
  const badge = document.createElement("span");
  badge.className = "file-issue-status";
  badge.textContent = status.label;
  header.append(title, badge);

  const meta = document.createElement("div");
  meta.className = "file-issue-meta";
  const metaParts = [
    summary.file_id ? `file_id：${summary.file_id}` : "",
    rawIssue?.content_type ? `content_type：${rawIssue.content_type}` : "",
    rawIssue?.route_type ? `route_type：${rawIssue.route_type}` : "",
  ].filter(Boolean);
  meta.textContent = metaParts.join("；");

  const description = document.createElement("p");
  description.textContent = summary.summary || "该文件存在待核对问题。";

  const tags = document.createElement("div");
  tags.className = "file-issue-tags";
  for (const issueType of normalizeArray(summary.issue_types || rawIssue?.issue_types)) {
    const tag = document.createElement("span");
    tag.textContent = fileIssueTypeLabel(issueType);
    tags.appendChild(tag);
  }

  const action = document.createElement("p");
  action.className = "file-issue-action";
  action.textContent = summary.suggested_action || rawIssue?.suggested_action || "请核对该文件的处理和抽取结果。";

  card.append(header);
  if (metaParts.length) {
    card.appendChild(meta);
  }
  card.append(description);
  if (tags.childElementCount) {
    card.appendChild(tags);
  }
  card.appendChild(action);
  return card;
}

function normalizeFileIssueStatus(status) {
  const text = String(status || "").trim();
  if (text === "error" || text === "异常") {
    return { label: "异常", className: "error" };
  }
  if (text === "normal" || text === "通过") {
    return { label: "通过", className: "ok" };
  }
  return { label: "需人工复核", className: "warning" };
}

function fileIssueTypeLabel(issueType) {
  const labels = {
    content_type_unknown: "文件类型未知",
    ocr_failed: "OCR 失败",
    ocr_low_confidence: "OCR 置信度低",
    file_parse_failed: "文件无法解析",
    extract_failed: "抽取失败",
    extract_partial_failed: "部分抽取失败",
    llm_request_failed: "LLM 请求失败",
    json_parse_failed: "JSON 解析失败",
    llm_output_truncated: "LLM 输出被截断",
    schema_invalid: "schema 不合法",
    missing_required_fields: "缺少必填字段",
    missing_date: "缺少日期",
    missing_securities_account: "缺少证券账号",
    missing_account_type: "缺少账户类型",
    missing_security_code: "缺少证券代码",
    missing_security_name: "缺少证券名称",
    many_pending_review_items: "待复核记录较多",
    pending_review_event: "存在待复核事件",
    pending_review_holding: "存在待复核持仓",
    unknown_event_type: "事件类型无法判断",
    conflict_between_sources: "来源字段冲突",
    file_review_reason: "文件处理提示",
  };
  return labels[issueType] || issueType;
}

function normalizeObjectArray(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : [];
}

function normalizeArray(value) {
  return Array.isArray(value) ? value.filter((item) => item !== null && item !== undefined) : [];
}

function addEditableRow(key, columns, row) {
  const table = reviewTables.querySelector(`table[data-review-key="${key}"]`);
  if (!table) {
    return;
  }

  const tbody = table.querySelector("tbody");
  const tr = document.createElement("tr");
  tr.dataset.meta = JSON.stringify(row._meta || {});
  tr.dataset.originalRow = JSON.stringify(row || {});

  const selectCell = document.createElement("td");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.setAttribute("aria-label", "选择行");
  selectCell.appendChild(checkbox);
  tr.appendChild(selectCell);

  for (const column of columns) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.type = "text";
    input.value = row[column] ?? "";
    input.dataset.column = column;
    td.appendChild(input);
    tr.appendChild(td);
  }
  tbody.appendChild(tr);
}

function deleteSelectedRows(key) {
  const table = reviewTables.querySelector(`table[data-review-key="${key}"]`);
  if (!table) {
    return;
  }

  const rows = [...table.querySelectorAll("tbody tr")];
  const selectedRows = rows.filter((row) => row.querySelector('input[type="checkbox"]')?.checked);
  const rowsToDelete = selectedRows.length ? selectedRows : rows.slice(-1);
  for (const row of rowsToDelete) {
    row.remove();
  }
}

function collectReviewData() {
  return {
    review_data: {
      最终申报表: collectReviewRows("最终申报表"),
      完整表: collectReviewRows("完整表"),
      待复核问题: collectReviewRows("待复核问题"),
      持仓: collectReviewRows("持仓"),
      身份信息: collectIdentityInfo(),
      checklist结果: currentReviewData?.["checklist结果"] || currentReviewData?.checklist_rows || [],
    },
  };
}

function collectReviewRows(key) {
  const table = reviewTables.querySelector(`table[data-review-key="${key}"]`);
  if (!table) {
    return [];
  }

  const columns = JSON.parse(table.dataset.columns || "[]");
  const rows = [];
  for (const tr of table.querySelectorAll("tbody tr")) {
    const row = parseJsonObject(tr.dataset.originalRow);
    let hasValue = false;
    for (const column of columns) {
      const value = tr.querySelector(`input[data-column="${column}"]`)?.value.trim() || "";
      row[column] = value;
      hasValue = hasValue || Boolean(value);
    }
    const meta = parseJsonObject(tr.dataset.meta);
    if (Object.keys(meta).length) {
      row._meta = meta;
    }
    if (hasValue || Object.keys(meta).length) {
      rows.push(row);
    }
  }
  return rows;
}

function collectIdentityInfo() {
  const rows = collectReviewRows("身份信息");
  return rows[0] || {};
}

function parseJsonObject(value) {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function processDebugFile(event) {
  event.preventDefault();

  if (!debugFileInput.files.length) {
    debugFileResult.textContent = "请选择一个文件";
    return;
  }

  const formData = new FormData();
  formData.append("file", debugFileInput.files[0]);
  debugFileResult.textContent = "正在处理文件...";

  try {
    const response = await fetch("/api/debug/process-file", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "文件处理失败");
    }

    debugFileResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    debugFileResult.textContent = error.message || "文件处理失败";
  }
}

window.addEventListener("DOMContentLoaded", () => {
  initFilePickerLabels();
  checkApiHealth();
  loadChatbotSession();
});
chatbotToggle.addEventListener("mousedown", startChatbotDrag);
chatbotToggle.addEventListener("touchstart", startChatbotDrag, { passive: true });
chatbotHeader.addEventListener("mousedown", startChatbotDrag);
chatbotHeader.addEventListener("touchstart", startChatbotDrag, { passive: true });
chatbotToggle.addEventListener("click", () => {
  if (chatbotToggle.dataset.justDragged === "true") {
    return;
  }
  toggleChatbot();
});
chatbotClose.addEventListener("click", () => toggleChatbot(false));
chatbotReset.addEventListener("click", resetChatbotSession);
chatbotForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitChatbotQuestion(chatbotInput.value);
  chatbotInput.value = "";
});
for (const promptButton of document.querySelectorAll("[data-chatbot-prompt]")) {
  promptButton.addEventListener("click", () => {
    const prompt = promptButton.getAttribute("data-chatbot-prompt") || "";
    toggleChatbot(true);
    submitChatbotQuestion(prompt);
  });
}
llmHealthButton.addEventListener("click", checkLlmHealth);
llmHealthProxyButton?.addEventListener("click", checkLlmHealth);
createCaseEntryButton?.addEventListener("click", openCreateCaseForm);
createCaseForm.addEventListener("submit", createCase);
identityUploadForm.addEventListener("submit", uploadIdentityFile);
accountUploadForm.addEventListener("submit", uploadAccountFile);
identityUploadCaseIdInput.addEventListener("input", updateRerunExtractButtonState);
accountUploadCaseIdInput.addEventListener("input", updateRerunExtractButtonState);
filesListCaseIdInput.addEventListener("input", updateRerunExtractButtonState);
finalizeCaseIdInput.addEventListener("input", () => {
  const caseId = finalizeCaseIdInput.value.trim();
  reviewCaseIdInput.value = caseId;
  if (caseId) {
    setDownloadExcelLink(caseId);
  } else {
    resetDownloadExcelLink();
  }
  updateRerunExtractButtonState();
});
reviewCaseIdInput.addEventListener("input", () => {
  const caseId = reviewCaseIdInput.value.trim();
  if (caseId) {
    setDownloadExcelLink(caseId);
  } else {
    resetDownloadExcelLink();
  }
});
extractFileIdInput.addEventListener("input", updateRerunExtractButtonState);
viewExtractInputButton.addEventListener("click", viewExtractInput);
rerunExtractButton.addEventListener("click", rerunExtract);
caseFilesListForm.addEventListener("submit", listCaseFiles);
finalizeForm.addEventListener("submit", finalizeCase);
loadReviewButton.addEventListener("click", loadReviewData);
saveReviewButton.addEventListener("click", saveReviewData);
exportReviewedExcelButton.addEventListener("click", exportReviewedExcel);
debugFileForm.addEventListener("submit", processDebugFile);
downloadExcelLink.addEventListener("click", (event) => {
  if (downloadExcelLink.getAttribute("aria-disabled") === "true") {
    event.preventDefault();
  }
});
