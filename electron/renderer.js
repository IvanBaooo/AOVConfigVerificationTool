const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const REGION_SCOPES = { TW: "/Taiwan", TH: "/Thailand", VN: "/Vietnam", ID: "/Indonesia" };

const state = {
  view: "pack",
  region: "TW",
  ftpRegion: "TW",
  inputSource: "commits",
  settings: {},
  ftpProfiles: {},
  validationRules: [],
  ruleNameOverrides: {},
  result: null,
  acknowledged: new Set(),
  busy: false,
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
  $("#showcase-view").classList.toggle("hidden", view !== "showcase");
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  const titles = {
    pack: ["LOCAL PACKAGING", "打包任务"],
    settings: ["MACHINE SETTINGS", "本地配置"],
    showcase: ["RULE SHOWCASE", "演示模式"],
  };
  const [eyebrow, title] = titles[view] || titles.pack;
  $("#page-title").textContent = title;
  $("#page-eyebrow").textContent = eyebrow;
  if (view === "showcase") loadShowcaseStatus();
}

function selectSegment(container, matcher) {
  container.querySelectorAll("button").forEach((button) => button.classList.toggle("active", matcher(button)));
}

function packDirFor(region) {
  const scope = REGION_SCOPES[region] || "";
  const root = (state.settings.local_root || $("#local-root").value || "").trim().replace(/[\\/]+$/, "");
  if (!root) return scope || "--";
  const sep = root.includes("\\") ? "\\" : "/";
  return root + sep + scope.replace(/^\//, "");
}

function setRegion(region, { refresh = true } = {}) {
  state.region = region;
  $("#region-select").value = region;
  $("#scope-display").textContent = packDirFor(region);
  $("#scope-roots").value = REGION_SCOPES[region];
  $("#ftp-label").textContent = `${region} FTP`;
  if (refresh) refreshConnections();
}

function setInputSource(source) {
  state.inputSource = source;
  selectSegment(document.querySelector(".input-source-control"), (button) => button.dataset.source === source);
  const manual = source !== "auto";
  $("#manual-input-wrap").classList.toggle("hidden", !manual);
  const labels = {
    commits: "提交记录（粘贴后自动提取版本号到 Revision 栏）",
    files: "指定 SVN 文件列表（按清单从本机根目录取文件打包）",
  };
  $("#manual-input-label").textContent = labels[source] || "";
  $("#manual-input").placeholder = source === "files"
    ? "M ServerBytes/Taiwan/Databin/Server/...\nA ServerBytes/Taiwan/Databin/Server/...\n（每行需包含 ServerBytes 锚点；文件内容从本机根目录读取，不从 SVN 拉取）"
    : "粘贴 SmartSVN 列表或 svn log 内容，例如：\n1738420\taovtool\t--bug=162484356 【B54-GRN-TW】...\t2026-08-18 17:45\t52\thttp://...\n1738350\taovtool\t--other=108 yyj\t2026-08-18 17:14\t3\thttp://...";
  // 文件列表模式不需要 Revision（按清单打包本机文件），隐藏 Revision 栏
  document.querySelector(".revision-input-wrap").classList.toggle("hidden", source === "files");
  // Revision 栏：commits 模式只读展示提取结果；输入版本号模式可编辑
  const revisionInput = $("#current-revision");
  const isCommits = source === "commits";
  revisionInput.readOnly = isCommits;
  revisionInput.classList.toggle("readonly", isCommits);
  revisionInput.placeholder = isCommits ? "由提交记录自动提取" : "r1699919,r1699997 · 可直接粘贴提交记录自动提取";
  // 切到「提交记录」时若框内已有内容，立即提取一次
  if (isCommits) applyRevisionPaste($("#manual-input").value);
}

function setRunStatus(label, status = "idle") {
  const badge = $("#run-badge");
  badge.textContent = label;
  badge.className = `run-badge ${status}`;
}

function resetStages() {
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
  if (current) current.querySelector("small").textContent = detail;
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

// 从粘贴的提交记录（SmartSVN 表格 / svn log）中提取版本号。
// 只识别三种行首形态，避免误吞日期（2026-08-18）等数字：
//   r1738420 ...          r 前缀（svn log 风格 "r1738420 | author | ..."）
//   1738420<TAB>...       纯数字 + 制表符（SmartSVN 列表复制的第一列）
//   1738420               整行只有一个数字（每行一个版本号的粘贴）
function extractRevisionsFromText(text) {
  const revisions = new Set();
  String(text || "").split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const match = trimmed.match(/^[rR](\d+)\b/) || trimmed.match(/^(\d{4,})(?=\t)/) || trimmed.match(/^(\d{4,})$/);
    if (match) revisions.add(Number(match[1]));
  });
  return [...revisions].sort((a, b) => a - b);
}

function applyRevisionPaste(text) {
  if (!/[\n\t]/.test(text || "")) return false;
  const revisions = extractRevisionsFromText(text);
  if (!revisions.length) return false;
  const spec = revisions.map((r) => `r${r}`).join(",");
  $("#current-revision").value = spec;
  if (spec !== state.lastExtractedSpec) {
    state.lastExtractedSpec = spec;
    const preview = revisions.length > 6
      ? [...revisions.slice(0, 3), "…", ...revisions.slice(-2)].map(String).join("、")
      : revisions.map((r) => `r${r}`).join("、");
    toast(`已从提交记录提取 ${revisions.length} 个版本号：${preview}`, "success");
    appendLog(`提交记录解析：提取 ${revisions.length} 个 Revision（${preview}）`);
  }
  return true;
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
  $("#commit-high-risk").value = settings.commit_high_risk || "";
  refreshListEditors();
  $("#baseline-revision").textContent = settings.last_external_revision_spec || "--";
  $("#baseline-time").textContent = formatDate(settings.last_external_time);
  setRegion(settings.package_region || "TW", { refresh: false });
  loadFtpForm(state.region);
  state.ruleNameOverrides = { ...(settings.rule_name_overrides || {}) };
  renderRuleToggles(settings.disabled_rule_ids);
}

// ---- 内容校验规则：注册表驱动的设置开关与动态标签 ----

function ruleSpecFor(key) {
  return state.validationRules.find((spec) => spec.type === key) || null;
}

function ruleLabel(key) {
  const spec = ruleSpecFor(key);
  if (spec && state.ruleNameOverrides[spec.id]) return state.ruleNameOverrides[spec.id];
  return (spec && spec.name) || RULE_CHECK_LABELS[key] || key;
}

function ruleOrderBadge(key) {
  const index = state.validationRules.findIndex((spec) => spec.type === key);
  return index >= 0 ? String(index + 1).padStart(2, "0") : "";
}

