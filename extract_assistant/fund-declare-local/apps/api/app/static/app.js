const state = {
  caseId: "",
  files: [],
  reviewData: null,
  reviewStatus: null,
  reviewPayload: null,
  currentPage: 1,
  currentStep: "create",
  lastError: null,
  finalizePayload: null,
  debugLog: [],
  assistantMessages: [
    {
      role: "assistant",
      content: "你好，我是小易。可以问我材料准备、人工复核、待复核清单或 Excel 导出的事项。",
    },
  ],
  assistantSubmitting: false,
  assistantDrag: null,
  analysisProgressTimer: null,
  analysisProgressValue: 0,
  stagedUploadSeq: 0,
};

const steps = ["create", "upload", "analysis", "review"];
const analysisSteps = [
  "材料缓存完成",
  "文件读取中",
  "OCR / PDF 解析中",
  "材料内容识别中",
  "智能抽取中",
  "生成复核结果",
  "等待人工复核",
];

const editableTables = {
  最终申报表: ["账户类型", "证券账号", "证券代码", "证券名称", "变动类型", "日期", "成交数量", "成交单价", "收付金额"],
  完整表: ["账户类型", "证券账号", "证券代码", "证券名称", "变动类型", "起始日期", "终止日期", "日期", "成交数量", "成交单价", "收付金额", "数据来源"],
  持仓: ["账户类型", "证券账号", "证券代码", "证券名称", "持有数量", "市值", "查询结果所属日期", "币种"],
};

const identityColumns = ["姓名", "电话", "关系类型", "身份证姓名", "身份证号码", "地址", "有效期起", "有效期止"];
const checklistColumns = ["checklist条件", "状态", "说明"];
const problemColumns = ["序号", "待复核原因", "问题描述", "对应材料"];

const els = {
  statusText: document.getElementById("status-text"),
  statusIndicator: document.getElementById("status-indicator"),
  stepButtons: [...document.querySelectorAll(".process-step")],
  pagePanels: [...document.querySelectorAll(".page-panel")],
  createCaseForm: document.getElementById("create-case-form"),
  caseName: document.getElementById("case-name"),
  casePhone: document.getElementById("case-phone"),
  caseRelationLabel: document.getElementById("case-relation-label"),
  createMessage: document.getElementById("create-message"),
  identityUploadForm: document.getElementById("identity-upload-form"),
  identityFile: document.getElementById("identity-file"),
  identityUploadMessage: document.getElementById("identity-upload-message"),
  accountUploadForm: document.getElementById("account-upload-form"),
  accountFile: document.getElementById("account-file"),
  accountUploadMessage: document.getElementById("account-upload-message"),
  refreshFilesButton: document.getElementById("refresh-files-button"),
  materialsTable: document.getElementById("materials-table"),
  uploadReadyMessage: document.getElementById("upload-ready-message"),
  startAnalysisButton: document.getElementById("start-analysis-button"),
  analysisSteps: document.getElementById("analysis-steps"),
  analysisCurrentStep: document.getElementById("analysis-current-step"),
  analysisProgressText: document.getElementById("analysis-progress-text"),
  analysisProgressBar: document.getElementById("analysis-progress-bar"),
  analysisMessage: document.getElementById("analysis-message"),
  reviewSummary: document.getElementById("review-summary"),
  reviewTables: document.getElementById("review-tables"),
  checklistResults: document.getElementById("checklist-results"),
  problemList: document.getElementById("problem-list"),
  fileIssueList: document.getElementById("file-issue-list"),
  saveReviewButton: document.getElementById("save-review-button"),
  exportExcelButton: document.getElementById("export-excel-button"),
  exportMessage: document.getElementById("export-message"),
  llmHealthButton: document.getElementById("llm-health-button"),
  showStateButton: document.getElementById("show-state-button"),
  debugOutput: document.getElementById("debug-output"),
  assistantToggle: document.getElementById("assistant-toggle"),
  assistantPanel: document.getElementById("assistant-panel"),
  assistantClose: document.getElementById("assistant-close"),
  assistantReset: document.getElementById("assistant-reset"),
  assistantMessages: document.getElementById("assistant-messages"),
  assistantForm: document.getElementById("assistant-form"),
  assistantInput: document.getElementById("assistant-input"),
  assistantPrompts: [...document.querySelectorAll("[data-assistant-prompt]")],
};

function setServiceState(kind, message) {
  els.statusText.textContent = message;
  els.statusIndicator.className = `service-indicator is-${kind}`;
}

async function checkApiHealth() {
  try {
    const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error("health check failed");
    }
    setServiceState("ok", "服务已连接");
  } catch (error) {
    setServiceState("error", "服务未连接");
    logDebug("服务连接失败", error);
  }
}

function showStep(step) {
  if (!steps.includes(step)) {
    return;
  }
  state.currentStep = step;
  state.currentPage = steps.indexOf(step) + 1;
  document.body.dataset.step = step;

  for (const panel of els.pagePanels) {
    panel.classList.toggle("is-active", panel.id === `page-${step}`);
  }
  updateStepButtons();
}

function updateStepButtons() {
  const hasUploadedFiles = state.files.some((file) => !file.local_only && file.upload_state !== "failed");
  const enabled = {
    create: true,
    upload: Boolean(state.caseId),
    analysis: Boolean(state.caseId && hasUploadedFiles),
    review: Boolean(state.reviewData),
  };

  for (const button of els.stepButtons) {
    const step = button.dataset.step;
    button.disabled = !enabled[step];
    button.classList.toggle("is-active", state.currentStep === step);
    button.classList.toggle("is-complete", steps.indexOf(step) < steps.indexOf(state.currentStep));
  }
}

