const statusText = document.getElementById("status-text");
const statusDot = document.getElementById("status-dot");
const caseForm = document.getElementById("case-form");
const caseResult = document.getElementById("case-result");
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

async function createCase(event) {
  event.preventDefault();

  const formData = new FormData(caseForm);
  const payload = {
    name: String(formData.get("name") || "").trim(),
    phone: String(formData.get("phone") || "").trim(),
    relation_type: String(formData.get("relation_type") || "employee_self").trim(),
  };

  caseResult.textContent = "正在创建任务...";

  try {
    const response = await fetch("/api/cases", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "创建任务失败");
    }

    caseResult.textContent = [
      `case_id: ${data.case_id}`,
      `status: ${data.status}`,
      "本地目录已创建",
    ].join("\n");
  } catch (error) {
    caseResult.textContent = error.message || "创建任务失败";
  }
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
caseForm.addEventListener("submit", createCase);
debugFileForm.addEventListener("submit", processDebugFile);
