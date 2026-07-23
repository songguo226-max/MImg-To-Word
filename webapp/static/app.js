const convertTab = document.querySelector("#convertTab");
const settingsTab = document.querySelector("#settingsTab");
const convertView = document.querySelector("#convertView");
const settingsView = document.querySelector("#settingsView");
const fileInput = document.querySelector("#fileInput");
const selectFiles = document.querySelector("#selectFiles");
const dropzone = document.querySelector("#dropzone");
const dropHint = document.querySelector("#dropHint");
const jobList = document.querySelector("#jobList");
const jobCount = document.querySelector("#jobCount");
const downloadAll = document.querySelector("#downloadAll");
const cancelAll = document.querySelector("#cancelAll");
const globalProgressBar = document.querySelector("#globalProgressBar");
const globalSummary = document.querySelector("#globalSummary");
const tokenSummary = document.querySelector("#tokenSummary");
const settingsForm = document.querySelector("#settingsForm");
const settingsMessage = document.querySelector("#settingsMessage");
const testSettings = document.querySelector("#testSettings");

let pollTimer = null;
let versionTimer = null;
let latestJobs = [];
let bulkDownloadedJobIds = new Set();
const appVersion = window.__MATHIMG_APP_VERSION__ || "";
let pricing = {
  inputPerMillion: 0,
  outputPerMillion: 0,
};

function switchView(name) {
  const settings = name === "settings";
  convertTab.classList.toggle("active", !settings);
  settingsTab.classList.toggle("active", settings);
  convertTab.setAttribute("aria-selected", String(!settings));
  settingsTab.setAttribute("aria-selected", String(settings));
  convertView.classList.toggle("active", !settings);
  settingsView.classList.toggle("active", settings);
  if (settings) {
    loadSettings();
  }
}

function setHint(message) {
  dropHint.textContent = message;
}

function setSettingsStatus(kind, message) {
  settingsMessage.classList.remove("status-idle", "status-testing", "status-success", "status-error");
  settingsMessage.classList.add(`status-${kind}`);

  const text = String(message || "");
  const splitAt = text.indexOf("：");
  const hasStructuredStatus = kind !== "idle" && splitAt > 0;
  if (!hasStructuredStatus) {
    settingsMessage.textContent = text;
    return;
  }

  const title = text.slice(0, splitAt);
  const detail = text.slice(splitAt + 1).trim();
  settingsMessage.textContent = "";
  const copy = document.createElement("span");
  copy.className = "settings-message-copy";
  const titleNode = document.createElement("strong");
  titleNode.className = "settings-message-title";
  titleNode.textContent = title;
  const detailNode = document.createElement("span");
  detailNode.className = "settings-message-detail";
  detailNode.textContent = detail;
  copy.append(titleNode, detailNode);
  settingsMessage.append(copy);
}

function friendlyConnectionDetail(detail) {
  const raw = String(detail || "").trim();
  const lower = raw.toLowerCase();
  const model = settingsForm.model.value.trim();
  const modelName = model ? `“${model}”` : "当前填写的模型";

  if (!raw) {
    return "不可用：连接失败。请检查模型名称、Base URL 和 API Key。";
  }
  if (raw.startsWith("不可用：") && !raw.includes("{") && !raw.includes("request_id")) {
    return raw;
  }
  if (lower.includes("model_not_found") || lower.includes("does not exist") || lower.includes("model not found")) {
    return `不可用：模型名称${modelName}不可用。请检查模型名是否拼写正确，或确认当前 API Key 已开通这个模型。`;
  }
  if (lower.includes("do not have access") || lower.includes("permission") || lower.includes("403")) {
    return "不可用：当前 API Key 没有权限访问这个模型。请在服务商后台开通模型权限，或换一个已授权的 API Key。";
  }
  if (lower.includes("401") || lower.includes("unauthorized") || lower.includes("invalid api key") || lower.includes("incorrect api key")) {
    return "不可用：API Key 无效或已过期。请重新复制服务商后台的 API Key，保存后再测试。";
  }
  if (lower.includes("quota") || lower.includes("balance") || lower.includes("余额")) {
    return "不可用：账号额度不足。请检查服务商后台的余额、套餐或免费额度是否还能使用。";
  }
  if (lower.includes("rate limit") || lower.includes("too many requests") || lower.includes("429")) {
    return "不可用：请求太频繁。请稍等一会儿再测试，或降低并发数量。";
  }
  if (lower.includes("timed out") || lower.includes("timeout")) {
    return "不可用：连接超时。请检查网络是否正常，或确认 Base URL 是否填写正确。";
  }
  if (lower.includes("connection") || lower.includes("dns") || lower.includes("getaddrinfo")) {
    return "不可用：无法连接到模型服务。请检查 Base URL 是否正确，以及当前网络是否能访问服务商接口。";
  }
  if (lower.includes("404") || lower.includes("not found")) {
    return "不可用：接口地址没有找到。请检查 Base URL 是否填成服务商的 OpenAI 兼容地址。";
  }
  return "不可用：连接失败。请检查模型名称、Base URL 和 API Key 是否与服务商后台一致。";
}

