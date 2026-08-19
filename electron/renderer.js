const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const REGION_SCOPES = { TW: "/Taiwan", TH: "/Thailand", VN: "/Vietnam", ID: "/Indonesia" };
const MODULE_ORDER = ["activity", "skin", "item", "reward", "limit"];
const REGULAR_ACTIVITY_KEYWORDS = [
  "签到", "定时", "翻倍", "条件", "兑换", "文本", "商城", "活跃度", "全服统一进度", "收集兑换", "通用兑换",
];

function buildCoreContentGroups(details) {
  const groups = [
    { id: "ilua", label: "ilua 活动", items: [] },
    { id: "regular", label: "常规活动", items: [] },
    { id: "item", label: "道具", items: [] },
    { id: "related", label: "关联内容", items: [] },
  ];
  const byId = Object.fromEntries(groups.map((group) => [group.id, group]));
  details.forEach((item) => {
    const moduleId = String(item.module || "");
    const activityType = String(item.activity_type || "");
    if (!item.direct_change) {
      byId.related.items.push(item);
    } else if (moduleId === "activity" && activityType.toLowerCase().includes("ilua")) {
      byId.ilua.items.push(item);
    } else if (moduleId === "activity" && REGULAR_ACTIVITY_KEYWORDS.some((keyword) => activityType.includes(keyword))) {
      byId.regular.items.push(item);
    } else if (moduleId === "item") {
      byId.item.items.push(item);
    }
  });
  return groups;
}

const state = {
  view: "pack",
  region: "TW",
  ftpRegion: "TW",
  inputSource: "auto",
  contentMode: "local_latest",
  settings: {},
  ftpProfiles: {},
  result: null,
  busy: false,
  activeStage: "",
  stageStartedAt: 0,
  stageTimer: null,
};

function toast(message, level = "info") {
  const node = document.createElement("div");
  node.className = `toast ${level}`;
  node.textContent = message;
  $("#toast-region").append(node);
  setTimeout(() => node.remove(), 4200);
}

function setDot(dot, status) {
  dot.className = `status-dot ${status}`;
}

function showView(view) {
  state.view = view;
  $("#pack-view").classList.toggle("hidden", view !== "pack");
  $("#settings-view").classList.toggle("hidden", view !== "settings");
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $("#page-title").textContent = view === "pack" ? "打包任务" : "本地配置";
  $("#page-eyebrow").textContent = view === "pack" ? "LOCAL PACKAGING" : "MACHINE SETTINGS";
}

function selectSegment(container, matcher) {
  container.querySelectorAll("button").forEach((button) => button.classList.toggle("active", matcher(button)));
}

function setRegion(region, { refresh = true } = {}) {
  state.region = region;
  selectSegment($("#region-control"), (button) => button.dataset.region === region);
  $("#scope-display").textContent = REGION_SCOPES[region];
  $("#scope-roots").value = REGION_SCOPES[region];
  $("#ftp-label").textContent = `${region} FTP`;
  if (refresh) refreshConnections();
}

function setInputSource(source) {
  state.inputSource = source;
  selectSegment(document.querySelector(".input-source-control"), (button) => button.dataset.source === source);
  const manual = source !== "auto";
  $("#manual-input-wrap").classList.toggle("hidden", !manual);
  $("#manual-input-label").textContent = source === "files" ? "指定 SVN 文件列表" : "SVN log -v 内容";
  $("#manual-input").placeholder = source === "files"
    ? "M /Taiwan/Databin/Server/..."
    : "粘贴 svn log -v 输出";
}

function setContentMode(mode) {
  state.contentMode = mode;
  selectSegment($("#content-mode-control"), (button) => button.dataset.contentMode === mode);
}

function setRunStatus(label, status = "idle") {
  const badge = $("#run-badge");
  badge.textContent = label;
  badge.className = `run-badge ${status}`;
}

function resetStages() {
  if (state.stageTimer) clearInterval(state.stageTimer);
  state.stageTimer = null;
  state.activeStage = "";
  state.stageStartedAt = 0;
  $$("#stage-list li").forEach((item) => {
    item.classList.remove("active", "complete", "error");
    item.querySelector("small").textContent = item.dataset.stage === "archive" ? "人工操作" : "等待任务";
  });
}