// ---- mac 风格列表编辑器（白名单/高危名单）：+ 添加、− 删除、双击编辑 ----
// 数据仍落在隐藏 textarea（每行一条），collectSettings / 匹配逻辑不变。

const listEditors = {};

function createListEditor(textareaId, containerId, placeholder) {
  const textarea = $(`#${textareaId}`);
  const container = $(`#${containerId}`);
  if (!textarea || !container) return;

  const list = el("div", "list-editor-rows");
  const bar = el("div", "list-editor-bar");
  const addBtn = el("button", "list-editor-btn", "+");
  addBtn.type = "button";
  addBtn.title = "添加一条";
  const removeBtn = el("button", "list-editor-btn", "−");
  removeBtn.type = "button";
  removeBtn.title = "删除选中";
  bar.append(addBtn, removeBtn);
  container.replaceChildren(list, bar);

  let selected = -1;
  const entries = () => textarea.value.split("\n").map((line) => line.trim()).filter(Boolean);
  const sync = (items) => { textarea.value = items.join("\n"); };

  const render = () => {
    const items = entries();
    if (selected >= items.length) selected = items.length - 1;
    list.replaceChildren(...items.map((text, i) => {
      const row = el("div", `list-editor-row${i === selected ? " selected" : ""}`, text);
      row.addEventListener("click", () => { selected = i; render(); });
      row.addEventListener("dblclick", () => startEdit(i));
      return row;
    }));
    removeBtn.disabled = selected < 0;
  };

  const startEdit = (index) => {
    const items = entries();
    const isNew = index >= items.length;
    const input = el("input", "list-editor-input");
    input.type = "text";
    input.value = isNew ? "" : items[index];
    input.placeholder = placeholder || "";
    const rowEl = el("div", "list-editor-row editing");
    rowEl.append(input);
    if (isNew) list.append(rowEl);
    else list.children[index].replaceWith(rowEl);
    input.focus();
    if (!isNew) input.select();
    let done = false;
    const finish = (commit) => {
      if (done) return;
      done = true;
      const value = input.value.trim();
      const next = entries();
      if (commit && value) {
        if (isNew) { next.push(value); selected = next.length - 1; }
        else { next[index] = value; selected = index; }
      }
      sync(next);
      render();
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      else if (event.key === "Escape") { event.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  };

  addBtn.addEventListener("click", () => startEdit(entries().length));
  removeBtn.addEventListener("click", () => {
    const items = entries();
    if (selected < 0 || selected >= items.length) return;
    items.splice(selected, 1);
    sync(items);
    render();
  });

  listEditors[textareaId] = { refresh: render };
  render();
}

function refreshListEditors() {
  Object.values(listEditors).forEach((editor) => editor.refresh());
}

function renderRuleToggles(disabledIds) {
  const box = $("#rule-toggles");
  if (!box) return;
  if (!state.validationRules.length) {
    box.replaceChildren(el("p", "empty-hint", "未获取到规则清单（桥接命令 list_validation_rules 不可用）。"));
    return;
  }
  const disabled = new Set(Array.isArray(disabledIds) ? disabledIds : []);
  box.replaceChildren(...state.validationRules.map((spec, index) => {
    const item = el("div", "rule-toggle-item");
    const row = el("div", "rule-toggle-row");
    row.append(el("span", "rule-toggle-index", String(index + 1).padStart(2, "0")));
    const label = el("label", "toggle-row");
    const input = el("input");
    input.type = "checkbox";
    input.dataset.ruleId = spec.id;
    input.checked = !disabled.has(spec.id);
    label.append(input);
    const nameText = el("span", "rule-toggle-name-text", state.ruleNameOverrides[spec.id] || spec.name || spec.id);
    const nameInput = el("input", "rule-toggle-name");
    nameInput.type = "text";
    nameInput.dataset.ruleId = spec.id;
    nameInput.dataset.defaultName = spec.name || spec.id;
    nameInput.value = nameText.textContent;
    nameInput.placeholder = spec.name || spec.id;
    nameInput.title = "可自定义规则显示名，保存后生效";
    nameInput.hidden = true;
    const renameBtn = el("button", "rule-rename-btn", "重命名");
    renameBtn.type = "button";
    renameBtn.title = "重命名规则显示名";
    const finishRename = (commit) => {
      if (nameInput.hidden) return;
      if (!commit) nameInput.value = nameText.textContent;
      const value = nameInput.value.trim() || nameInput.dataset.defaultName;
      nameInput.value = value;
      nameText.textContent = value;
      nameInput.hidden = true;
      nameText.hidden = false;
      renameBtn.hidden = false;
    };
    renameBtn.addEventListener("click", () => {
      nameText.hidden = true;
      renameBtn.hidden = true;
      nameInput.hidden = false;
      nameInput.focus();
      nameInput.select();
    });
    nameInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); finishRename(true); }
      else if (event.key === "Escape") { event.preventDefault(); finishRename(false); }
    });
    nameInput.addEventListener("blur", () => finishRename(true));
    label.append(nameText, nameInput, renameBtn);
    row.append(label);
    item.append(row, el("p", "rule-toggle-desc", spec.description || ""));
    return item;
  }));
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
    commit_high_risk: $("#commit-high-risk").value,
    backend_url: $("#backend-url").value.trim(),
    ftp_profiles: state.ftpProfiles,
    disabled_rule_ids: $$("#rule-toggles input[type=checkbox]")
      .filter((cb) => !cb.checked)
      .map((cb) => cb.dataset.ruleId),
    rule_name_overrides: $$("#rule-toggles input.rule-toggle-name")
      .filter((input) => input.value.trim() && input.value.trim() !== input.dataset.defaultName)
      .reduce((acc, input) => { acc[input.dataset.ruleId] = input.value.trim(); return acc; }, {}),
  };
}

function collectPackPayload() {
  const settings = collectSettings();
  // commits（提交记录提取）与 auto 一样走 svn CLI 自动拉 log；仅 files/manual 用粘贴内容
  const autoLog = state.inputSource === "auto" || state.inputSource === "commits";
  return {
    ...settings,
    region: state.region,
    current_revision_spec: $("#current-revision").value.trim(),
    input_method: state.inputSource === "files" ? "pasted_svn_file_list" : "revision_spec",
    svn_log_source: autoLog ? "auto" : "manual",
    input_text: $("#manual-input").value,
    svn_password: $("#svn-password").value,
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

function formatBytes(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "--";
  const units = ["B", "KB", "MB", "GB"];
  let current = size;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) { current /= 1024; index += 1; }
  return `${current.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function globToRegExp(pattern) {
  const escaped = pattern.trim().replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`, "i");
}