function statusLabel(status) {
  return {
    queued: "等待中",
    running: "处理中",
    completed: "转换完成",
    failed: "转换失败",
    cancelled: "已取消",
  }[status] || status;
}

function extensionLabel(filename) {
  const ext = filename.split(".").pop();
  return ext ? ext.slice(0, 4).toUpperCase() : "IMG";
}

function formatCount(value) {
  return new Intl.NumberFormat("zh-CN").format(Math.max(0, Number(value || 0)));
}

function estimateCost(inputTokens, outputTokens) {
  const inputCost = (Number(inputTokens || 0) * pricing.inputPerMillion) / 1_000_000;
  const outputCost = (Number(outputTokens || 0) * pricing.outputPerMillion) / 1_000_000;
  const total = inputCost + outputCost;
  return total > 0 ? total : null;
}

function formatCost(cost) {
  if (!cost) {
    return "";
  }
  if (cost < 0.0001) {
    return "估算费用低于 ¥0.0001";
  }
  const digits = cost < 1 ? 4 : 2;
  return `估算费用约 ¥${cost.toFixed(digits)}`;
}

function tokenBreakdownText(inputTokens, outputTokens) {
  return `发送给模型 ${formatCount(inputTokens)}，模型生成 ${formatCount(outputTokens)}`;
}

function tokenText(job) {
  const inputTokens = job.input_tokens || 0;
  const outputTokens = job.output_tokens || 0;
  const total = inputTokens + outputTokens;
  if (total > 0) {
    const cost = formatCost(estimateCost(inputTokens, outputTokens));
    return `本次消耗 ${formatCount(total)} tokens（${tokenBreakdownText(inputTokens, outputTokens)}）${cost ? ` · ${cost}` : ""}`;
  }
  return "正在统计消耗量";
}

function statusClass(status) {
  return `status-${String(status || "queued").replace(/[^a-z-]/g, "")}`;
}

function renderEmptyState() {
  jobList.innerHTML = `
    <div class="empty-state">
      <span class="empty-icon" aria-hidden="true">∑</span>
      <strong>队列为空</strong>
      <span>等待图片上传</span>
    </div>
  `;
}