function activateStage(stage, detail = "执行中") {
  const order = ["svn", "packaging", "review", "archive"];
  const index = order.indexOf(stage);
  $$("#stage-list li").forEach((item) => {
    const itemIndex = order.indexOf(item.dataset.stage);
    item.classList.toggle("complete", itemIndex < index);
    item.classList.toggle("active", itemIndex === index);
    if (itemIndex < index) item.querySelector("small").textContent = "已完成";
  });
  const current = $(`#stage-list li[data-stage="${stage}"]`);
  if (state.activeStage !== stage) {
    state.activeStage = stage;
    state.stageStartedAt = performance.now();
    if (state.stageTimer) clearInterval(state.stageTimer);
    state.stageTimer = setInterval(() => {
      const active = $(`#stage-list li[data-stage="${state.activeStage}"] small`);
      if (active && state.stageStartedAt) {
        active.textContent = `${active.dataset.label || detail} · ${((performance.now() - state.stageStartedAt) / 1000).toFixed(1)}秒`;
      }
    }, 200);
  }
  if (current) {
    current.querySelector("small").dataset.label = detail;
    current.querySelector("small").textContent = detail;
  }
}

function appendLog(message, level = "info") {
  const panel = $("#log-panel");
  panel.querySelector(".empty-log")?.remove();
  const line = document.createElement("p");
  line.className = level;
  line.textContent = message;
  panel.append(line);
  panel.scrollTop = panel.scrollHeight;
}

function clearLog() {
  $("#log-panel").replaceChildren();
}

function formatDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function readFtpForm() {
  return {
    host: $("#ftp-host").value.trim(),
    port: $("#ftp-port").value.trim() || "21",
    username: $("#ftp-username").value.trim(),
    password: $("#ftp-password").value,
    remote_directory: $("#ftp-directory").value.trim() || "/",
    passive: $("#ftp-passive").checked,
  };
}

function storeFtpForm() {
  const next = readFtpForm();
  const previous = state.ftpProfiles[state.ftpRegion] || {};
  if (!next.password) delete next.password;
  state.ftpProfiles[state.ftpRegion] = { ...previous, ...next };
}

function loadFtpForm(region) {
  state.ftpRegion = region;
  selectSegment($("#ftp-region-control"), (button) => button.dataset.ftpRegion === region);
  const profile = state.ftpProfiles[region] || {};
  $("#ftp-host").value = profile.host || "";
  $("#ftp-port").value = profile.port || "21";
  $("#ftp-username").value = profile.username || "";
  $("#ftp-password").value = "";
  $("#ftp-password").placeholder = profile.password_configured ? "已配置，留空保持" : "输入密码";
  $("#ftp-directory").value = profile.remote_directory || "/";
  $("#ftp-passive").checked = profile.passive !== false;
}

function applySettings(settings) {
  state.settings = { ...settings };
  state.ftpProfiles = { ...(settings.ftp_profiles || {}) };
  $("#local-root").value = settings.local_root || "";
  $("#tdr-root").value = settings.tdr_root || "";
  $("#svn-target").value = settings.svn_target || "";
  $("#svn-exe").value = settings.svn_exe || "svn";
  $("#svn-username").value = settings.svn_username || "";
  $("#use-auth-cache").checked = settings.use_auth_cache !== false;
  $("#backend-url").value = settings.backend_url || "http://127.0.0.1:8780";
  $("#package-version").value = settings.package_version || "";
  $("#scope-roots").value = settings.scope_roots || "/Taiwan";
  $("#enable-commit-check").checked = settings.enable_commit_check !== false;
  $("#enable-region-filter").checked = settings.enable_region_filter !== false;
  $("#commit-whitelist").value = settings.commit_whitelist || "";
  $("#baseline-revision").textContent = settings.last_external_revision_spec || "--";
  $("#baseline-time").textContent = formatDate(settings.last_external_time);
  setRegion(settings.package_region || "TW", { refresh: false });
  loadFtpForm(state.region);
}