async function createCase(event) {
  event.preventDefault();
  clearNotice(els.createMessage);

  const name = els.caseName.value.trim();
  const phone = els.casePhone.value.trim();
  const relationTypeLabel = els.caseRelationLabel.value.trim() || "员工本人";
  if (!name || !phone) {
    showNotice(els.createMessage, "warning", "请填写姓名和电话。");
    return;
  }

  showNotice(els.createMessage, "info", "正在创建任务。");
  try {
    const payload = await requestJson("/api/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        name,
        phone,
        relation_type: "custom",
        relation_type_label: relationTypeLabel,
      }),
    });
    state.caseId = payload.case_id || payload.case?.case_id || "";
    state.files = [];
    state.reviewData = null;
    state.reviewStatus = null;
    state.reviewPayload = null;
    logDebug("创建任务返回", payload);
    showNotice(els.createMessage, "success", "任务已创建。请继续填写身份信息并上传材料。");
    renderMaterials();
    updateStepButtons();
    showStep("upload");
  } catch (error) {
    handleFriendlyError(error, els.createMessage, "任务创建失败，请检查填写信息后重试。");
  }
}

async function uploadIdentityFiles(event) {
  event.preventDefault();
  await uploadFiles("identity", els.identityFile, els.identityUploadMessage);
}

async function uploadAccountFiles(event) {
  event.preventDefault();
  await uploadFiles("account", els.accountFile, els.accountUploadMessage);
}

async function uploadFiles(kind, input, messageEl) {
  clearNotice(messageEl);
  if (!state.caseId) {
    showNotice(messageEl, "warning", "请先创建任务。");
    showStep("create");
    return;
  }
  const files = [...input.files];
  if (!files.length) {
    showNotice(messageEl, "warning", "请选择需要上传的材料。");
    return;
  }

  const endpoint = kind === "identity" ? "identity-info/files" : "account-info/files";
  const stagedFiles = stageUploadFiles(kind, files);
  renderMaterials();
  let successCount = 0;
  let failureCount = 0;
  for (const [index, file] of files.entries()) {
    const staged = stagedFiles[index];
    updateStagedFile(staged.local_id, {
      upload_state: "uploading",
      process_status: "uploading",
    });
    renderMaterials();
    showNotice(messageEl, "info", `正在加入缓存区 ${index + 1}/${files.length}：${file.name}`);
    try {
      const payload = await uploadSingleFile(endpoint, file);
      if (payload.file) {
        replaceStagedFile(staged.local_id, {
          ...payload.file,
          upload_state: "done",
        });
      } else {
        updateStagedFile(staged.local_id, {
          upload_state: "done",
          process_status: "uploaded",
        });
      }
      logDebug("材料上传返回", payload);
      successCount += 1;
    } catch (error) {
      failureCount += 1;
      updateStagedFile(staged.local_id, {
        upload_state: "failed",
        process_status: "failed",
        manual_review_required: true,
        review_reasons: ["材料上传失败，请重新上传或检查文件格式。"],
      });
      logDebug("材料上传失败", error);
    }
    renderMaterials();
  }
  input.value = "";
  await loadFiles({ silent: true });
  const resultText = failureCount
    ? `已加入缓存区 ${successCount} 份材料，${failureCount} 份材料上传失败，请重新上传或检查文件格式。`
    : `已加入缓存区 ${successCount} 份材料。`;
  showNotice(messageEl, failureCount ? "warning" : "success", resultText);
}

function stageUploadFiles(kind, files) {
  const module = kind === "identity" ? "identity_info" : "account_info";
  const contentType = kind === "identity" ? "identity" : "pending";
  const startIndex = state.files.length;
  const staged = files.map((file, index) => {
    state.stagedUploadSeq += 1;
    return {
      local_id: `local_${Date.now()}_${state.stagedUploadSeq}`,
      local_only: true,
      file_no: String(startIndex + index + 1).padStart(3, "0"),
      original_file_name: file.name,
      module,
      content_type: contentType,
      process_status: "queued",
      extract_status: null,
      upload_state: "queued",
      manual_review_required: false,
      review_reasons: [],
    };
  });
  state.files = [...state.files, ...staged];
  return staged;
}

function updateStagedFile(localId, patch) {
  state.files = state.files.map((file) =>
    file.local_id === localId ? { ...file, ...patch } : file,
  );
}

function replaceStagedFile(localId, serverFile) {
  state.files = state.files.map((file) =>
    file.local_id === localId ? serverFile : file,
  );
}

async function uploadSingleFile(endpoint, file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`/api/cases/${encodeURIComponent(state.caseId)}/${endpoint}`, {
    method: "POST",
    body: formData,
  });
  const payload = await safeJson(response);
  if (!response.ok) {
    throw makeRequestError(response, payload, "材料上传失败，请重新上传或检查文件格式。");
  }
  return payload;
}

async function loadFiles({ silent = false } = {}) {
  if (!state.caseId) {
    return;
  }
  try {
    const payload = await requestJson(`/api/cases/${encodeURIComponent(state.caseId)}/files`);
    const localRows = state.files.filter(
      (file) => file.local_only && ["queued", "uploading", "failed"].includes(file.upload_state),
    );
    state.files = [...(Array.isArray(payload.files) ? payload.files : []), ...localRows];
    logDebug("材料列表返回", payload);
    renderMaterials();
  } catch (error) {
    logDebug("材料列表读取失败", error);
    if (!silent) {
      showNotice(els.uploadReadyMessage, "warning", "材料列表读取失败，请稍后重试。");
    }
  }
}