function highRiskPatterns() {
  return ($("#commit-high-risk").value || "")
    .split("\n").map((line) => line.trim()).filter(Boolean).map(globToRegExp);
}

function matchesRisk(patterns, entry) {
  const haystack = [entry.fixed_path, entry.table_name, entry.readable_name, entry.directory].filter(Boolean);
  return patterns.some((re) => haystack.some((text) => re.test(text)));
}

function renderBlockTags(selector, tags) {
  $(selector).replaceChildren(...tags.map((t) => el("span", `tag tag-${t.tone}`, t.label)));
}

function revisionSpan(revisions) {
  if (!Array.isArray(revisions) || !revisions.length) return "--";
  const sorted = [...revisions].sort((a, b) => a - b);
  return `r${sorted[0]}–r${sorted[sorted.length - 1]} · ${sorted.length} 个版本`;
}

function commitGroupRow(group) {
  const row = el("div", "commit-row");
  const main = el("div", "commit-row-main");
  main.append(el("p", "commit-row-name", group.readable || group.table));
  main.append(el("p", "commit-row-meta", `${group.directory || "--"} · ${group.revisionsLabel}`));
  row.append(main, el("span", "chip", `${group.count} 条`));
  return row;
}

function renderCommitCheck(report) {
  const check = report?.validation?.checks?.commit_record || {};
  const comparison = check.comparison || {};
  const warnings = Array.isArray(check.warnings) ? check.warnings : [];
  const ignored = Array.isArray(check.ignored_tables) ? check.ignored_tables : [];

  const files = Array.isArray(report?.files) ? report.files : [];
  $("#chip-packaged").textContent = files.filter((f) => f.status === "packaged").length || state.result?.success_count || 0;
  $("#chip-failed").textContent = files.filter((f) => f.status === "failed").length || state.result?.failure_count || 0;
  $("#chip-skipped").textContent = files.filter((f) => f.status === "skipped").length || state.result?.skipped_count || 0;

  const compare = $("#commit-compare");
  if (!check.status || check.status === "skipped") {
    compare.textContent = "间隔提交校验未执行（手动输入模式下仅校验本次文件列表）。";
  } else {
    compare.replaceChildren(
      document.createTextNode(`间隔提交校验：期望覆盖 ${comparison.expected_revision_spec || "--"} · 本次仅含 ${comparison.included_revision_spec || "--"} · `),
      (() => {
        const strong = el("strong", warnings.length ? "warn-text" : "ok-text",
          warnings.length ? `区间内有 ${warnings.length} 条改动未纳入本包` : "区间内无遗漏改动");
        return strong;
      })(),
    );
  }

  const groups = new Map();
  warnings.forEach((w) => {
    const key = w.table_name || w.readable_name || w.fixed_path || "未识别";
    if (!groups.has(key)) groups.set(key, { table: key, readable: w.readable_name || key, directory: w.directory || "", revisions: [], entries: [] });
    const g = groups.get(key);
    g.revisions.push(...(Array.isArray(w.revisions) ? w.revisions : []));
    g.entries.push(w);
  });
  const all = [...groups.values()].map((g) => ({ ...g, count: g.entries.length, revisionsLabel: revisionSpan(g.revisions) }));

  const patterns = highRiskPatterns();
  const high = patterns.length ? all.filter((g) => g.entries.some((e) => matchesRisk(patterns, e))) : [];
  const normal = all.filter((g) => !high.includes(g)).sort((a, b) => b.count - a.count);

  const highBox = $("#high-risk-box");
  highBox.classList.toggle("hidden", high.length === 0);
  $("#high-risk-groups").replaceChildren(...high.map(commitGroupRow));

  const groupsBox = $("#commit-groups");
  if (!normal.length && !high.length) {
    groupsBox.replaceChildren(el("p", "empty-hint", warnings.length ? "告警均已列入高危区" : "没有间隔提交告警"));
  } else {
    const renderGroup = (g) => {
      const item = el("details", "commit-group");
      const summary = el("summary", "commit-group-head");
      summary.append(el("span", "commit-group-name", g.table), el("span", "chip", String(g.count)));
      item.append(summary, commitGroupRow(g));
      return item;
    };
    const VISIBLE_GROUPS = 10;
    const top = normal.slice(0, VISIBLE_GROUPS);
    const rest = normal.slice(VISIBLE_GROUPS);
    const nodes = top.map(renderGroup);
    if (rest.length) {
      const restWarnings = rest.reduce((sum, g) => sum + g.count, 0);
      const fold = el("details", "low-risk-fold");
      const foldHead = el("summary", "low-risk-fold-head");
      foldHead.append(
        el("span", "", `其余 ${rest.length} 组低危改动`),
        el("span", "chip", `${restWarnings} 条`),
      );
      fold.append(foldHead, ...rest.map(renderGroup));
      nodes.push(fold);
    }
    groupsBox.replaceChildren(...nodes);
  }

  const whiteBox = $("#whitelist-box");
  const ignoredTotal = ignored.length;
  whiteBox.classList.toggle("hidden", ignoredTotal === 0);
  if (ignoredTotal) {
    $("#whitelist-summary").textContent = `已豁免（白名单）· ${ignoredTotal} 条`;
    $("#whitelist-groups").replaceChildren(...ignored.map((entry) =>
      commitGroupRow({ table: entry.table_name, readable: entry.readable_name || entry.table_name, directory: entry.directory, revisionsLabel: "", count: 0, entries: [entry] })));
  }

  const commitTags = [];
  if (high.length) commitTags.push({ label: `存在高危提交 · ${high.length} 组`, tone: "red" });
  if (!check.status || check.status === "skipped") {
    commitTags.push({ label: "间隔校验未执行", tone: "plain" });
  } else if (warnings.length) {
    commitTags.push({ label: `间隔告警 ${warnings.length} 条`, tone: "amber" });
  } else {
    commitTags.push({ label: "无间隔遗漏", tone: "green" });
  }
  if (ignoredTotal) commitTags.push({ label: `已豁免 ${ignoredTotal} 条`, tone: "plain" });
  renderBlockTags("#commit-block-tags", commitTags);
}

function bizItemName(item) {
  return item.name || item.skin?.name || item.hero?.name && `${item.hero.name} 相关` || item.object_id || "未命名对象";
}

function bizItemTags(item) {
  const tags = [];
  const direct = Array.isArray(item.changes) && item.changes.length > 0;
  tags.push({ label: direct ? "直接更新" : "关联影响", tone: direct ? "dark" : "plain" });
  if (Array.isArray(item.promotions) && item.promotions.length) tags.push({ label: "促销特卖", tone: "amber" });
  if (Array.isArray(item.unresolved_references) && item.unresolved_references.length) tags.push({ label: "未解读变更", tone: "amber" });
  return tags;
}

