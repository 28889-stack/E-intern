const statusText = document.getElementById("status-text");
const statusDot = document.getElementById("status-dot");
const llmHealthButton = document.getElementById("llm-health-button");
const llmHealthResult = document.getElementById("llm-health-result");
const createCaseForm = document.getElementById("create-case-form");
const caseNameInput = document.getElementById("case-name");
const casePhoneInput = document.getElementById("case-phone");
const caseRelationLabelInput = document.getElementById("case-relation-label");
const createCaseResult = document.getElementById("create-case-result");
const caseFileForm = document.getElementById("case-file-form");
const caseUploadIdInput = document.getElementById("case-upload-id");
const caseFileInput = document.getElementById("case-file");
const caseFileSummary = document.getElementById("case-file-summary");
const caseFileResult = document.getElementById("case-file-result");
const extractFileIdInput = document.getElementById("extract-file-id");
const viewExtractInputButton = document.getElementById("view-extract-input-button");
const rerunExtractButton = document.getElementById("rerun-extract-button");
const caseFilesListForm = document.getElementById("case-files-list-form");
const filesListCaseIdInput = document.getElementById("files-list-case-id");
const caseFilesListResult = document.getElementById("case-files-list-result");
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
  const relationTypeLabel = caseRelationLabelInput.value.trim();

  if (!name || !phone || !relationTypeLabel) {
    createCaseResult.textContent = "请填写姓名、手机号和与员工关系";
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

    caseUploadIdInput.value = data.case_id;
    filesListCaseIdInput.value = data.case_id;
    createCaseResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    createCaseResult.textContent = error.message || "创建任务失败";
  }
}

async function uploadCaseFile(event) {
  event.preventDefault();

  const caseId = caseUploadIdInput.value.trim();
  if (!caseId) {
    caseFileResult.textContent = "请填写 case_id";
    return;
  }

  if (!caseFileInput.files.length) {
    caseFileResult.textContent = "请选择一个文件";
    return;
  }

  const formData = new FormData();
  formData.append("file", caseFileInput.files[0]);
  caseFileSummary.replaceChildren();
  caseFileResult.textContent = "正在上传并处理文件...";

  try {
    const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/files`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "上传处理失败");
    }

    renderCaseFileSummary(data.file || {});
    extractFileIdInput.value = data.file?.file_id || "";
    updateRerunExtractButtonState();
    caseFileResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    caseFileResult.textContent = error.message || "上传处理失败";
  }
}

async function viewExtractInput() {
  const caseId = caseUploadIdInput.value.trim();
  const fileId = extractFileIdInput.value.trim();

  if (!caseId || !fileId) {
    caseFileResult.textContent = "请填写 case_id 和 file_id";
    return;
  }

  caseFileResult.textContent = "正在读取抽取输入...";

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

    caseFileResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    caseFileResult.textContent = error.message || "读取抽取输入失败";
  }
}

async function rerunExtract() {
  const caseId = caseUploadIdInput.value.trim();
  const fileId = extractFileIdInput.value.trim();

  if (!caseId || !fileId) {
    caseFileResult.textContent = "请填写 case_id 和 file_id";
    return;
  }

  caseFileResult.textContent = "正在重跑抽取...";

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

    renderCaseFileSummary(data.file || {});
    caseFileResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    caseFileResult.textContent = error.message || "重跑抽取失败";
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

  try {
    const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/files`, {
      headers: {
        Accept: "application/json",
      },
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "查询文件列表失败");
    }

    caseFilesListResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    caseFilesListResult.textContent = error.message || "查询文件列表失败";
  }
}

function renderCaseFileSummary(file) {
  caseFileSummary.replaceChildren();
  addSummaryItem("file_id", file.file_id);
  addSummaryItem("route_type", file.route_type);
  addSummaryItem("content_type", file.content_type);
  addSummaryItem("process_status", file.process_status);
  addSummaryItem("extract_status", file.extract_status);
  addSummaryItem("manual_review_required", file.manual_review_required);
  addSummaryItem("review_reasons", (file.review_reasons || []).join("；"));
}

function addSummaryItem(label, value) {
  const item = document.createElement("div");
  item.textContent = `${label}: ${value ?? ""}`;
  caseFileSummary.appendChild(item);
}

function updateRerunExtractButtonState() {
  const disabled = !caseUploadIdInput.value.trim() || !extractFileIdInput.value.trim();
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
caseFileForm.addEventListener("submit", uploadCaseFile);
caseUploadIdInput.addEventListener("input", updateRerunExtractButtonState);
extractFileIdInput.addEventListener("input", updateRerunExtractButtonState);
viewExtractInputButton.addEventListener("click", viewExtractInput);
rerunExtractButton.addEventListener("click", rerunExtract);
caseFilesListForm.addEventListener("submit", listCaseFiles);
debugFileForm.addEventListener("submit", processDebugFile);