function mergeFile(file) {
  const key = file.file_id || file.file_no || file.original_file_name;
  const next = state.files.filter((item) => (item.file_id || item.file_no || item.original_file_name) !== key);
  next.push(file);
  state.files = next;
}

function renderMaterials() {
  els.materialsTable.replaceChildren();
  updateStepButtons();
  const activeUploads = state.files.some((file) => file.local_only && ["queued", "uploading"].includes(file.upload_state));
  const uploadedFiles = state.files.filter((file) => !file.local_only && file.upload_state !== "failed");
  els.startAnalysisButton.disabled = !state.caseId || uploadedFiles.length === 0 || activeUploads;
  if (activeUploads) {
    els.uploadReadyMessage.textContent = "材料正在进入缓存区，完成后可以开始系统分析。";
  } else if (uploadedFiles.length) {
    els.uploadReadyMessage.textContent = "材料已进入缓存区，可以开始抽取及分析。";
  } else {
    els.uploadReadyMessage.textContent = "上传身份材料和账户交易材料后，可以开始系统分析。";
  }

  if (!state.files.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "缓存区还没有材料。";
    els.materialsTable.appendChild(empty);
    return;
  }

  const table = createTable(["材料编号", "文件名", "材料类型"]);
  const tbody = table.querySelector("tbody");
  for (const [index, file] of state.files.entries()) {
    const row = document.createElement("tr");
    appendCell(row, materialNo(file, index));
    appendCell(row, file.original_file_name || file.stored_file_name || "未命名材料");
    appendCell(row, contentTypeLabel(file.content_type, file.module));
    tbody.appendChild(row);
  }
  els.materialsTable.appendChild(table);
}