function openObjDrawer(moduleName, item) {
  $("#obj-drawer-title").textContent = `${moduleName} · ${bizItemName(item)}`;
  $("#obj-drawer-sub").textContent = item.object_id || "";
  const body = $("#obj-drawer-body");
  const sections = [];

  const tagRow = el("div", "tag-row");
  bizItemTags(item).forEach((t) => tagRow.append(el("span", `tag tag-${t.tone}`, t.label)));
  sections.push(tagRow);

  if (item.summary) sections.push(el("p", "obj-summary", item.summary));

  if (Array.isArray(item.changes) && item.changes.length) {
    const box = el("div");
    box.append(el("p", "obj-section-title", "变更明细"));
    item.changes.forEach((c) => {
      const card = el("div", "change-card");
      card.append(el("p", "change-card-head", `${c.file_name || "--"} · ${c.sheet || "--"}`));
      const typeLabel = { added: "新增", modified: "修改", deleted: "删除" }[c.change_type] || c.change_type || "变更";
      card.append(el("p", "change-card-meta", `主键 ${typeof c.business_key === "string" ? c.business_key : JSON.stringify(c.business_key || "--")} · ${typeLabel} · ${revisionSpan(c.revisions).split(" · ")[0]}`));
      box.append(card);
    });
    sections.push(box);
  }

  if (item.current_state && typeof item.current_state === "object" && Object.keys(item.current_state).length) {
    const box = el("div");
    box.append(el("p", "obj-section-title", "当前状态"));
    const list = el("div", "state-list");
    Object.entries(item.current_state).slice(0, 12).forEach(([k, v]) => {
      const row = el("div", "state-row");
      row.append(el("span", "", k), el("strong", "", typeof v === "object" ? JSON.stringify(v) : String(v)));
      list.append(row);
    });
    box.append(list);
    sections.push(box);
  }

  if (Array.isArray(item.unresolved_references) && item.unresolved_references.length) {
    const box = el("div");
    box.append(el("p", "obj-section-title warn-text", "未解读引用"));
    item.unresolved_references.slice(0, 8).forEach((u) => box.append(el("p", "obj-unresolved", typeof u === "string" ? u : JSON.stringify(u))));
    sections.push(box);
  }

  body.replaceChildren(...sections);
  $("#obj-drawer").classList.remove("hidden");
  $("#obj-drawer-backdrop").classList.remove("hidden");
}

function closeObjDrawer() {
  $("#obj-drawer").classList.add("hidden");
  $("#obj-drawer-backdrop").classList.add("hidden");
}

function renderModuleGroups(moduleAnalysis) {
  const box = $("#module-groups");
  const modules = Array.isArray(moduleAnalysis?.modules) ? moduleAnalysis.modules : [];
  if (!modules.length) {
    box.replaceChildren(el("p", "empty-hint", "本次没有识别到可解读的业务内容。"));
    renderBlockTags("#content-block-tags", [{ label: "无可解读内容", tone: "plain" }]);
    return;
  }
  const totalItems = modules.reduce((sum, m) => sum + Number(m.item_count || (Array.isArray(m.items) ? m.items.length : 0)), 0);
  const totalUnresolved = modules.reduce((sum, m) => sum + (Array.isArray(m.items) ? m.items : [])
    .filter((it) => Array.isArray(it.unresolved_references) && it.unresolved_references.length).length, 0);
  const hasAnyRisk = totalUnresolved > 0 || modules.some((m) => m.status && m.status !== "interpreted");
  renderBlockTags("#content-block-tags", [
    { label: `${modules.length} 个模块 · ${totalItems} 个对象`, tone: "plain" },
    hasAnyRisk
      ? { label: `存在风险 · ${totalUnresolved} 处未解读`, tone: "amber" }
      : { label: "整体无风险", tone: "green" },
  ]);
  box.replaceChildren(...modules.map((m) => {
    const items = Array.isArray(m.items) ? m.items : [];
    const riskCount = items.filter((it) => Array.isArray(it.unresolved_references) && it.unresolved_references.length).length;
    const hasRisk = riskCount > 0 || (m.status && m.status !== "interpreted");
    const count = Number(m.item_count || items.length);

    const wrap = el("details", "module-group");
    if (hasRisk) wrap.open = true;
    const head = el("summary", "module-group-head");
    head.append(
      el("span", "module-group-name", m.name || m.module || "未分组"),
      el("span", "module-group-count", `${count} 个`),
      el("span", "module-group-break", `${m.matched_change_count ?? items.length} 处变更`),
      el("span", `tag ${hasRisk ? "tag-amber" : "tag-green"}`, hasRisk ? `有风险 · ${riskCount} 处未解读` : "整体无风险"),
    );
    wrap.append(head);
    items.forEach((item) => {
      const row = el("div", "biz-row");
      const main = el("div", "biz-row-main");
      const title = el("p", "biz-row-title");
      title.append(el("strong", "", bizItemName(item)), el("code", "", item.object_id || ""));
      main.append(title);
      if (item.hero?.name) main.append(el("p", "biz-row-sub", `英雄：${item.hero.name}`));
      if (item.summary) main.append(el("p", "biz-row-sub", item.summary));
      const tagRow = el("div", "tag-row");
      bizItemTags(item).forEach((t) => tagRow.append(el("span", `tag tag-${t.tone}`, t.label)));
      main.append(tagRow);
      const btn = el("button", "quiet-button small", "详情");
      btn.type = "button";
      btn.addEventListener("click", () => openObjDrawer(m.name || m.module, item));
      row.append(main, btn);
      wrap.append(row);
    });
    if (!items.length) wrap.append(el("p", "empty-hint", "该模块无对象级明细"));
    return wrap;
  }));
}

function renderFileTable(files) {
  const rows = (Array.isArray(files) ? files : []).map((f) => {
    const tr = el("tr");
    const statusLabel = { packaged: "已打包", failed: "失败", skipped: "已跳过" }[f.status] || f.status || "--";
    tr.append(
      el("td", "mono", f.action || "--"),
      el("td", "mono path-cell", f.fixed_path || f.archive_path || "--"),
      el("td", "mono", formatBytes(f.size)),
      (() => { const td = el("td"); td.append(el("span", `tag ${f.status === "packaged" ? "tag-green" : f.status === "failed" ? "tag-red" : "tag-plain"}`, statusLabel)); return td; })(),
    );
    return tr;
  });
  $("#file-table-body").replaceChildren(...rows);
}

const RULE_CHECK_LABELS = {
  skin_precheck: "皮肤促销窗口预检",
  hidden_item_listing: "隐藏道具识别",
  expiry_time_cross_check: "有效期关联校验",
  skin_sale_change_check: "皮肤售卖方式校验",
  package_completeness: "包完整性（手动清单）",
};