function renderJobs(jobs) {
  latestJobs = jobs;
  jobCount.textContent = String(jobs.length);

  if (jobs.length === 0) {
    bulkDownloadedJobIds.clear();
    renderEmptyState();
    globalProgressBar.style.width = "0%";
    globalSummary.textContent = "0 / 0 完成";
    tokenSummary.textContent = "本轮共消耗 0 tokens";
    downloadAll.hidden = true;
    cancelAll.hidden = true;
    return;
  }

  const completed = jobs.filter((job) => job.status === "completed").length;
  const downloadable = jobs.filter((job) => job.status === "completed" && job.download_url);
  const currentJobIds = new Set(jobs.map((job) => job.id));
  bulkDownloadedJobIds.forEach((jobId) => {
    if (!currentJobIds.has(jobId)) {
      bulkDownloadedJobIds.delete(jobId);
    }
  });
  const pendingBulkDownloads = downloadable.filter((job) => !bulkDownloadedJobIds.has(job.id));
  const hasActiveJobs = jobs.some((job) => job.status === "queued" || job.status === "running");
  const inputTokens = jobs.reduce((sum, job) => sum + (job.input_tokens || 0), 0);
  const outputTokens = jobs.reduce((sum, job) => sum + (job.output_tokens || 0), 0);
  const totalTokens = inputTokens + outputTokens;
  const totalProgress = jobs.reduce((sum, job) => sum + (job.progress || 0), 0);
  const averageProgress = Math.round(totalProgress / jobs.length);
  globalProgressBar.style.width = `${averageProgress}%`;
  globalSummary.textContent = `${completed} / ${jobs.length} 完成`;
  const totalCost = formatCost(estimateCost(inputTokens, outputTokens));
  tokenSummary.textContent = totalTokens > 0
    ? `本轮共消耗 ${formatCount(totalTokens)} tokens（${tokenBreakdownText(inputTokens, outputTokens)}）${totalCost ? ` · ${totalCost}` : ""}`
    : "正在统计本轮消耗量";
  downloadAll.hidden = pendingBulkDownloads.length === 0;
  downloadAll.disabled = pendingBulkDownloads.length === 0;
  downloadAll.textContent = hasActiveJobs
    ? `下载已完成 (${pendingBulkDownloads.length})`
    : `下载全部 (${pendingBulkDownloads.length})`;
  cancelAll.hidden = false;
  cancelAll.textContent = hasActiveJobs ? "取消全部" : "清空";
  cancelAll.dataset.mode = hasActiveJobs ? "cancel" : "clear";

  jobList.innerHTML = jobs.map((job) => {
    const progress = Math.max(0, Math.min(100, job.progress || 0));
    const canCancel = job.status === "queued" || job.status === "running";
    const canDownload = job.status === "completed" && job.download_url;
    const meta = job.error
      ? job.error
      : `${job.step || statusLabel(job.status)} · ${tokenText(job)}`;

    const action = canDownload
      ? `<a class="job-action download" href="${job.download_url}">下载 Word</a>`
      : canCancel
        ? `<button class="job-action cancel" type="button" data-cancel="${job.id}">取消</button>`
        : `<span class="status-text ${statusClass(job.status)}">${statusLabel(job.status)}</span>`;

    return `
      <article class="job ${statusClass(job.status)}">
        <div class="thumb" aria-hidden="true">${extensionLabel(job.filename)}</div>
        <div class="job-main">
          <div class="job-topline">
            <div class="file-name">${escapeHtml(job.filename)}</div>
            <span class="job-status ${statusClass(job.status)}">${statusLabel(job.status)}</span>
          </div>
          <div class="job-meta">${escapeHtml(meta)}</div>
          <div class="job-progress-track" aria-label="任务进度 ${progress}%">
            <div class="job-progress" style="width:${progress}%"></div>
          </div>
        </div>
        <div class="job-actions">${action}</div>
      </article>
    `;
  }).join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadJobs() {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    setHint("读取任务列表失败");
    return;
  }
  const data = await response.json();
  renderJobs(data.jobs || []);
}

function ensurePolling() {
  if (pollTimer) {
    return;
  }
  pollTimer = window.setInterval(loadJobs, 1200);
}

function ensureVersionCheck() {
  if (versionTimer || !appVersion) {
    return;
  }
  versionTimer = window.setInterval(checkFrontendVersion, 5000);
}