function collectSettings() {
  storeFtpForm();
  return {
    local_root: $("#local-root").value.trim(),
    tdr_root: $("#tdr-root").value.trim(),
    svn_target: $("#svn-target").value.trim(),
    svn_exe: $("#svn-exe").value.trim() || "svn",
    svn_username: $("#svn-username").value.trim(),
    use_auth_cache: $("#use-auth-cache").checked,
    last_external_revision_spec: $("#baseline-revision").textContent === "--" ? "" : $("#baseline-revision").textContent,
    last_external_time: state.settings.last_external_time || "",
    scope_roots: $("#scope-roots").value.trim() || REGION_SCOPES[state.region],
    package_version: $("#package-version").value.trim(),
    package_region: state.region,
    enable_commit_check: $("#enable-commit-check").checked,
    enable_region_filter: $("#enable-region-filter").checked,
    enable_skin_validation: false,
    window_start: "",
    window_end: "",
    commit_whitelist: $("#commit-whitelist").value,
    backend_url: $("#backend-url").value.trim(),
    ftp_profiles: state.ftpProfiles,
  };
}

function collectPackPayload() {
  const settings = collectSettings();
  return {
    ...settings,
    region: state.region,
    current_revision_spec: $("#current-revision").value.trim(),
    input_method: state.inputSource === "files" ? "pasted_svn_file_list" : "revision_spec",
    svn_log_source: state.inputSource === "auto" ? "auto" : "manual",
    input_text: $("#manual-input").value,
    svn_password: $("#svn-password").value,
    content_mode: state.contentMode,
  };
}

async function checkBackend({ quiet = false } = {}) {
  setDot($("#backend-dot"), "pending");
  $("#backend-status").textContent = "检查中";
  try {
    const result = await window.aov.request("check_backend", {
      backend_url: $("#backend-url").value.trim(),
      backend_token: $("#backend-token").value,
      region: state.region,
    });
    setDot($("#backend-dot"), "ok");
    $("#backend-status").textContent = "已连接";
    if (result.baseline) {
      $("#baseline-revision").textContent = result.baseline.released_revision_spec;
      $("#baseline-package").textContent = result.baseline.package_id;
      $("#baseline-time").textContent = formatDate(result.baseline.release_time);
      state.settings.last_external_revision_spec = result.baseline.released_revision_spec;
      state.settings.last_external_time = result.baseline.release_time;
      if (result.baseline.package_version) $("#package-version").value = result.baseline.package_version;
    } else {
      $("#baseline-package").textContent = "未建立基线";
    }
    if (!quiet) toast("归档后端连接正常", "success");
    return true;
  } catch (error) {
    setDot($("#backend-dot"), "error");
    $("#backend-status").textContent = "连接失败";
    $("#baseline-package").textContent = "使用本地记录";
    if (!quiet) toast(error.message, "error");
    return false;
  }
}

async function checkFtp({ quiet = false, useForm = false } = {}) {
  setDot($("#ftp-dot"), "pending");
  $("#ftp-status").textContent = "检查中";
  const region = useForm ? state.ftpRegion : state.region;
  try {
    await window.aov.request("check_ftp", {
      region,
      profile: useForm ? readFtpForm() : undefined,
    });
    if (region === state.region) {
      setDot($("#ftp-dot"), "ok");
      $("#ftp-status").textContent = "已连接";
    }
    if (!quiet) toast(`${region} FTP 连接正常`, "success");
    return true;
  } catch (error) {
    if (region === state.region) {
      setDot($("#ftp-dot"), "error");
      $("#ftp-status").textContent = "不可用";
    }
    if (!quiet) toast(error.message, "error");
    return false;
  }
}

async function refreshConnections() {
  $("#ftp-label").textContent = `${state.region} FTP`;
  await Promise.all([checkBackend({ quiet: true }), checkFtp({ quiet: true })]);
}