const RULE_REASON_LABELS = {
  missing_check_window: "未配置检查窗口（设置页 05 打包策略可配）",
  no_rules: "未启用规则集",
  missing_validation_config: "未启用内容校验",
  content_check_disabled: "规则未启用",
  package_not_touch_item_module: "本次未涉及道具模块",
  package_not_touch_skin_module: "本次未涉及皮肤模块",
  no_item_table_change: "本次提交未变更道具信息表",
  no_skin_table_change: "本次提交未变更皮肤上下架/促销表",
  changeset_unavailable: "ChangeSet 不可用，按「只校验提交内容」原则跳过",
  svn_mode_covered_by_commit_record: "SVN 模式已由提交校验覆盖",
  missing_tdr_root: "缺少 TdrTable 根目录配置",
  missing_dtxml: "找不到规则所需 dtxml 文件",
  unreadable_dtxml: "dtxml 读取失败",
};

const ACTIVITY_SOURCE_LABELS = {
  reward_exchange_chain: "奖励/兑换链",
  token_progress_chain: "token 进度链",
  ilua_chain: "ilua 聚合链",
  activity_id_column: "活动ID 直查",
  manual_activity_windows: "人工排期表",
};

function activitySourceTags(sources) {
  return (Array.isArray(sources) ? sources : []).map((s) => ACTIVITY_SOURCE_LABELS[s] || s).join(" · ");
}

function ruleCheckRow(key, result) {
  const status = result.status || "skipped";
  const statusLabel = { passed: "通过", warning: "有告警", error: "错误", skipped: "未执行", confirm: "待确认" }[status] || status;
  const tone = status === "passed" ? "green" : status === "skipped" ? "plain" : status === "warning" ? "amber" : status === "error" ? "red" : "amber";
  const row = el("div", "rule-row");
  const side = el("div", "rule-row-side");
  const main = el("div", "rule-row-main");
  const orderBadge = ruleOrderBadge(key);
  main.append(el("p", "rule-row-name", (orderBadge ? `${orderBadge} · ` : "") + ruleLabel(key)));
  const reasonText = RULE_REASON_LABELS[result.reason] || result.reason || "";
  const itemCount = Array.isArray(result.items) ? result.items.length : 0;
  const warnCount = Array.isArray(result.warnings) ? result.warnings.length : 0;
  const subParts = [reasonText || `${itemCount} 个对象 · ${warnCount} 条告警`];
  if (result.activity_resolution) {
    subParts.push(result.activity_resolution === "module_index" ? "活动时间来源：关联链自动解析" : "活动时间来源：仅人工排期表");
  }
  if (result.scope === "changeset" && Array.isArray(result.scope_ids) && result.scope_ids.length) {
    subParts.push(`校验范围：${result.scope_ids.length} 个变更道具`);
  }
  const passedCount = Array.isArray(result.passed_items) ? result.passed_items.length : 0;
  if (passedCount) {
    subParts.push(`自动通过 ${passedCount} 个`);
  }
  main.append(el("p", "rule-row-sub", subParts.join(" · ")));
  if (warnCount) {
    const list = el("ul", "rule-warnings");
    result.warnings.slice(0, 10).forEach((w) => list.append(el("li", "", typeof w === "string" ? w : w.message || JSON.stringify(w))));
    main.append(list);
  }
  if (key === "expiry_time_cross_check") {
    const renderExpiryTable = (entries, verdictFor) => {
      const table = el("table", "file-table rule-item-table");
      const thead = el("thead");
      const headRow = el("tr");
      ["道具 ID", "名称", "expire_time", "结论", "关联活动", "来源"].forEach((h) => headRow.append(el("th", "", h)));
      thead.append(headRow);
      const tbody = el("tbody");
      entries.forEach((entry) => {
        const acts = Array.isArray(entry.activities) ? entry.activities : [];
        const actText = acts.length
          ? acts.map((a) => `${a.activity_id}${a.activity_name ? `（${a.activity_name}）` : ""} ${a.activity_start_time || ""}~${a.activity_end_time || ""}`.trim()).join("\n")
          : String(entry.activity_id || "--");
        const srcText = acts.length ? acts.map((a) => activitySourceTags(a.sources)).filter(Boolean).join("\n") : "--";
        const tr = el("tr");
        tr.append(
          el("td", "mono", String(entry.item_id || "--")),
          el("td", "", String(entry.name || "--")),
          el("td", "mono", String(entry.expire_time || "--")),
          el("td", "", verdictFor(entry)),
          el("td", "mono", actText || "--"),
          el("td", "", srcText || "--"),
        );
        tbody.append(tr);
      });
      table.append(thead, tbody);
      return table;
    };
    const detailEntries = [...(result.warnings || []), ...(result.items || [])].filter((entry) => entry && typeof entry === "object" && (entry.item_id || entry.activities));
    if (detailEntries.length) {
      const detail = el("details", "rule-items");
      detail.append(el("summary", "", `有效期校验明细 · ${detailEntries.length} 条`));
      detail.append(renderExpiryTable(detailEntries, (entry) => entry.level === "warning"
        ? (entry.type === "expiry_before_activity_start" ? "早于活动开始" : "落在活动期间")
        : "待人工核对"));
      main.append(detail);
    }
    const passedItems = (Array.isArray(result.passed_items) ? result.passed_items : []).filter((entry) => entry && typeof entry === "object");
    if (passedItems.length) {
      const passedDetail = el("details", "rule-items");
      passedDetail.append(el("summary", "", `已通过 · ${passedItems.length} 个（有效期晚于活动结束，自动判定）`));
      passedDetail.append(renderExpiryTable(passedItems, () => "自动通过"));
      main.append(passedDetail);
    }
  }
  if (key === "hidden_item_listing" && itemCount) {
    const detail = el("details", "rule-items");
    detail.append(el("summary", "", `隐藏道具清单 · ${itemCount} 个`));
    const table = el("table", "file-table rule-item-table");
    const thead = el("thead");
    const headRow = el("tr");
    ["道具 ID", "名称", "关联活动", "expire_time"].forEach((h) => headRow.append(el("th", "", h)));
    thead.append(headRow);
    const tbody = el("tbody");
    result.items.forEach((item) => {
      const tr = el("tr");
      tr.append(
        el("td", "mono", String(item.item_id || "--")),
        el("td", "", String(item.name || "--")),
        el("td", "mono", String(item.linked_activity || "--")),
        el("td", "mono", String(item.expire_time || "--")),
      );
      tbody.append(tr);
    });
    table.append(thead, tbody);
    detail.append(table);
    main.append(detail);
  }
  // 通用明细表：未定制渲染的注册规则，按注册表 detail_columns（或自动推导列）展示 items
  const CUSTOM_DETAIL_RULES = new Set(["expiry_time_cross_check", "hidden_item_listing"]);
  if (!CUSTOM_DETAIL_RULES.has(key) && itemCount) {
    const items = (result.items || []).filter((it) => it && typeof it === "object");
    if (items.length) {
      const spec = ruleSpecFor(key);
      const declared = spec && Array.isArray(spec.detail_columns) ? spec.detail_columns.filter((c) => c && c.key) : [];
      const columns = declared.length
        ? declared
        : Object.keys(items[0]).filter((k) => !["type", "level"].includes(k)).slice(0, 6).map((k) => ({ key: k, label: k }));
      const detail = el("details", "rule-items");
      detail.append(el("summary", "", `明细 · ${items.length} 条`));
      const table = el("table", "file-table rule-item-table");
      const thead = el("thead");
      const headRow = el("tr");
      columns.forEach((c) => headRow.append(el("th", "", c.label || c.key)));
      thead.append(headRow);
      const tbody = el("tbody");
      items.forEach((item) => {
        const tr = el("tr");
        columns.forEach((c) => tr.append(el("td", "mono", item[c.key] === undefined || item[c.key] === "" ? "--" : String(item[c.key]))));
        tbody.append(tr);
      });
      table.append(thead, tbody);
      detail.append(table);
      main.append(detail);
    }
  }
  row.append(main, side);
  side.append(el("span", `tag tag-${tone}`, statusLabel));
  if (status === "confirm") {
    const ack = el("label", "rule-ack");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.acknowledged.has(key);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.acknowledged.add(key);
      } else {
        state.acknowledged.delete(key);
      }
      updateArchiveGate();
    });
    ack.append(checkbox, document.createTextNode("已人工确认"));
    side.append(ack);
  }
  return row;
}

