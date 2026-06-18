const statusText = document.getElementById("status-text");
const statusDot = document.getElementById("status-dot");
const llmHealthButton = document.getElementById("llm-health-button");
const llmHealthResult = document.getElementById("llm-health-result");
const createCaseForm = document.getElementById("create-case-form");
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
const debugFileForm = document.getElementById("debug-file-form");
const debugFileInput = document.getElementById("debug-file");
const debugFileResult = document.getElementById("debug-file-result");

function setStatus(kind, message) {
  statusText.textContent = message;
  statusDot.className = `status-dot status-dot--${kind}`;
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
    config.resultContainer.textContent = "请选择一个文件";
    return;
  }

  const formData = new FormData();
  formData.append("file", config.fileInput.files[0]);
  config.summaryContainer.replaceChildren();
  config.resultContainer.textContent = config.pendingText;

  try {
    const response = await fetch(
      `/api/cases/${encodeURIComponent(caseId)}/${config.endpointSuffix}`,
      {
        method: "POST",
        body: formData,
      },
    );
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "上传处理失败");
    }

    renderCaseFileSummary(data.file || {}, config.summaryContainer);
    extractFileIdInput.value = data.file?.file_id || "";
    filesListCaseIdInput.value = caseId;
    finalizeCaseIdInput.value = caseId;
    setDownloadExcelLink(caseId);
    updateRerunExtractButtonState();
    config.resultContainer.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    config.resultContainer.textContent = error.message || "上传处理失败";
  }
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
    setDownloadExcelLink(caseId);
    finalizeResult.textContent = JSON.stringify(data, null, 2);
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
  addSummaryItem("excel_path", data.excel_path, finalizeSummary);

  const summary = data.summary || {};
  addSummaryItem("complete_row_count", summary.complete_row_count, finalizeSummary);
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
    finalizeCaseIdInput.value.trim()
  );
}

function setDownloadExcelLink(caseId) {
  downloadExcelLink.href = `/api/cases/${encodeURIComponent(caseId)}/export/excel`;
  downloadExcelLink.classList.remove("is-disabled");
  downloadExcelLink.setAttribute("aria-disabled", "false");
}

function resetDownloadExcelLink() {
  downloadExcelLink.href = "#";
  downloadExcelLink.classList.add("is-disabled");
  downloadExcelLink.setAttribute("aria-disabled", "true");
}

function updateRerunExtractButtonState() {
  const disabled = !getActiveCaseId() || !extractFileIdInput.value.trim();
  viewExtractInputButton.disabled = disabled;
  rerunExtractButton.disabled = disabled;
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

window.addEventListener("DOMContentLoaded", checkApiHealth);
llmHealthButton.addEventListener("click", checkLlmHealth);
createCaseForm.addEventListener("submit", createCase);
identityUploadForm.addEventListener("submit", uploadIdentityFile);
accountUploadForm.addEventListener("submit", uploadAccountFile);
identityUploadCaseIdInput.addEventListener("input", updateRerunExtractButtonState);
accountUploadCaseIdInput.addEventListener("input", updateRerunExtractButtonState);
filesListCaseIdInput.addEventListener("input", updateRerunExtractButtonState);
finalizeCaseIdInput.addEventListener("input", () => {
  const caseId = finalizeCaseIdInput.value.trim();
  if (caseId) {
    setDownloadExcelLink(caseId);
  } else {
    resetDownloadExcelLink();
  }
  updateRerunExtractButtonState();
});
extractFileIdInput.addEventListener("input", updateRerunExtractButtonState);
viewExtractInputButton.addEventListener("click", viewExtractInput);
rerunExtractButton.addEventListener("click", rerunExtract);
caseFilesListForm.addEventListener("submit", listCaseFiles);
finalizeForm.addEventListener("submit", finalizeCase);
debugFileForm.addEventListener("submit", processDebugFile);
downloadExcelLink.addEventListener("click", (event) => {
  if (downloadExcelLink.getAttribute("aria-disabled") === "true") {
    event.preventDefault();
  }
});