async function startAnalysis() {
  if (!state.caseId) {
    showStep("create");
    return;
  }
  const activeUploads = state.files.some((file) => file.local_only && ["queued", "uploading"].includes(file.upload_state));
  const uploadedFiles = state.files.filter((file) => !file.local_only && file.upload_state !== "failed");
  if (activeUploads) {
    showStep("upload");
    els.uploadReadyMessage.textContent = "材料仍在上传和读取中，请稍候。";
    return;
  }
  if (!uploadedFiles.length) {
    showStep("upload");
    return;
  }

  showStep("analysis");
  renderAnalysisSteps(0);
  setAnalysisProgress(8, "准备分析材料");
  showNotice(els.analysisMessage, "info", "系统正在读取材料并生成复核结果，请稍候。");

  try {
    renderAnalysisSteps(1);
    beginAnalysisProgress("读取材料与识别内容", 16, 78);
    const analyzePayload = await requestJson(`/api/cases/${encodeURIComponent(state.caseId)}/files/analyze`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    logDebug("批量分析材料返回", analyzePayload);
    if (Array.isArray(analyzePayload.files)) {
      state.files = analyzePayload.files;
      renderMaterials();
    }
    setAnalysisProgress(72, "智能抽取中");
    renderAnalysisSteps(4);
    renderAnalysisSteps(5);
    beginAnalysisProgress("生成复核结果", 72, 94);
    const finalizePayload = await requestJson(`/api/cases/${encodeURIComponent(state.caseId)}/finalize`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    stopAnalysisProgress();
    setAnalysisProgress(96, "加载人工复核数据");
    state.finalizePayload = finalizePayload;
    logDebug("生成复核结果返回", finalizePayload);
    renderAnalysisSteps(6);
    await loadReviewData();
    renderAnalysisSteps(7);
    setAnalysisProgress(100, "分析完成");
    showNotice(els.analysisMessage, "success", "复核结果已生成，请进入人工复核。");
    showStep("review");
  } catch (error) {
    stopAnalysisProgress();
    state.lastError = error;
    renderAnalysisSteps(5, true);
    setAnalysisProgress(state.analysisProgressValue || 0, "分析未完成");
    handleFriendlyError(error, els.analysisMessage, "生成复核结果失败。部分材料可能未能完成识别，请稍后重试或在待复核清单中人工复核。");
  }
}

function beginAnalysisProgress(label, start, cap) {
  stopAnalysisProgress();
  setAnalysisProgress(Math.max(state.analysisProgressValue, start), label);
  state.analysisProgressTimer = window.setInterval(() => {
    if (state.analysisProgressValue >= cap) {
      return;
    }
    const step = state.analysisProgressValue < 55 ? 2 : 1;
    setAnalysisProgress(Math.min(cap, state.analysisProgressValue + step), label);
  }, 420);
}

function stopAnalysisProgress() {
  if (state.analysisProgressTimer) {
    window.clearInterval(state.analysisProgressTimer);
    state.analysisProgressTimer = null;
  }
}

function setAnalysisProgress(percent, label) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  state.analysisProgressValue = value;
  els.analysisProgressBar.style.width = `${value}%`;
  els.analysisProgressText.textContent = `${value}%`;
  els.analysisCurrentStep.textContent = label;
}

function renderAnalysisSteps(doneCount, hasError = false) {
  els.analysisSteps.replaceChildren();
  analysisSteps.forEach((label, index) => {
    const item = document.createElement("li");
    if (index < doneCount) {
      item.className = "is-done";
    } else if (index === doneCount && !hasError) {
      item.className = "is-active";
    }
    if (hasError && index === doneCount) {
      item.className = "is-error";
    }
    const marker = document.createElement("span");
    marker.textContent = String(index + 1).padStart(2, "0");
    const text = document.createElement("strong");
    text.textContent = label;
    item.append(marker, text);
    els.analysisSteps.appendChild(item);
  });
}

async function loadReviewData() {
  const payload = await requestJson(`/api/cases/${encodeURIComponent(state.caseId)}/review`, {
    headers: { Accept: "application/json" },
  });
  state.reviewPayload = payload;
  state.reviewData = payload.data || {};
  state.reviewStatus = payload.review_status || {};
  logDebug("复核数据返回", payload);
  renderReview();
  updateStepButtons();
}

function renderReview() {
  els.reviewTables.replaceChildren();
  els.checklistResults.replaceChildren();
  els.problemList.replaceChildren();
  els.fileIssueList.replaceChildren();

  const data = state.reviewData || {};
  renderReviewSummary(data, state.reviewStatus || {});
  for (const [sheetName, columns] of Object.entries(editableTables)) {
    renderEditableTable(sheetName, columns, getRows(data, sheetName));
  }
  renderIdentityTable(data["身份信息"] || data.identity_info || {});
  renderReadonlyChecklist(data["checklist结果"] || data.checklist_rows || []);
  renderProblemList(data["待复核问题"] || data.review_issue_rows || []);
  renderFileIssues(state.reviewPayload || {});
  updateExportState();
}

function renderReviewSummary(data, reviewStatus) {
  els.reviewSummary.replaceChildren();
  const finalRows = getRows(data, "最终申报表").length;
  const completeRows = getRows(data, "完整表").length;
  const holdingRows = getRows(data, "持仓").length;
  const problemRows = getRows(data, "待复核问题").length;
  const items = [
    ["最终申报记录", finalRows],
    ["完整交易记录", completeRows],
    ["持仓记录", holdingRows],
    ["待复核问题", problemRows],
    ["复核状态", reviewStatus.review_saved ? "已保存" : "待保存"],
  ];
  for (const [label, value] of items) {
    const item = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = value;
    const span = document.createElement("span");
    span.textContent = label;
    item.append(strong, span);
    els.reviewSummary.appendChild(item);
  }
}

function renderEditableTable(title, columns, rows) {
  const section = document.createElement("section");
  section.className = "content-card review-table-block";
  section.dataset.reviewKey = title;

  const header = document.createElement("div");
  header.className = "table-title-row";
  const titleBox = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = title;
  titleBox.appendChild(heading);
  const actions = document.createElement("div");
  actions.className = "table-actions";
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "text-button";
  addButton.textContent = "新增一行";
  addButton.addEventListener("click", () => addEditableRow(title, columns, {}));
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "text-button";
  deleteButton.textContent = "删除选中行";
  deleteButton.addEventListener("click", () => deleteSelectedRows(title));
  actions.append(addButton, deleteButton);
  header.append(titleBox, actions);
  section.appendChild(header);

  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = createEditableTable(title, columns);
  wrapper.appendChild(table);
  section.appendChild(wrapper);
  els.reviewTables.appendChild(section);

  for (const row of rows) {
    addEditableRow(title, columns, row);
  }
}

function renderIdentityTable(identityInfo) {
  const columns = [
    ...identityColumns,
    ...Object.keys(identityInfo).filter((column) => column !== "_meta" && !identityColumns.includes(column)),
  ];
  const section = document.createElement("section");
  section.className = "content-card review-table-block";
  section.dataset.reviewKey = "身份信息";

  const heading = document.createElement("h3");
  heading.textContent = "身份信息";
  section.appendChild(heading);

  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = createEditableTable("身份信息", columns);
  wrapper.appendChild(table);
  section.appendChild(wrapper);
  els.reviewTables.appendChild(section);
  addEditableRow("身份信息", columns, identityInfo);
}

function createEditableTable(key, columns) {
  const table = document.createElement("table");
  table.className = "review-table";
  table.dataset.reviewKey = key;
  table.dataset.columns = JSON.stringify(columns);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  appendHeader(headRow, "选择");
  columns.forEach((column) => appendHeader(headRow, column));
  thead.appendChild(headRow);
  table.appendChild(thead);
  table.appendChild(document.createElement("tbody"));
  return table;
}

function addEditableRow(key, columns, row) {
  const table = els.reviewTables.querySelector(`table[data-review-key="${cssEscape(key)}"]`);
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
  const table = els.reviewTables.querySelector(`table[data-review-key="${cssEscape(key)}"]`);
  if (!table) {
    return;
  }
  const rows = [...table.querySelectorAll("tbody tr")];
  const selected = rows.filter((row) => row.querySelector('input[type="checkbox"]')?.checked);
  const toDelete = selected.length ? selected : rows.slice(-1);
  toDelete.forEach((row) => row.remove());
}

function renderReadonlyChecklist(rows) {
  const legalRows = legalChecklistRows(rows);
  if (!legalRows.length) {
    renderEmpty(els.checklistResults, "暂无法律 checklist 结果。");
    return;
  }
  for (const row of legalRows) {
    const item = document.createElement("article");
    item.className = "readonly-card";
    const title = document.createElement("strong");
    title.textContent = row["checklist条件"] || "";
    const status = document.createElement("span");
    status.className = "status-label";
    status.textContent = row["状态"] || "";
    const desc = document.createElement("p");
    desc.textContent = row["说明"] || "";
    item.append(title, status, desc);
    els.checklistResults.appendChild(item);
  }
}

function renderProblemList(rows) {
  if (!rows.length) {
    renderEmpty(els.problemList, "暂无待复核问题。");
    return;
  }
  els.problemList.replaceChildren();
  const table = createTable(problemColumns);
  table.className = "review-table problem-review-table";
  const tbody = table.querySelector("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const column of problemColumns) {
      appendCell(tr, row[column] || "");
    }
    tbody.appendChild(tr);
  }
  els.problemList.appendChild(table);
}