function confirmRuleEntries() {
  const checks = state.result?.report?.validation?.checks || {};
  return Object.entries(checks).filter(([key, value]) => key !== "commit_record" && value && typeof value === "object" && value.status === "confirm");
}

function updateArchiveGate() {
  if (!state.result) return;
  const pending = confirmRuleEntries().filter(([key]) => !state.acknowledged.has(key));
  $("#confirm-archive").disabled = !state.result.can_archive || pending.length > 0;
  const hint = $("#archive-gate-hint");
  if (state.result.can_archive && pending.length) {
    hint.textContent = `还有 ${pending.length} 条规则待人工确认`;
    hint.classList.remove("hidden");
  } else {
    hint.textContent = "";
    hint.classList.add("hidden");
  }
}

function renderRuleChecks(checks) {
  const box = $("#rule-checks");
  const entries = Object.entries(checks || {}).filter(([key, value]) => key !== "commit_record" && value && typeof value === "object");
  if (!entries.length) {
    box.replaceChildren(el("p", "empty-hint", "没有规则校验结果。"));
    renderBlockTags("#rules-block-tags", [{ label: "无规则结果", tone: "plain" }]);
    return;
  }
  box.replaceChildren(...entries.map(([key, value]) => ruleCheckRow(key, value)));
  const worst = entries.some(([, v]) => v.status === "error") ? { label: "存在错误", tone: "red" }
    : entries.some(([, v]) => v.status === "warning") ? { label: "存在告警", tone: "amber" }
    : entries.some(([, v]) => v.status === "confirm") ? { label: "有待确认项", tone: "amber" }
    : entries.every(([, v]) => v.status === "skipped") ? { label: "全部未执行", tone: "plain" }
    : { label: "全部通过", tone: "green" };
  renderBlockTags("#rules-block-tags", [{ label: `${entries.length} 条规则`, tone: "plain" }, worst]);
}