function renderResult(result) {
  state.result = result;
  $("#result-section").classList.remove("hidden");
  $("#result-package").textContent = result.package_name;
  $("#result-md5").textContent = `MD5 ${result.md5}`;
  $("#result-files").textContent = result.success_count;
  $("#result-warnings").textContent = result.validation.warning_count;
  $("#result-errors").textContent = result.validation.error_count + result.failure_count;
  $("#confirm-archive").disabled = !result.can_archive;
  const status = $("#result-status");
  status.textContent = result.test_mode ? "测试完成" : (result.can_archive ? "待人工确认" : "禁止归档");
  status.className = `result-status ${result.test_mode ? "success" : (result.can_archive ? "" : "error")}`;

  const overview = result.module_overview || {};
  const source = result.package_source || {};
  const details = Array.isArray(result.content_details) && result.content_details.length
    ? result.content_details
    : (Array.isArray(result.activity_details) ? result.activity_details : []);
  const coreGroups = buildCoreContentGroups(details);
  const coreContentCount = coreGroups.reduce((total, group) => total + group.items.length, 0);
  const coreUpdateText = coreGroups
    .filter((group) => group.items.length)
    .map((group) => `${group.label} ${group.items.length}个`)
    .join("、") || "未识别到核心业务内容";
  $("#analysis-source").textContent = source.mode === "historical_revision"
    ? `历史 r${source.target_revision} 精确导出`
    : `本地最新（HEAD r${source.repository_head_revision || "--"}）`;
  const structuralRiskCount = Number(overview.structural_risk_count || 0);
  const validationRiskCount = Number(result.validation.warning_count || 0) + Number(result.validation.error_count || 0) + Number(result.failure_count || 0);
  $("#analysis-update").textContent = validationRiskCount || structuralRiskCount
    ? `${coreUpdateText}，发现 ${validationRiskCount + structuralRiskCount} 项需关注内容`
    : `${coreUpdateText}，当前未发现风险`;
  $("#analysis-note").textContent = coreContentCount
    ? "核心区仅展示 ilua、常规活动、道具与关联内容；其他 Module 结果仍保留在 Report。"
    : "所有差异仍会保留在 Report 中；尚未接入 Module 的表仅记录原始差异。";
  $("#analysis-related").textContent = `${coreGroups.find((group) => group.id === "related").items.length}项关联内容`;
  $("#analysis-risk").textContent = overview.has_structural_risk
    ? `${structuralRiskCount}项`
    : "当前未发现";
  $("#analysis-risk").classList.toggle("risk", Boolean(overview.has_structural_risk));
  $("#analysis-uninterpreted").textContent = `${Number(overview.uninterpreted_change_count || 0)}条`;

  $("#content-overview-count").textContent = `${coreContentCount} 项`;
  const updateList = $("#content-update-list");
  updateList.replaceChildren();
  const previewList = $("#content-preview-list");
  const renderCoreGroup = (selectedGroup) => {
    updateList.querySelectorAll("button").forEach((button) => {
      const selected = button.dataset.group === selectedGroup.id;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    previewList.replaceChildren();
    if (!selectedGroup.items.length) {
      const empty = document.createElement("p");
      empty.className = "content-empty";
      empty.textContent = `本次没有${selectedGroup.label}更新。`;
      previewList.append(empty);
      return;
    }
    selectedGroup.items.forEach((item) => {
      const article = document.createElement("article");
      const marker = document.createElement("span");
      marker.className = "content-module-marker";
      marker.textContent = selectedGroup.label;
      const body = document.createElement("div");
      const header = document.createElement("header");
      const title = document.createElement("strong");
      title.textContent = [item.object_id || item.activity_id, item.object_name || item.activity_name].filter(Boolean).join(" ") || "未命名内容";
      const change = document.createElement("span");
      change.textContent = item.direct_change ? "本次修改" : "关联影响";
      header.append(title, change);
      const type = document.createElement("small");
      type.textContent = item.activity_type || item.object_type || item.module_name || "业务内容";
      const lines = (Array.isArray(item.display_lines) ? item.display_lines : [])
        .filter((line) => line && !String(line).startsWith(`${item.module_name || ""}:`))
        .slice(0, 2);
      const summary = document.createElement("p");
      summary.textContent = lines.join(" · ") || "已识别该业务对象，完整内容见下方详情。";
      body.append(header, type, summary);
      article.append(marker, body);
      previewList.append(article);
    });
  };
  coreGroups.forEach((group) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.dataset.group = group.id;
    tab.setAttribute("role", "tab");
    const count = document.createElement("strong");
    const label = document.createElement("span");
    count.textContent = String(group.items.length);
    label.textContent = group.label;
    tab.append(count, label);
    tab.addEventListener("click", () => renderCoreGroup(group));
    updateList.append(tab);
  });
  renderCoreGroup(coreGroups.find((group) => group.items.length) || coreGroups[0]);
  const moduleGroups = new Map();
  details.forEach((item) => {
    const moduleId = item.module || "other";
    if (!moduleGroups.has(moduleId)) {
      moduleGroups.set(moduleId, {
        id: moduleId,
        name: item.module_name || "其他",
        items: [],
      });
    }
    moduleGroups.get(moduleId).items.push(item);
  });
  const orderedGroups = [...moduleGroups.values()].sort((left, right) => {
    const leftIndex = MODULE_ORDER.indexOf(left.id);
    const rightIndex = MODULE_ORDER.indexOf(right.id);
    return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex);
  });
  $("#activity-detail-count").textContent = details.length
    ? `${details.length}项内容 · ${orderedGroups.length}个 Module`
    : "无可解读内容";
  const moduleTabs = $("#module-detail-tabs");
  moduleTabs.replaceChildren();
  moduleTabs.classList.toggle("hidden", orderedGroups.length === 0);
  const detailList = $("#activity-detail-list");
  detailList.replaceChildren();
  if (!details.length) {
    const empty = document.createElement("p");
    empty.textContent = "本次没有识别到可解读的业务内容。";
    detailList.append(empty);
  }
  details.forEach((activity) => {
    const article = document.createElement("article");
    article.dataset.module = activity.module || "other";
    article.setAttribute("role", "tabpanel");
    const heading = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = [
      activity.object_id || activity.activity_id,
      activity.object_name || activity.activity_name,
    ].filter(Boolean).join(" ");
    const badge = document.createElement("span");
    badge.textContent = activity.module === "activity" && !activity.direct_change
      ? "关联影响"
      : (activity.module_name || "直接更新");
    heading.append(title, badge);
    const type = document.createElement("small");
    type.textContent = activity.activity_type || activity.module_name || activity.object_type || "业务内容";
    const content = document.createElement("pre");
    content.textContent = Array.isArray(activity.display_lines) ? activity.display_lines.join("\n") : "";
    article.append(heading, type, content);
    detailList.append(article);
  });
  const selectDetailModule = (moduleId) => {
    moduleTabs.querySelectorAll("button").forEach((button) => {
      const selected = button.dataset.module === moduleId;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    detailList.querySelectorAll("article").forEach((article) => {
      article.classList.toggle("hidden", article.dataset.module !== moduleId);
    });
  };
  orderedGroups.forEach((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.module = group.id;
    button.setAttribute("role", "tab");
    const label = document.createElement("span");
    const count = document.createElement("strong");
    label.textContent = group.name;
    count.textContent = String(group.items.length);
    button.append(label, count);
    button.addEventListener("click", () => selectDetailModule(group.id));
    moduleTabs.append(button);
  });
  if (orderedGroups.length) selectDetailModule(orderedGroups[0].id);
}

async function startPack({ testMode = false } = {}) {
  if (state.busy) return;
  state.busy = true;
  $("#start-pack").disabled = true;
  $("#run-test").disabled = true;
  $("#result-section").classList.add("hidden");
  clearLog();
  resetStages();
  setRunStatus("执行中", "running");
  activateStage(state.inputSource === "auto" ? "svn" : "packaging", "执行中");
  appendLog(`${testMode ? "执行测试" : "正式打包"} · 区域 ${state.region} · ${$("#current-revision").value.trim() || "未填写 Revision"}`);
  try {
    const result = await window.aov.request("pack", { ...collectPackPayload(), test_mode: testMode });
    activateStage("review", "等待人工确认");
    setRunStatus("已完成", "success");
    appendLog(`${testMode ? "测试" : "打包"}完成：${result.package_name}`, "success");
    renderResult(result);
  } catch (error) {
    setRunStatus("失败", "error");
    const active = $("#stage-list li.active");
    active?.classList.add("error");
    appendLog(error.message, "error");
    toast(error.message, "error");
  } finally {
    state.busy = false;
    $("#start-pack").disabled = false;
    $("#run-test").disabled = false;
  }
}

function updateUploadProgress(data) {
  const total = Number(data.total_bytes || 0);
  const transferred = Number(data.transferred_bytes || 0);
  const percent = total ? Math.min(100, transferred * 100 / total) : 0;
  $("#upload-progress").classList.remove("hidden");
  $("#upload-bar").value = percent;
  $("#upload-percent").textContent = `${percent.toFixed(0)}%`;
}

async function confirmArchive() {
  if (!state.result || state.busy) return;
  if (!window.confirm(`确认归档 ${state.result.package_name}？\n\n将上传 FTP 并同步网页后端。`)) return;
  state.busy = true;
  $("#confirm-archive").disabled = true;
  activateStage("archive", "检查 FTP 同名文件");
  try {
    const info = await window.aov.request("inspect_archive", { region: state.region });
    let policy = "require_absent";
    if (info.exists && info.remote_size === info.local_size) {
      const accepted = window.confirm("FTP 已存在同名且同大小文件。确认是同一个包，并只继续网页归档？");
      if (!accepted) throw new Error("已取消归档");
      policy = "use_existing";
    } else if (info.exists) {
      const accepted = window.confirm("FTP 已存在同名文件，但大小不同。确认替换远端文件？");
      if (!accepted) throw new Error("已取消归档");
      policy = "replace";
    }
    const result = await window.aov.request("publish", {
      region: state.region,
      policy,
      backend_token: $("#backend-token").value,
    });
    $("#upload-bar").value = 100;
    $("#upload-percent").textContent = "100%";
    $("#result-status").textContent = "归档完成";
    $("#result-status").className = "result-status success";
    activateStage("archive", "已归档");
    $("#stage-list li[data-stage='archive']").classList.add("complete");
    setRunStatus("归档完成", "success");
    toast(`归档完成：${result.package_id}`, "success");
  } catch (error) {
    $("#confirm-archive").disabled = false;
    appendLog(error.message, error.message === "已取消归档" ? "warning" : "error");
    if (error.message !== "已取消归档") toast(error.message, "error");
  } finally {
    state.busy = false;
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const message = $("#settings-message");
  message.textContent = "正在保存";
  try {
    const result = await window.aov.request("save_settings", { settings: collectSettings() });
    applySettings(result.settings);
    message.textContent = "配置已保存";
    toast("本地配置已保存", "success");
    refreshConnections();
  } catch (error) {
    message.textContent = "保存失败";
    toast(error.message, "error");
  }
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $$("#region-control button").forEach((button) => button.addEventListener("click", () => setRegion(button.dataset.region)));
  $$(".input-source-control button").forEach((button) => button.addEventListener("click", () => setInputSource(button.dataset.source)));
  $$("#content-mode-control button").forEach((button) => button.addEventListener("click", () => setContentMode(button.dataset.contentMode)));
  $$("#ftp-region-control button").forEach((button) => button.addEventListener("click", () => {
    storeFtpForm();
    loadFtpForm(button.dataset.ftpRegion);
  }));
  $$('[data-browse]').forEach((button) => button.addEventListener("click", async () => {
    const selected = await window.aov.selectDirectory();
    if (selected) $(`#${button.dataset.browse}`).value = selected;
  }));
  $("#start-pack").addEventListener("click", () => startPack());
  $("#run-test").addEventListener("click", () => startPack({ testMode: true }));
  $("#confirm-archive").addEventListener("click", confirmArchive);
  $("#open-output").addEventListener("click", () => state.result && window.aov.openPath(state.result.output_dir));
  $("#open-report").addEventListener("click", () => state.result && window.aov.openPath(state.result.report_path));
  $("#refresh-status").addEventListener("click", refreshConnections);
  $("#test-backend").addEventListener("click", () => checkBackend());
  $("#test-ftp").addEventListener("click", () => checkFtp({ useForm: true }));
  $("#settings-form").addEventListener("submit", saveSettings);
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter" && state.view === "pack") startPack();
  });
  window.aov.onBridgeEvent((message) => {
    if (message.event === "log") appendLog(message.data.message, message.data.level);
    if (message.event === "progress") updateUploadProgress(message.data);
    if (message.event === "stage") {
      const stageMap = { source_check: "svn", packaging: "packaging", preflight: "archive", ftp_upload: "archive", backend_archive: "archive", complete: "archive" };
      const labels = { source_check: "检查本地 SVN", preflight: "复核 Report", ftp_upload: "FTP 上传中", backend_archive: "同步网页后端", complete: "完成归档" };
      activateStage(stageMap[message.data.stage] || "packaging", labels[message.data.stage] || "执行中");
      if (message.data.stage === "ftp_upload") $("#upload-progress").classList.remove("hidden");
    }
  });
  window.aov.onBridgeError(({ message }) => appendLog(message, "error"));
}

async function bootstrap() {
  bindEvents();
  setInputSource("auto");
  setContentMode("local_latest");
  try {
    const result = await window.aov.request("bootstrap");
    applySettings(result.settings);
    if (result.pending_sync_count > 0) toast(`有 ${result.pending_sync_count} 条待同步归档`, "warning");
    await refreshConnections();
  } catch (error) {
    toast(`启动失败：${error.message}`, "error");
    setDot($("#backend-dot"), "error");
    $("#backend-status").textContent = "桥接失败";
  }
}

bootstrap();