function renderFileIssues(payload) {
  const summaries = asObjectArray(payload.file_issue_summaries || payload.trace?.file_issue_summaries);
  const issues = asObjectArray(payload.file_issues || payload.trace?.file_issues);
  if (!summaries.length && !issues.length) {
    renderEmpty(els.fileIssueList, "未发现文件级 OCR、解析、抽取或关键字段缺失问题。");
    return;
  }

  const rawByFile = new Map();
  for (const issue of issues) {
    if (issue.file_id) {
      rawByFile.set(issue.file_id, issue);
    }
  }
  const cards = summaries.length ? summaries : issues.map((issue) => ({
    file_id: issue.file_id || "",
    file_no: issue.file_no || "",
    file_name: issue.file_name || "",
    status: issue.severity === "error" ? "异常" : "需人工复核",
    summary: asArray(issue.evidence).join("；") || "该文件存在待核对问题。",
    issue_types: issue.issue_types || [],
    suggested_action: issue.suggested_action || "请核对该文件的处理和抽取结果。",
  }));

  for (const summary of cards) {
    const raw = rawByFile.get(summary.file_id) || {};
    const item = document.createElement("article");
    item.className = "readonly-card file-issue-card";
    const title = document.createElement("strong");
    title.textContent = [summary.file_no ? `材料${summary.file_no}` : "", summary.file_name || "未命名材料"].filter(Boolean).join("：");
    const status = document.createElement("span");
    status.className = "status-label";
    status.textContent = normalizeReviewStatus(summary.status || raw.severity);
    const desc = document.createElement("p");
    desc.textContent = summary.summary || "该文件存在待核对问题。";
    const tags = document.createElement("div");
    tags.className = "tag-row";
    asArray(summary.issue_types || raw.issue_types).forEach((type) => {
      const tag = document.createElement("span");
      tag.textContent = issueTypeLabel(type);
      tags.appendChild(tag);
    });
    const action = document.createElement("span");
    action.className = "muted-line";
    action.textContent = summary.suggested_action || raw.suggested_action || "请核对该文件的处理和抽取结果。";
    item.append(title, status, desc);
    if (tags.childElementCount) {
      item.appendChild(tags);
    }
    item.appendChild(action);
    els.fileIssueList.appendChild(item);
  }
}