function renderResult(result) {
  state.result = result;
  state.acknowledged = new Set();
  const report = result.report || {};
  const overview = result.module_overview || report?.module_analysis?.overview || {};

  $("#result-section").classList.remove("hidden");
  $("#result-package").textContent = result.package_name;
  $("#result-md5").textContent = `MD5 ${result.md5}`;
  $("#result-files").textContent = result.success_count;
  $("#result-warnings").textContent = result.validation.warning_count;
  $("#result-errors").textContent = result.validation.error_count + result.failure_count;
  const status = $("#result-status");
  status.textContent = result.can_archive ? "待人工确认" : "禁止归档";
  status.className = `result-status ${result.can_archive ? "" : "error"}`;

  const lines = Array.isArray(overview.display_lines) && overview.display_lines.length
    ? overview.display_lines
    : ["本次未产生可总结的内容变化"];
  $("#summary-lines").replaceChildren(...lines.map((line) => el("li", "", line)));

  renderCommitCheck(report);
  renderModuleGroups(report.module_analysis);
  renderFileTable(report.files);
  renderRuleChecks(report.validation?.checks);
  updateArchiveGate();
  $("#result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---- 演示模式（Showcase）：本地克隆 + 场景注入，不访问 SVN ----

async function loadShowcaseStatus() {
  const box = $("#showcase-scenes");
  if (!box) return;
  try {
    const status = await window.aov.request("showcase_status");
    state.showcaseWorkspace = status.workspace || "";
    $("#showcase-workspace").textContent = status.workspace || "--";
    $("#showcase-state").textContent = status.initialized ? "已初始化" : "未初始化";
    if (status.initialized) loadEditorTables();
    const scenes = status.initialized
      ? (Array.isArray(status.scenes) ? status.scenes : [])
      : (status.scene_catalog || []).map((s) => ({ ...s, applied: null }));
    box.replaceChildren(...scenes.map((scene) => {
      const row = el("div", "scene-row");
      const badge = scene.applied === true ? el("span", "tag tag-green", "已注入")
        : scene.applied === false ? el("span", "tag tag-red", "未生效")
        : el("span", "tag tag-plain", "待初始化");
      const main = el("div", "scene-main");
      main.append(el("p", "scene-title", scene.title || scene.id));
      main.append(el("p", "scene-desc", scene.description || ""));
      if (scene.detail) main.append(el("p", "scene-detail", scene.detail));
      row.append(badge, main);
      return row;
    }));
  } catch (error) {
    box.replaceChildren(el("p", "empty-hint", error.message));
  }
}

async function initShowcase() {
  if (state.busy) return;
  state.busy = true;
  $("#init-showcase").disabled = true;
  try {
    await window.aov.request("init_showcase", { reset: true });
    toast("演示数据已就绪（已应用全部演示场景）", "success");
    await loadShowcaseStatus();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.busy = false;
    $("#init-showcase").disabled = false;
  }
}

async function runShowcase() {
  if (state.busy) return;
  state.busy = true;
  $("#run-showcase").disabled = true;
  clearLog();
  resetStages();
  setRunStatus("演示执行中", "running");
  activateStage("packaging", "执行中");
  showView("pack");
  try {
    const result = await window.aov.request("run_showcase", {
      baseline_revision: $("#showcase-baseline").value.trim(),
      current_revision_spec: $("#showcase-current").value.trim(),
    });
    activateStage("review", "演示完成");
    setRunStatus("演示完成", "success");
    appendLog("演示校验完成（演示结果不可归档）", "success");
    renderResult(result);
    toast("演示校验完成", "success");
  } catch (error) {
    setRunStatus("失败", "error");
    appendLog(error.message, "error");
    toast(error.message, "error");
  } finally {
    state.busy = false;
    $("#run-showcase").disabled = false;
  }
}

// ---- 行编辑器（Showcase 阶段二）----

function editorState() {
  if (!state.editor) state.editor = { table: "", sheet: "", columns: [], rows: [], selected: -1 };
  return state.editor;
}

async function loadEditorTables() {
  const select = $("#editor-table");
  if (!select) return;
  try {
    const result = await window.aov.request("showcase_tables");
    const tables = Array.isArray(result.tables) ? result.tables : [];
    select.replaceChildren(
      el("option", "", "选择表…"),
      ...tables.map((t) => {
        const option = el("option", "", t.file_name);
        option.value = t.file_name;
        return option;
      }),
    );
    select.querySelector("option").value = "";
  } catch (error) {
    select.replaceChildren(el("option", "", "加载失败"));
  }
}

async function loadEditorSheets() {
  const editor = editorState();
  const select = $("#editor-sheet");
  editor.sheet = "";
  editor.rows = [];
  editor.selected = -1;
  renderEditorRows();
  renderEditorForm();
  if (!editor.table) {
    select.replaceChildren(el("option", "", "选择 Sheet…"));
    return;
  }
  try {
    const result = await window.aov.request("showcase_sheets", { table: editor.table });
    const sheets = Array.isArray(result.sheets) ? result.sheets : [];
    select.replaceChildren(
      el("option", "", "选择 Sheet…"),
      ...sheets.map((s) => {
        const option = el("option", "", `${s.name}（${s.row_count} 行）`);
        option.value = s.name;
        return option;
      }),
    );
    select.querySelector("option").value = "";
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadEditorRows() {
  const editor = editorState();
  if (!editor.table || !editor.sheet) return;
  try {
    const result = await window.aov.request("showcase_rows", {
      table: editor.table,
      sheet: editor.sheet,
      keyword: $("#editor-search").value.trim(),
      limit: 200,
    });
    editor.columns = result.columns || [];
    editor.rows = result.rows || [];
    editor.selected = -1;
    renderEditorRows();
    renderEditorForm();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderEditorRows() {
  const editor = editorState();
  const box = $("#editor-rows");
  if (!editor.rows.length) {
    box.replaceChildren(el("p", "empty-hint", editor.sheet ? "没有匹配的行" : "先选择表与 Sheet"));
    return;
  }
  box.replaceChildren(...editor.rows.map((row) => {
    const item = el("div", `row-item${row.index === editor.selected ? " selected" : ""}`);
    item.append(el("span", "row-item-key", row.key || `#${row.index}`));
    item.append(el("span", "row-item-label", row.label || ""));
    item.addEventListener("click", () => {
      editor.selected = row.index;
      renderEditorRows();
      renderEditorForm();
    });
    return item;
  }));
}

function renderEditorForm() {
  const editor = editorState();
  const box = $("#editor-form");
  const row = editor.rows.find((r) => r.index === editor.selected);
  if (!row) {
    box.replaceChildren(el("p", "empty-hint", "从左侧选择一行进行编辑"));
    return;
  }
  const form = el("div", "row-form-fields");
  editor.columns.forEach((column) => {
    const label = el("label", "row-field");
    label.append(el("span", "", column));
    const input = el("input");
    input.type = "text";
    input.value = row.cells[column] || "";
    input.dataset.column = column;
    label.append(input);
    form.append(label);
  });
  const actions = el("div", "row-form-actions");
  const saveBtn = el("button", "primary-button", "保存修改");
  saveBtn.type = "button";
  saveBtn.addEventListener("click", saveEditorRow);
  const addBtn = el("button", "quiet-button", "以此为模板新增行");
  addBtn.type = "button";
  addBtn.addEventListener("click", addEditorRow);
  const deleteBtn = el("button", "quiet-button danger", "删除此行");
  deleteBtn.type = "button";
  deleteBtn.addEventListener("click", deleteEditorRow);
  actions.append(saveBtn, addBtn, deleteBtn);
  box.replaceChildren(form, actions);
}

async function saveEditorRow() {
  const editor = editorState();
  const row = editor.rows.find((r) => r.index === editor.selected);
  if (!row) return;
  const changes = {};
  $$("#editor-form input").forEach((input) => {
    if (input.value !== (row.cells[input.dataset.column] || "")) changes[input.dataset.column] = input.value;
  });
  if (!Object.keys(changes).length) {
    toast("没有改动", "info");
    return;
  }
  try {
    await window.aov.request("showcase_update_row", {
      table: editor.table, sheet: editor.sheet, row_index: editor.selected, changes,
    });
    toast(`已保存 ${Object.keys(changes).length} 个字段`, "success");
    await loadEditorRows();
    editor.selected = row.index;
    renderEditorRows();
    renderEditorForm();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function deleteEditorRow() {
  const editor = editorState();
  const row = editor.rows.find((r) => r.index === editor.selected);
  if (!row) return;
  if (!window.confirm(`确认删除行 ${row.key || editor.selected}（${row.label || "无名称"}）？只影响演示副本。`)) return;
  try {
    await window.aov.request("showcase_delete_row", {
      table: editor.table, sheet: editor.sheet, row_index: editor.selected,
    });
    toast("已删除（演示副本）", "success");
    await loadEditorRows();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function addEditorRow() {
  const editor = editorState();
  const row = editor.rows.find((r) => r.index === editor.selected);
  if (!row) return;
  try {
    const result = await window.aov.request("showcase_add_row", {
      table: editor.table, sheet: editor.sheet, row_index: editor.selected,
    });
    toast(`已复制新增行 #${result.row_index}，请修改关键字段后保存`, "success");
    await loadEditorRows();
    editor.selected = result.row_index;
    renderEditorRows();
    renderEditorForm();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function startPack() {
  if (state.busy) return;
  if (state.inputSource === "commits" && !$("#current-revision").value.trim()) {
    toast("请先在下方粘贴提交记录，未提取到版本号", "error");
    appendLog("提交记录校验失败：粘贴后未提取到 Revision，请检查格式（行首需为版本号）。", "error");
    return;
  }
  if (state.inputSource === "files") {
    const lines = $("#manual-input").value.split("\n").filter((line) => line.trim());
    const hits = lines.filter((line) => line.includes("ServerBytes")).length;
    if (lines.length && hits === 0) {
      toast("未解析到有效路径：每行需包含 ServerBytes 锚点，例如 M ServerBytes/Taiwan/Databin/...", "error");
      appendLog("文件列表校验失败：没有一行包含 ServerBytes 锚点，请检查输入格式。", "error");
      return;
    }
    if (hits < lines.length) {
      appendLog(`提示：${lines.length - hits} 行不含 ServerBytes 锚点，将被跳过。`, "warning");
    }
  }
  state.busy = true;
  $("#start-pack").disabled = true;
  $("#result-section").classList.add("hidden");
  clearLog();
  resetStages();
  setRunStatus("执行中", "running");
  activateStage(state.inputSource === "auto" || state.inputSource === "commits" ? "svn" : "packaging", "执行中");
  appendLog(`区域 ${state.region} · ${$("#current-revision").value.trim() || "未填写 Revision"}`);
  try {
    const result = await window.aov.request("pack", collectPackPayload());
    activateStage("review", "等待人工确认");
    setRunStatus("已完成", "success");
    appendLog(`打包完成：${result.package_name}`, "success");
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
    const acknowledgedAt = new Date().toISOString();
    const acknowledgments = confirmRuleEntries()
      .filter(([key]) => state.acknowledged.has(key))
      .map(([key, value]) => ({ type: key, name: String(value.name || ruleLabel(key)), acknowledged_at: acknowledgedAt }));
    const result = await window.aov.request("publish", {
      region: state.region,
      policy,
      backend_token: $("#backend-token").value,
      acknowledgments,
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
    updateArchiveGate();
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
  createListEditor("commit-whitelist", "commit-whitelist-editor", "*/Databin/Server/Item/*");
  createListEditor("commit-high-risk", "commit-high-risk-editor", "*/Databin/Server/Shop/*");
  $("#init-showcase").addEventListener("click", initShowcase);
  $("#run-showcase").addEventListener("click", runShowcase);
  $("#open-showcase-dir").addEventListener("click", () => {
    if (state.showcaseWorkspace) window.aov.openPath(state.showcaseWorkspace);
  });
  $("#editor-table").addEventListener("change", (event) => {
    editorState().table = event.target.value;
    loadEditorSheets();
  });
  $("#editor-sheet").addEventListener("change", (event) => {
    editorState().sheet = event.target.value;
    loadEditorRows();
  });
  let editorSearchTimer = null;
  $("#editor-search").addEventListener("input", () => {
    clearTimeout(editorSearchTimer);
    editorSearchTimer = setTimeout(loadEditorRows, 300);
  });
  $("#region-select").addEventListener("change", (event) => setRegion(event.target.value));
  $("#local-root").addEventListener("input", () => { $("#scope-display").textContent = packDirFor(state.region); });
  $$(".input-source-control button").forEach((button) => button.addEventListener("click", () => setInputSource(button.dataset.source)));
  // Revision 框支持直接粘贴提交记录（SmartSVN 表格 / svn log），自动提取版本号
  $("#current-revision").addEventListener("paste", (event) => {
    const text = event.clipboardData ? event.clipboardData.getData("text") : "";
    if (applyRevisionPaste(text)) event.preventDefault();
  });
  $("#current-revision").addEventListener("change", (event) => applyRevisionPaste(event.target.value));
  // 提交记录输入框：内容变化时实时提取版本号到 Revision 栏
  $("#manual-input").addEventListener("input", (event) => {
    if (state.inputSource === "commits") applyRevisionPaste(event.target.value);
  });
  $$("#ftp-region-control button").forEach((button) => button.addEventListener("click", () => {
    storeFtpForm();
    loadFtpForm(button.dataset.ftpRegion);
  }));
  $$('[data-browse]').forEach((button) => button.addEventListener("click", async () => {
    const selected = await window.aov.selectDirectory();
    if (selected) $(`#${button.dataset.browse}`).value = selected;
  }));
  $("#start-pack").addEventListener("click", startPack);
  $("#confirm-archive").addEventListener("click", confirmArchive);
  $("#open-output").addEventListener("click", () => state.result && window.aov.openPath(state.result.output_dir));
  $("#open-report").addEventListener("click", () => state.result && window.aov.openPath(state.result.report_path));
  $("#refresh-status").addEventListener("click", refreshConnections);
  $("#test-backend").addEventListener("click", () => checkBackend());
  $("#test-ftp").addEventListener("click", () => checkFtp({ useForm: true }));
  $("#settings-form").addEventListener("submit", saveSettings);
  $$("#content-tabs button").forEach((button) => button.addEventListener("click", () => {
    selectSegment($("#content-tabs"), (item) => item === button);
    $("#module-groups").classList.toggle("hidden", button.dataset.tab !== "objects");
    $("#file-table-wrap").classList.toggle("hidden", button.dataset.tab !== "files");
  }));
  $("#obj-drawer-close").addEventListener("click", closeObjDrawer);
  $("#obj-drawer-backdrop").addEventListener("click", closeObjDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#obj-drawer").classList.contains("hidden")) closeObjDrawer();
  });
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter" && state.view === "pack") startPack();
  });
  window.aov.onBridgeEvent((message) => {
    if (message.event === "log") appendLog(message.data.message, message.data.level);
    if (message.event === "progress") updateUploadProgress(message.data);
    if (message.event === "stage") {
      const stageMap = { packaging: "packaging", preflight: "archive", ftp_upload: "archive", backend_archive: "archive", complete: "archive" };
      const labels = { preflight: "复核 Report", ftp_upload: "FTP 上传中", backend_archive: "同步网页后端", complete: "完成归档" };
      activateStage(stageMap[message.data.stage] || "packaging", labels[message.data.stage] || "执行中");
      if (message.data.stage === "ftp_upload") $("#upload-progress").classList.remove("hidden");
    }
  });
  window.aov.onBridgeError(({ message }) => appendLog(message, "error"));
}

async function bootstrap() {
  bindEvents();
  setInputSource("commits");
  // 先取规则注册表元数据（设置页开关 + 规则行名称的数据源），失败不阻塞启动
  try {
    const rulesResult = await window.aov.request("list_validation_rules");
    state.validationRules = Array.isArray(rulesResult.rules) ? rulesResult.rules : [];
  } catch (_error) {
    state.validationRules = [];
  }
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