async function checkFrontendVersion() {
  const response = await fetch(`/api/frontend-version?client=${encodeURIComponent(appVersion)}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    return;
  }
  const data = await response.json().catch(() => ({}));
  if (data.version && data.version !== appVersion) {
    window.location.reload();
  }
}

async function uploadFiles(files) {
  const selected = Array.from(files || []);
  if (selected.length === 0) {
    return;
  }

  const formData = new FormData();
  selected.forEach((file) => formData.append("files", file));
  setHint("正在上传图片...");

  const response = await fetch("/api/jobs", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    setHint(error.detail || "上传失败");
    return;
  }

  fileInput.value = "";
  setHint("上传完成，正在处理队列");
  await loadJobs();
  ensurePolling();
}

async function cancelJob(jobId) {
  await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
  await loadJobs();
}

async function cancelAllJobs() {
  await fetch("/api/jobs/cancel", { method: "POST" });
  await loadJobs();
}

async function clearJobs() {
  let response = await fetch("/api/jobs/clear", { method: "POST" });
  if (response.status === 404 || response.status === 405) {
    response = await fetch("/api/jobs", { method: "DELETE" });
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = response.status === 404 || response.status === 405
      ? "服务端未加载清空接口，请关闭启动窗口后重新运行 start_web.bat"
      : error.detail;
    setHint(detail || "清空队列失败");
    return;
  }
  setHint("队列已清空");
  await loadJobs();
}

function downloadAllCompleted() {
  const downloadable = latestJobs.filter(
    (job) => job.status === "completed" && job.download_url && !bulkDownloadedJobIds.has(job.id),
  );
  if (downloadable.length === 0) {
    return;
  }
  downloadable.forEach((job) => {
    const link = document.createElement("a");
    link.href = job.download_url;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
    bulkDownloadedJobIds.add(job.id);
  });
  setHint(`已开始下载 ${downloadable.length} 个 Word 文件`);
  renderJobs(latestJobs);
}

function handleQueueControl() {
  if (cancelAll.dataset.mode === "clear") {
    clearJobs();
    return;
  }
  cancelAllJobs();
}

async function loadSettings() {
  const response = await fetch("/api/settings");
  if (!response.ok) {
    setSettingsStatus("error", "不可用：读取设置失败");
    return;
  }
  const settings = await response.json();
  settingsForm.model.value = settings.model || "";
  settingsForm.base_url.value = settings.base_url || "";
  settingsForm.api_key.value = settings.api_key || "";
  settingsForm.max_workers.value = settings.max_workers || 3;
  pricing = {
    inputPerMillion: Number(settings.input_token_price_per_million || 0),
    outputPerMillion: Number(settings.output_token_price_per_million || 0),
  };
  settingsForm.input_token_price_per_million.value = pricing.inputPerMillion || "";
  settingsForm.output_token_price_per_million.value = pricing.outputPerMillion || "";
  renderJobs(latestJobs);
}

function settingsPayload() {
  return {
    model: settingsForm.model.value.trim(),
    base_url: settingsForm.base_url.value.trim(),
    api_key: settingsForm.api_key.value.trim(),
    max_workers: Number(settingsForm.max_workers.value || 3),
    input_token_price_per_million: Number(settingsForm.input_token_price_per_million.value || 0),
    output_token_price_per_million: Number(settingsForm.output_token_price_per_million.value || 0),
  };
}

async function saveSettings() {
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settingsPayload()),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    setSettingsStatus("error", data.detail ? `不可用：${data.detail}` : "不可用：保存失败");
    return;
  }
  setSettingsStatus("idle", "设置已保存，新的转换任务会使用更新后的配置。");
  settingsForm.api_key.value = data.api_key || "";
  pricing = {
    inputPerMillion: Number(data.input_token_price_per_million || 0),
    outputPerMillion: Number(data.output_token_price_per_million || 0),
  };
  renderJobs(latestJobs);
}

async function checkSettings() {
  setSettingsStatus("testing", "正在测试连接...");
  testSettings.disabled = true;
  const response = await fetch("/api/settings/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settingsPayload()),
  });
  const data = await response.json().catch(() => ({}));
  testSettings.disabled = false;
  if (response.ok) {
    setSettingsStatus("success", data.message || "可用：已成功连接模型");
    return;
  }
  setSettingsStatus("error", friendlyConnectionDetail(data.detail));
}

convertTab.addEventListener("click", () => switchView("convert"));
settingsTab.addEventListener("click", () => switchView("settings"));
selectFiles.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
downloadAll.addEventListener("click", downloadAllCompleted);
cancelAll.addEventListener("click", handleQueueControl);
testSettings.addEventListener("click", checkSettings);

dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveSettings();
});

jobList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-cancel]");
  if (button) {
    cancelJob(button.dataset.cancel);
  }
});

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  });
});

dropzone.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));

loadJobs();
loadSettings();
ensurePolling();
ensureVersionCheck();