async function saveReviewData() {
  if (!state.caseId || !state.reviewData) {
    return;
  }
  els.saveReviewButton.disabled = true;
  els.exportMessage.textContent = "正在保存复核结果。";
  try {
    const payload = await requestJson(`/api/cases/${encodeURIComponent(state.caseId)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(collectReviewData()),
    });
    state.reviewStatus = payload.review_status || {};
    logDebug("保存复核结果返回", payload);
    els.exportMessage.textContent = "复核结果已保存，可以导出 Excel";
    updateExportState();
  } catch (error) {
    els.saveReviewButton.disabled = false;
    handleFriendlyText(error, "复核结果保存失败，请稍后重试。");
  }
}

async function exportExcel() {
  if (!state.caseId) {
    return;
  }
  els.exportExcelButton.disabled = true;
  els.exportMessage.textContent = "正在准备 Excel。";
  try {
    const response = await fetch(`/api/cases/${encodeURIComponent(state.caseId)}/export/excel`);
    if (!response.ok) {
      const payload = await safeJson(response);
      if (response.status === 409) {
        throw makeFriendlyError("请先保存人工复核结果，再导出 Excel。", payload);
      }
      throw makeRequestError(response, payload, "导出 Excel 失败，请稍后重试。");
    }
    const blob = await response.blob();
    downloadBlob(blob, "投资申报复核结果.xlsx");
    els.exportMessage.textContent = "Excel 已开始下载。";
  } catch (error) {
    els.exportExcelButton.disabled = state.reviewStatus?.excel_export_allowed !== true;
    handleFriendlyText(error, "导出 Excel 失败，请稍后重试。");
  }
}

function collectReviewData() {
  return {
    review_data: {
      最终申报表: collectTableRows("最终申报表"),
      完整表: collectTableRows("完整表"),
      持仓: collectTableRows("持仓"),
      身份信息: collectIdentityInfo(),
      待复核问题: state.reviewData?.["待复核问题"] || state.reviewData?.review_issue_rows || [],
      checklist结果: legalChecklistRows(state.reviewData?.["checklist结果"] || state.reviewData?.checklist_rows || []),
    },
  };
}

function collectTableRows(key) {
  const table = els.reviewTables.querySelector(`table[data-review-key="${cssEscape(key)}"]`);
  if (!table) {
    return [];
  }
  const columns = JSON.parse(table.dataset.columns || "[]");
  const rows = [];
  for (const tr of table.querySelectorAll("tbody tr")) {
    const row = parseJsonObject(tr.dataset.originalRow);
    let hasValue = false;
    for (const column of columns) {
      const value = tr.querySelector(`input[data-column="${cssEscape(column)}"]`)?.value.trim() || "";
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
  return collectTableRows("身份信息")[0] || {};
}

function updateExportState() {
  const allowed = state.reviewStatus?.excel_export_allowed === true;
  els.saveReviewButton.disabled = !state.reviewData;
  els.exportExcelButton.disabled = !allowed;
  els.exportMessage.textContent = allowed
    ? "复核结果已保存，可以导出 Excel"
    : "请先保存人工复核结果";
}

function getRows(data, key) {
  if (!data) {
    return [];
  }
  const aliases = {
    最终申报表: "final_declaration_rows",
    完整表: "full_transaction_rows",
    持仓: "holding_rows",
    待复核问题: "review_issue_rows",
  };
  const rows = data[key] || data[aliases[key]] || [];
  return Array.isArray(rows) ? rows : [];
}

function createTable(columns) {
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  columns.forEach((column) => appendHeader(tr, column));
  thead.appendChild(tr);
  table.appendChild(thead);
  table.appendChild(document.createElement("tbody"));
  return table;
}

function appendHeader(row, text) {
  const th = document.createElement("th");
  th.textContent = text;
  row.appendChild(th);
}

function appendCell(row, text) {
  const td = document.createElement("td");
  td.textContent = text ?? "";
  row.appendChild(td);
}

function renderEmpty(container, text) {
  container.replaceChildren();
  const item = document.createElement("div");
  item.className = "empty-state";
  item.textContent = text;
  container.appendChild(item);
}

function legalChecklistRows(rows) {
  return asObjectArray(rows).filter(
    (row) => String(row["checklist条件"] || "").trim() !== "文件级问题归纳",
  );
}

function showNotice(container, kind, text) {
  if (typeof container === "string") {
    els.exportMessage.textContent = container;
    return;
  }
  container.className = `notice-panel is-${kind}`;
  container.textContent = text;
}

function clearNotice(container) {
  container.textContent = "";
  container.className = "notice-panel";
}

function handleFriendlyError(error, container, fallback) {
  const message = friendlyErrorMessage(error, fallback);
  showNotice(container, "warning", message);
  state.lastError = error;
  logDebug("用户可见错误", error);
}

function handleFriendlyText(error, fallback) {
  const message = friendlyErrorMessage(error, fallback);
  els.exportMessage.textContent = message;
  state.lastError = error;
  logDebug("用户可见错误", error);
}

function friendlyErrorMessage(error, fallback) {
  const raw = String(error?.message || "");
  if (raw.includes("请先保存人工复核结果")) {
    return "请先保存人工复核结果，再导出 Excel。";
  }
  if (raw.includes("final_result.json")) {
    return "请先生成复核结果，再进入人工复核。";
  }
  if (raw.includes("case not found")) {
    return "任务不存在，请重新创建上传任务。";
  }
  if (raw.includes("材料上传失败")) {
    return "材料上传失败，请重新上传或检查文件格式。";
  }
  if (raw.includes("Traceback") || raw.includes(".py") || raw.includes("/Users/")) {
    return fallback;
  }
  return raw || fallback;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await safeJson(response);
  if (!response.ok) {
    throw makeRequestError(response, payload, payload.detail || "请求失败，请稍后重试。");
  }
  return payload;
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function makeRequestError(response, payload, fallback) {
  const detail = payload?.detail;
  const message = typeof detail === "string" ? detail : fallback;
  const error = new Error(message);
  error.status = response.status;
  error.payload = payload;
  return error;
}

function makeFriendlyError(message, payload = {}) {
  const error = new Error(message);
  error.payload = payload;
  return error;
}

function materialNo(file, index) {
  return file.file_no || String(index + 1).padStart(3, "0");
}

function contentTypeLabel(contentType, module) {
  if (module === "identity_info" || contentType === "identity") {
    return "身份材料";
  }
  const labels = {
    chinaclear: "中国结算材料",
    guangfa: "广发证券材料",
    unknown: "待确认材料",
  };
  return labels[contentType] || "账户交易材料";
}

function materialStatusLabel(file) {
  if (file.upload_state === "queued") {
    return "等待上传";
  }
  if (file.upload_state === "uploading") {
    return "上传中，系统处理中";
  }
  if (file.upload_state === "failed") {
    return "上传失败";
  }
  const process = processStatusLabel(file.process_status || file.ocr_status);
  const extract = extractStatusLabel(file.extract_status);
  if (extract) {
    return `${process}，${extract}`;
  }
  return process;
}

function processStatusLabel(status) {
  const labels = {
    queued: "等待上传",
    uploading: "上传中",
    uploaded: "已上传",
    parsed: "已读取",
    ocr_done: "已读取",
    success: "已读取",
    failed: "读取失败",
    partial_failed: "部分读取失败",
    not_required: "无需 OCR",
    skipped: "已跳过",
  };
  return labels[status] || "处理中";
}

function extractStatusLabel(status) {
  if (!status) {
    return "";
  }
  const labels = {
    success: "已抽取",
    mock_success: "已抽取",
    skipped: "无需抽取",
    failed: "抽取失败",
    llm_request_failed: "抽取失败",
    json_parse_failed: "需人工复核",
    partial_failed: "部分抽取失败",
  };
  return labels[status] || "抽取处理中";
}

function reviewReasonText(reasons) {
  const texts = asArray(reasons).map(sanitizeIssueText).filter(Boolean);
  return texts.length ? texts.join("；") : "暂无";
}

function sanitizeIssueText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (text.includes("Traceback") || text.includes(".py") || text.includes("/Users/") || text.includes("output_dir")) {
    return "材料处理异常，请人工复核。";
  }
  return text
    .replaceAll("content_type", "材料类型")
    .replaceAll("extract_result", "抽取结果")
    .replaceAll("unknown", "待确认")
    .replaceAll("success", "成功")
    .replaceAll("failed", "失败");
}

function normalizeReviewStatus(status) {
  if (status === "error" || status === "异常") {
    return "异常";
  }
  if (status === "normal" || status === "通过") {
    return "通过";
  }
  return "需人工复核";
}

function issueTypeLabel(type) {
  const labels = {
    content_type_unknown: "文件类型待确认",
    ocr_failed: "OCR 失败",
    ocr_low_confidence: "OCR 置信度低",
    file_parse_failed: "文件无法解析",
    extract_failed: "抽取失败",
    extract_partial_failed: "部分抽取失败",
    llm_request_failed: "智能抽取请求失败",
    json_parse_failed: "抽取结果不完整",
    llm_output_truncated: "抽取输出被截断",
    schema_invalid: "抽取结构异常",
    missing_required_fields: "缺少必填字段",
    missing_date: "缺少日期",
    missing_securities_account: "缺少证券账号",
    missing_account_type: "缺少账户类型",
    missing_security_code: "缺少证券代码",
    missing_security_name: "缺少证券名称",
    many_pending_review_items: "待复核记录较多",
    pending_review_event: "存在待复核事件",
    pending_review_holding: "存在待复核持仓",
    unknown_event_type: "事件类型待确认",
    conflict_between_sources: "来源字段冲突",
    file_review_reason: "文件处理提示",
  };
  return labels[type] || String(type || "待复核");
}

function asArray(value) {
  return Array.isArray(value) ? value.filter((item) => item !== null && item !== undefined) : [];
}

function asObjectArray(value) {
  return asArray(value).filter((item) => item && typeof item === "object");
}

function parseJsonObject(value) {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function cssEscape(value) {
  return window.CSS?.escape ? CSS.escape(value) : String(value).replaceAll('"', '\\"');
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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

function logDebug(label, value) {
  state.debugLog.push({
    time: new Date().toLocaleTimeString(),
    label,
    value: serializeDebugValue(value),
  });
  renderDebugLog();
}

function serializeDebugValue(value) {
  if (value instanceof Error) {
    return {
      message: value.message,
      status: value.status,
      payload: value.payload,
    };
  }
  return value;
}

function renderDebugLog() {
  els.debugOutput.textContent = JSON.stringify(
    {
      state,
      debugLog: state.debugLog,
    },
    null,
    2,
  );
}

async function checkLlmHealth() {
  try {
    const payload = await requestJson("/api/llm/health", { headers: { Accept: "application/json" } });
    logDebug("模型状态", payload);
    els.debugOutput.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    logDebug("模型状态检查失败", error);
    els.debugOutput.textContent = friendlyErrorMessage(error, "模型状态检查失败。");
  }
}

function toggleAssistant(forceOpen) {
  if (els.assistantToggle.dataset.justDragged === "true") {
    return;
  }
  const isOpen = typeof forceOpen === "boolean"
    ? forceOpen
    : !els.assistantPanel.classList.contains("is-open");
  els.assistantPanel.classList.toggle("is-open", isOpen);
  els.assistantPanel.setAttribute("aria-hidden", String(!isOpen));
  els.assistantToggle.setAttribute("aria-expanded", String(isOpen));
  if (isOpen) {
    renderAssistantMessages();
    els.assistantInput.focus();
  }
}

function startAssistantDrag(event) {
  const pointer = event.touches?.[0] || event;
  if (!pointer) {
    return;
  }
  const interactiveTarget = event.target.closest("input, button, a, select, textarea");
  if (interactiveTarget && interactiveTarget !== els.assistantToggle) {
    return;
  }
  const widget = document.querySelector(".assistant-widget");
  if (!widget) {
    return;
  }
  const rect = widget.getBoundingClientRect();
  state.assistantDrag = {
    startY: pointer.clientY,
    startTop: rect.top,
    moved: false,
  };
  widget.style.top = `${rect.top}px`;
  widget.style.bottom = "auto";
  widget.classList.add("is-dragging");
  document.addEventListener("mousemove", dragAssistant);
  document.addEventListener("mouseup", stopAssistantDrag);
  document.addEventListener("touchmove", dragAssistant, { passive: false });
  document.addEventListener("touchend", stopAssistantDrag);
}

function dragAssistant(event) {
  if (!state.assistantDrag) {
    return;
  }
  const pointer = event.touches?.[0] || event;
  const widget = document.querySelector(".assistant-widget");
  if (!pointer || !widget) {
    return;
  }
  event.preventDefault();
  const panelHeight = els.assistantPanel.classList.contains("is-open")
    ? els.assistantPanel.offsetHeight
    : 0;
  const widgetHeight = Math.max(widget.offsetHeight, panelHeight);
  const nextTop = clamp(
    state.assistantDrag.startTop + pointer.clientY - state.assistantDrag.startY,
    92,
    window.innerHeight - widgetHeight - 12,
  );
  state.assistantDrag.moved =
    state.assistantDrag.moved || Math.abs(pointer.clientY - state.assistantDrag.startY) > 4;
  widget.style.top = `${nextTop}px`;
}

function stopAssistantDrag() {
  const widget = document.querySelector(".assistant-widget");
  if (!state.assistantDrag || !widget) {
    return;
  }
  if (state.assistantDrag.moved) {
    els.assistantToggle.dataset.justDragged = "true";
    window.setTimeout(() => {
      delete els.assistantToggle.dataset.justDragged;
    }, 160);
  }
  state.assistantDrag = null;
  widget.classList.remove("is-dragging");
  document.removeEventListener("mousemove", dragAssistant);
  document.removeEventListener("mouseup", stopAssistantDrag);
  document.removeEventListener("touchmove", dragAssistant);
  document.removeEventListener("touchend", stopAssistantDrag);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function resetAssistant() {
  state.assistantMessages = [
    {
      role: "assistant",
      content: "你好，我是小易。可以问我材料准备、人工复核、待复核清单或 Excel 导出的事项。",
    },
  ];
  renderAssistantMessages();
}

function renderAssistantMessages() {
  els.assistantMessages.replaceChildren();
  for (const message of state.assistantMessages) {
    const item = document.createElement("article");
    item.className = `assistant-message is-${message.role}`;
    const label = document.createElement("span");
    label.textContent = message.role === "user" ? "你" : "小易";
    const text = document.createElement("p");
    text.textContent = message.content;
    item.append(label, text);
    els.assistantMessages.appendChild(item);
  }
  els.assistantMessages.scrollTop = els.assistantMessages.scrollHeight;
}

async function submitAssistantQuestion(question) {
  const content = question.trim();
  if (!content || state.assistantSubmitting) {
    return;
  }
  state.assistantSubmitting = true;
  els.assistantInput.disabled = true;
  state.assistantMessages.push({ role: "user", content });
  state.assistantMessages.push({ role: "assistant", content: "正在整理回复。" });
  renderAssistantMessages();

  try {
    const payload = await requestJson("/api/assistant/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        case_id: state.caseId || null,
        messages: state.assistantMessages
          .filter((message) => message.content !== "正在整理回复。")
          .map((message) => ({ role: message.role, content: message.content })),
      }),
    });
    state.assistantMessages[state.assistantMessages.length - 1] = {
      role: "assistant",
      content: payload.answer || assistantFallbackAnswer(content),
    };
    logDebug("问小易返回", payload);
  } catch (error) {
    state.assistantMessages[state.assistantMessages.length - 1] = {
      role: "assistant",
      content: assistantFallbackAnswer(content),
    };
    logDebug("问小易请求失败", error);
  } finally {
    state.assistantSubmitting = false;
    els.assistantInput.disabled = false;
    renderAssistantMessages();
    els.assistantInput.focus();
  }
}

function assistantFallbackAnswer(question) {
  const text = question.toLowerCase();
  if (question.includes("证券账号") || question.includes("账号")) {
    return "如果材料里没有证券账号，相关记录通常需要进入待复核清单。请在人工复核页核对账户类型、证券账号、日期和对应材料。";
  }
  if (question.includes("材料") || question.includes("上传")) {
    return "先填写身份信息，再分别上传身份材料和账户交易材料。材料进入列表后，可以继续添加多份文件，全部准备好后再开始抽取及分析。";
  }
  if (text.includes("excel") || question.includes("导出")) {
    return "Excel 需要先生成复核结果，再完成人工复核并保存。保存复核结果后，导出按钮才会启用。";
  }
  if (question.includes("复核") || text.includes("checklist") || question.includes("问题")) {
    return "人工复核页可以修改申报表、完整表、持仓和身份信息；右侧复核辅助栏展示法律 checklist 和文件级问题，下方待复核清单用于定位具体问题。";
  }
  return "这个问题需要结合材料和复核表格判断。你可以先完成上传和系统分析，再在人工复核页查看法律 checklist、文件级问题和待复核清单。";
}

function bindEvents() {
  els.createCaseForm.addEventListener("submit", createCase);
  els.identityUploadForm.addEventListener("submit", uploadIdentityFiles);
  els.accountUploadForm.addEventListener("submit", uploadAccountFiles);
  els.refreshFilesButton.addEventListener("click", () => loadFiles());
  els.startAnalysisButton.addEventListener("click", startAnalysis);
  els.saveReviewButton.addEventListener("click", saveReviewData);
  els.exportExcelButton.addEventListener("click", exportExcel);
  els.llmHealthButton.addEventListener("click", checkLlmHealth);
  els.showStateButton.addEventListener("click", renderDebugLog);
  els.assistantToggle.addEventListener("mousedown", startAssistantDrag);
  els.assistantToggle.addEventListener("touchstart", startAssistantDrag, { passive: true });
  els.assistantPanel.querySelector(".assistant-header")?.addEventListener("mousedown", startAssistantDrag);
  els.assistantPanel.querySelector(".assistant-header")?.addEventListener("touchstart", startAssistantDrag, { passive: true });
  els.assistantToggle.addEventListener("click", () => toggleAssistant());
  els.assistantClose.addEventListener("click", () => toggleAssistant(false));
  els.assistantReset.addEventListener("click", resetAssistant);
  els.assistantForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitAssistantQuestion(els.assistantInput.value);
    els.assistantInput.value = "";
  });
  for (const promptButton of els.assistantPrompts) {
    promptButton.addEventListener("click", () => {
      toggleAssistant(true);
      submitAssistantQuestion(promptButton.getAttribute("data-assistant-prompt") || "");
    });
  }
  for (const button of els.stepButtons) {
    button.addEventListener("click", () => showStep(button.dataset.step));
  }
}

bindEvents();
renderAssistantMessages();
renderMaterials();
renderAnalysisSteps(0);
setAnalysisProgress(0, "准备分析材料");
updateExportState();
checkApiHealth();
