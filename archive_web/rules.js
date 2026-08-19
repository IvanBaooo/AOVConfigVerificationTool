const ruleUi = {
  dashboardNav: document.querySelector("#nav-dashboard"), archiveNav: document.querySelector("#nav-archives"), rulesNav: document.querySelector("#nav-rules"),
  dashboardView: document.querySelector("#dashboard-view"), archiveView: document.querySelector("#archive-view"), rulesView: document.querySelector("#rules-view"),
  pageKicker: document.querySelector("#page-kicker"), pageTitle: document.querySelector("#page-title"),
  archiveRefresh: document.querySelector("#refresh-button"), refresh: document.querySelector("#rules-refresh"),
  newDraft: document.querySelector("#rules-new-draft"), caption: document.querySelector("#rules-caption"),
  notice: document.querySelector("#rules-notice"), history: document.querySelector("#rules-history-list"),
  historyCount: document.querySelector("#rules-history-count"), historyEmpty: document.querySelector("#rules-history-empty"),
  editorTitle: document.querySelector("#rules-editor-title"), editorMode: document.querySelector("#rules-editor-mode"),
  editorState: document.querySelector("#rules-editor-state"), ruleSetId: document.querySelector("#rule-set-id"),
  version: document.querySelector("#rule-version"), notes: document.querySelector("#rule-notes"),
  scopes: document.querySelector("#rule-scope-switch"), mappingRows: document.querySelector("#mapping-rows"),
  mappingEmpty: document.querySelector("#mapping-empty"), whitelistRows: document.querySelector("#whitelist-rows"),
  whitelistEmpty: document.querySelector("#whitelist-empty"), addMapping: document.querySelector("#add-mapping"),
  addWhitelist: document.querySelector("#add-whitelist"), contentRows: document.querySelector("#content-check-rows"),
  contentEmpty: document.querySelector("#content-check-empty"), contentCount: document.querySelector("#content-check-count"),
  addContent: document.querySelector("#add-content-check"),
  added: document.querySelector("#change-added"),
  updated: document.querySelector("#change-updated"), removed: document.querySelector("#change-removed"),
  errors: document.querySelector("#change-errors"), publish: document.querySelector("#publish-rules"),
  dialog: document.querySelector("#publish-rule-dialog"), dialogForm: document.querySelector("#publish-rule-form"),
  dialogSummary: document.querySelector("#publish-rule-summary"),
};

const RULE_SCOPES = ["common", "TW", "TH", "VN", "ID"];
const RULE_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const ruleState = { items: [], selected: null, baseline: null, draft: null, scope: "common", loading: false, publishing: false };

function cloneRule(value) { return value ? JSON.parse(JSON.stringify(value)) : value; }
function ruleScopeLabel(scope) { return scope === "common" ? "公共规则" : scope; }
function escapeRuleHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function formatRuleTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}
function setRuleNotice(message = "", kind = "") {
  ruleUi.notice.textContent = message;
  ruleUi.notice.className = "rules-notice notice";
  if (kind) ruleUi.notice.classList.add(`is-${kind}`);
  ruleUi.notice.classList.toggle("hidden", !message);
}
async function ruleRequest(path, { method = "GET", body = null } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== null) headers["Content-Type"] = "application/json";
  if (typeof state !== "undefined" && state.authRequired && state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { method, headers, body: body === null ? undefined : JSON.stringify(body), cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.message || payload.error || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}
function showRulesView() {
  ruleUi.dashboardView.classList.add("hidden"); ruleUi.archiveView.classList.add("hidden"); ruleUi.rulesView.classList.remove("hidden");
  ruleUi.dashboardNav.classList.remove("active"); ruleUi.dashboardNav.removeAttribute("aria-current");
  ruleUi.archiveNav.classList.remove("active"); ruleUi.archiveNav.removeAttribute("aria-current");
  ruleUi.rulesNav.classList.add("active"); ruleUi.rulesNav.setAttribute("aria-current", "page");
  ruleUi.pageKicker.textContent = "校验配置"; ruleUi.pageTitle.textContent = "规则版本管理";
  ruleUi.archiveRefresh.classList.add("hidden");
  if (!ruleState.items.length && !ruleState.loading) loadRuleHistory();
}
function showArchiveView() {
  ruleUi.dashboardView.classList.add("hidden"); ruleUi.rulesView.classList.add("hidden"); ruleUi.archiveView.classList.remove("hidden");
  ruleUi.dashboardNav.classList.remove("active"); ruleUi.dashboardNav.removeAttribute("aria-current");
  ruleUi.rulesNav.classList.remove("active"); ruleUi.rulesNav.removeAttribute("aria-current");
  ruleUi.archiveNav.classList.add("active"); ruleUi.archiveNav.setAttribute("aria-current", "page");
  ruleUi.pageKicker.textContent = "数据发布管理"; ruleUi.pageTitle.textContent = "归档记录";
  ruleUi.archiveRefresh.classList.remove("hidden");
}
function normalizeRule(document) {
  const value = cloneRule(document) || {};
  value.schema_version ||= "1.0"; value.rule_set_id ||= "aov-main"; value.version ||= "";
  value.published_at ||= ""; value.notes ||= ""; value.common ||= {};
  value.common.path_mappings ||= []; value.common.whitelist_paths ||= []; value.common.content_checks ||= []; value.regions ||= {};
  for (const region of RULE_SCOPES.slice(1)) {
    value.regions[region] ||= {}; value.regions[region].path_mappings ||= []; value.regions[region].whitelist_paths ||= []; value.regions[region].content_checks ||= [];
  }
  return value;
}
function activeScope(document = ruleState.draft || ruleState.selected) {
  if (!document) return { path_mappings: [], whitelist_paths: [], content_checks: [] };
  return ruleState.scope === "common" ? document.common : document.regions[ruleState.scope];
}
function nextRuleVersion() {
  const date = new Date();
  const prefix = `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, "0")}.${String(date.getDate()).padStart(2, "0")}`;
  let sequence = 0;
  for (const item of ruleState.items) {
    const match = String(item.version || "").match(new RegExp(`^${prefix.replaceAll(".", "\\.")}\\.(\\d+)$`));
    if (match) sequence = Math.max(sequence, Number(match[1]));
  }
  return `${prefix}.${sequence + 1}`;
}
function isoNow() { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }
function renderRuleHistory() {
  ruleUi.historyCount.textContent = String(ruleState.items.length);
  ruleUi.historyEmpty.classList.toggle("hidden", ruleState.items.length > 0);
  ruleUi.caption.textContent = ruleState.items.length ? `共 ${ruleState.items.length} 个不可变版本` : "尚未发布规则版本";
  ruleUi.history.innerHTML = ruleState.items.map((item) => {
    const active = ruleState.selected && item.rule_set_id === ruleState.selected.rule_set_id && item.version === ruleState.selected.version;
    return `<button class="rule-history-item${active ? " active" : ""}" type="button" data-rule-id="${escapeRuleHtml(item.rule_set_id)}" data-version="${escapeRuleHtml(item.version)}">
      <span class="rule-history-version">${escapeRuleHtml(item.version)}</span>
      <span class="rule-history-meta">${escapeRuleHtml(item.rule_set_id)} · ${formatRuleTime(item.published_at)}</span>
      <span class="rule-history-note">${escapeRuleHtml(item.notes || "无发布说明")}</span>
      <span class="rule-history-stats">${Number(item.mapping_count || 0)} 个映射 · ${Number(item.whitelist_count || 0)} 个白名单 · ${Number(item.content_check_count || 0)} 个表校验</span>
    </button>`;
  }).join("");
}
async function loadRuleHistory(preferred = null) {
  ruleState.loading = true; ruleUi.refresh.disabled = true; ruleUi.newDraft.disabled = true;
  setRuleNotice("正在读取规则历史...");
  try {
    const payload = await ruleRequest("/api/v1/validation-rule-sets?limit=100&offset=0");
    ruleState.items = payload.items || []; renderRuleHistory();
    const target = preferred || ruleState.items[0] || null;
    if (target) await loadRuleDetail(target.rule_set_id, target.version);
    else { ruleState.selected = null; ruleState.baseline = null; ruleState.draft = null; renderRuleEditor(); setRuleNotice("暂无已发布规则，可以创建第一份草稿。", "info"); }
  } catch (error) { setRuleNotice(`规则历史读取失败：${error.message}`, "error"); }
  finally { ruleState.loading = false; ruleUi.refresh.disabled = false; ruleUi.newDraft.disabled = false; }
}
async function loadRuleDetail(ruleSetId, version) {
  setRuleNotice("正在读取规则详情...");
  try {
    const payload = await ruleRequest(`/api/v1/validation-rule-sets/${encodeURIComponent(ruleSetId)}/${encodeURIComponent(version)}`);
    ruleState.selected = normalizeRule(payload.rule_set); ruleState.baseline = cloneRule(ruleState.selected); ruleState.draft = null;
    renderRuleHistory(); renderRuleEditor(); setRuleNotice("");
  } catch (error) { setRuleNotice(`规则详情读取失败：${error.message}`, "error"); }
}
function createRuleDraft() {
  const source = normalizeRule(ruleState.selected);
  ruleState.baseline = cloneRule(source); ruleState.draft = cloneRule(source);
  ruleState.draft.version = nextRuleVersion(); ruleState.draft.published_at = isoNow(); ruleState.draft.notes = "";
  ruleState.scope = "common"; renderRuleEditor();
  setRuleNotice("草稿仅保存在当前页面，确认发布后才会写入后端。", "info");
}
function renderRuleEditor() {
  const document = ruleState.draft || ruleState.selected; const editing = Boolean(ruleState.draft);
  ruleUi.editorMode.textContent = editing ? "编辑草稿" : "只读版本";
  ruleUi.editorMode.classList.toggle("is-draft", editing);
  ruleUi.editorTitle.textContent = editing ? "新版本草稿" : (document ? "规则版本详情" : "请选择规则版本");
  ruleUi.editorState.textContent = document ? `${document.rule_set_id} / ${document.version}` : "未加载";
  ruleUi.ruleSetId.value = document?.rule_set_id || "aov-main"; ruleUi.version.value = document?.version || ""; ruleUi.notes.value = document?.notes || "";
  ruleUi.ruleSetId.disabled = !editing; ruleUi.version.disabled = true; ruleUi.notes.disabled = !editing;
  for (const button of ruleUi.scopes.querySelectorAll("[data-scope]")) {
    const active = button.dataset.scope === ruleState.scope; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
  }
  renderRuleRows(); updateRuleSummary();
}
function renderRuleRows() {
  const editing = Boolean(ruleState.draft); const rules = activeScope();
  ruleUi.mappingRows.innerHTML = rules.path_mappings.map((mapping, index) => `<tr>
    <td><input data-kind="mapping" data-index="${index}" data-field="path_suffix" value="${escapeRuleHtml(mapping.path_suffix)}" ${editing ? "" : "disabled"} aria-label="路径后缀"></td>
    <td><input data-kind="mapping" data-index="${index}" data-field="module" value="${escapeRuleHtml(mapping.module || "")}" ${editing ? "" : "disabled"} aria-label="模块"></td>
    <td><input data-kind="mapping" data-index="${index}" data-field="table_name" value="${escapeRuleHtml(mapping.table_name)}" ${editing ? "" : "disabled"} aria-label="可读表名"></td>
    <td><button class="icon-button remove-rule-row" type="button" data-kind="mapping" data-index="${index}" title="删除映射" aria-label="删除映射" ${editing ? "" : "disabled"}>×</button></td>
  </tr>`).join("");
  ruleUi.mappingEmpty.classList.toggle("hidden", rules.path_mappings.length > 0);
  ruleUi.whitelistRows.innerHTML = rules.whitelist_paths.map((pattern, index) => `<div class="whitelist-row">
    <input data-kind="whitelist" data-index="${index}" value="${escapeRuleHtml(pattern)}" ${editing ? "" : "disabled"} aria-label="白名单路径">
    <button class="icon-button remove-rule-row" type="button" data-kind="whitelist" data-index="${index}" title="删除白名单" aria-label="删除白名单" ${editing ? "" : "disabled"}>×</button>
  </div>`).join("");
  ruleUi.whitelistEmpty.classList.toggle("hidden", rules.whitelist_paths.length > 0);
  ruleUi.contentRows.innerHTML = rules.content_checks.map((check, index) => `<article class="content-check-row">
    <div class="content-check-row-header">
      <label class="content-check-toggle"><span>启用</span><input type="checkbox" data-kind="content" data-index="${index}" data-field="enabled" ${check.enabled ? "checked" : ""} ${editing ? "" : "disabled"}></label>
      <label class="content-check-field"><span>规则 ID</span><input data-kind="content" data-index="${index}" data-field="id" value="${escapeRuleHtml(check.id)}" ${editing ? "" : "disabled"}></label>
      <label class="content-check-field"><span>校验名称</span><input data-kind="content" data-index="${index}" data-field="name" value="${escapeRuleHtml(check.name)}" ${editing ? "" : "disabled"}></label>
      <button class="icon-button remove-rule-row" type="button" data-kind="content" data-index="${index}" title="删除表校验" aria-label="删除表校验" ${editing ? "" : "disabled"}>×</button>
    </div>
    <div class="content-check-body">
      <label class="content-check-path"><span>DTXML 相对路径，支持 {region}</span><input data-kind="content" data-index="${index}" data-field="dtxml_path" value="${escapeRuleHtml(check.dtxml_path)}" ${editing ? "" : "disabled"}></label>
      <label class="content-check-field"><span>长期上下架 Sheet</span><input data-kind="content" data-index="${index}" data-field="main_sheet" value="${escapeRuleHtml(check.main_sheet)}" ${editing ? "" : "disabled"}></label>
      <label class="content-check-field"><span>促销特卖 Sheet</span><input data-kind="content" data-index="${index}" data-field="promotion_sheet" value="${escapeRuleHtml(check.promotion_sheet)}" ${editing ? "" : "disabled"}></label>
      <label class="content-check-triggers"><span>触发文件，每行一条；只有本次包涉及这些文件时才执行</span><textarea data-kind="content" data-index="${index}" data-field="trigger_paths" ${editing ? "" : "disabled"}>${escapeRuleHtml((check.trigger_paths || []).join("\n"))}</textarea></label>
    </div>
  </article>`).join("");
  ruleUi.contentEmpty.classList.toggle("hidden", rules.content_checks.length > 0);
  ruleUi.contentCount.textContent = `${rules.content_checks.length} 项`;
  ruleUi.addMapping.disabled = !editing; ruleUi.addWhitelist.disabled = !editing; ruleUi.addContent.disabled = !editing;
}
function comparable(document) {
  const mappings = new Map(); const whitelist = new Set(); const content = new Map();
  if (!document) return { mappings, whitelist, content };
  for (const scope of RULE_SCOPES) {
    const rules = scope === "common" ? document.common : document.regions[scope];
    for (const item of rules.path_mappings || []) mappings.set(`${scope}\0${String(item.path_suffix || "").toLowerCase()}`, { module: String(item.module || ""), table_name: String(item.table_name || "") });
    for (const item of rules.whitelist_paths || []) whitelist.add(`${scope}\0${String(item || "").toLowerCase()}`);
    for (const item of rules.content_checks || []) content.set(`${scope}\0${String(item.id || "").toLowerCase()}`, item);
  }
  return { mappings, whitelist, content };
}
function ruleDiff() {
  if (!ruleState.draft) return { added: 0, updated: 0, removed: 0, total: 0 };
  const before = comparable(ruleState.baseline); const after = comparable(ruleState.draft);
  let added = 0; let updated = 0; let removed = 0;
  for (const [key, value] of after.mappings) {
    if (!before.mappings.has(key)) added += 1;
    else if (JSON.stringify(before.mappings.get(key)) !== JSON.stringify(value)) updated += 1;
  }
  for (const key of before.mappings.keys()) if (!after.mappings.has(key)) removed += 1;
  for (const key of after.whitelist) if (!before.whitelist.has(key)) added += 1;
  for (const key of before.whitelist) if (!after.whitelist.has(key)) removed += 1;
  for (const [key, value] of after.content) {
    if (!before.content.has(key)) added += 1;
    else if (JSON.stringify(before.content.get(key)) !== JSON.stringify(value)) updated += 1;
  }
  for (const key of before.content.keys()) if (!after.content.has(key)) removed += 1;
  if ((ruleState.baseline?.notes || "") !== (ruleState.draft.notes || "")) updated += 1;
  if ((ruleState.baseline?.rule_set_id || "") !== (ruleState.draft.rule_set_id || "")) updated += 1;
  return { added, updated, removed, total: added + updated + removed };
}
function validateDraft() {
  if (!ruleState.draft) return [];
  const errors = [];
  if (!RULE_ID_PATTERN.test(ruleState.draft.rule_set_id || "")) errors.push("规则集 ID 格式不正确。");
  if (!String(ruleState.draft.notes || "").trim()) errors.push("请填写本次规则的发布说明。");
  for (const scope of RULE_SCOPES) {
    const rules = scope === "common" ? ruleState.draft.common : ruleState.draft.regions[scope];
    const mappings = new Set(); const whitelist = new Set();
    for (const [index, item] of (rules.path_mappings || []).entries()) {
      const name = `${ruleScopeLabel(scope)}第 ${index + 1} 条映射`; const suffix = String(item.path_suffix || "").trim();
      if (!suffix.startsWith("/") || suffix.endsWith("/")) errors.push(`${name}的路径后缀应以 / 开头且不能以 / 结尾。`);
      if (!String(item.table_name || "").trim()) errors.push(`${name}缺少可读表名。`);
      const key = suffix.toLowerCase(); if (key && mappings.has(key)) errors.push(`${name}的路径后缀重复。`); mappings.add(key);
    }
    for (const [index, item] of (rules.whitelist_paths || []).entries()) {
      const value = String(item || "").trim();
      if (!value) errors.push(`${ruleScopeLabel(scope)}第 ${index + 1} 条白名单为空。`);
      const key = value.toLowerCase(); if (key && whitelist.has(key)) errors.push(`${ruleScopeLabel(scope)}第 ${index + 1} 条白名单重复。`); whitelist.add(key);
    }
    const contentIds = new Set();
    for (const [index, item] of (rules.content_checks || []).entries()) {
      const name = `${ruleScopeLabel(scope)}第 ${index + 1} 条表校验`;
      const id = String(item.id || "").trim();
      if (!RULE_ID_PATTERN.test(id)) errors.push(`${name}的规则 ID 格式不正确。`);
      const idKey = id.toLowerCase(); if (idKey && contentIds.has(idKey)) errors.push(`${name}的规则 ID 重复。`); contentIds.add(idKey);
      if (!String(item.name || "").trim()) errors.push(`${name}缺少校验名称。`);
      const dtxmlPath = String(item.dtxml_path || "").trim();
      if (!dtxmlPath.startsWith("/") || !dtxmlPath.endsWith(".dtxml") || dtxmlPath.includes("..")) errors.push(`${name}的 DTXML 路径无效。`);
      if (!String(item.main_sheet || "").trim()) errors.push(`${name}缺少长期上下架 Sheet。`);
      if (!String(item.promotion_sheet || "").trim()) errors.push(`${name}缺少促销特卖 Sheet。`);
      if (!Array.isArray(item.trigger_paths) || !item.trigger_paths.length) errors.push(`${name}至少需要一个触发文件。`);
      else if (item.trigger_paths.some(path => !String(path).trim().startsWith("/") || String(path).includes(".."))) errors.push(`${name}包含无效触发路径。`);
    }
  }
  return errors;
}
function updateRuleSummary() {
  const diff = ruleDiff(); const errors = validateDraft();
  ruleUi.added.textContent = diff.added; ruleUi.updated.textContent = diff.updated; ruleUi.removed.textContent = diff.removed; ruleUi.errors.textContent = errors.length;
  ruleUi.errors.title = errors.join("\n");
  ruleUi.ruleSetId.setAttribute("aria-invalid", String(Boolean(ruleState.draft) && !RULE_ID_PATTERN.test(ruleState.draft.rule_set_id || "")));
  ruleUi.notes.setAttribute("aria-invalid", String(Boolean(ruleState.draft) && !String(ruleState.draft.notes || "").trim()));
  ruleUi.publish.disabled = !ruleState.draft || !diff.total || errors.length > 0 || ruleState.publishing;
}
function addMapping() { if (!ruleState.draft) return; activeScope().path_mappings.push({ path_suffix: "/", module: "", table_name: "" }); renderRuleRows(); updateRuleSummary(); ruleUi.mappingRows.querySelector("tr:last-child input")?.focus(); }
function addWhitelist() { if (!ruleState.draft) return; activeScope().whitelist_paths.push(""); renderRuleRows(); updateRuleSummary(); ruleUi.whitelistRows.querySelector(".whitelist-row:last-child input")?.focus(); }
function addContentCheck() {
  if (!ruleState.draft) return;
  activeScope().content_checks.push({
    id: "skin-sale-window",
    type: "skin_sale_window",
    enabled: true,
    name: "英雄皮肤上下架与促销关联",
    dtxml_path: "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
    main_sheet: "svr下发皮肤上下架表",
    promotion_sheet: "svr下发皮肤促销特卖",
    trigger_paths: [
      "/Databin/Server/Shop/SvrHeroSkinShop.xml",
      "/Databin/Server/Shop/SvrHeroSkinShop.bytes",
      "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
    ],
  });
  renderRuleRows(); updateRuleSummary();
  ruleUi.contentRows.querySelector(".content-check-row:last-child input[data-field='id']")?.focus();
}
function handleRuleInput(event) {
  if (!ruleState.draft) return;
  if (event.target === ruleUi.ruleSetId) ruleState.draft.rule_set_id = event.target.value.trim();
  else if (event.target === ruleUi.notes) ruleState.draft.notes = event.target.value;
  else if (event.target.dataset.kind === "mapping") activeScope().path_mappings[Number(event.target.dataset.index)][event.target.dataset.field] = event.target.value;
  else if (event.target.dataset.kind === "whitelist") activeScope().whitelist_paths[Number(event.target.dataset.index)] = event.target.value;
  else if (event.target.dataset.kind === "content") {
    const check = activeScope().content_checks[Number(event.target.dataset.index)];
    if (!check) return;
    if (event.target.dataset.field === "enabled") check.enabled = event.target.checked;
    else if (event.target.dataset.field === "trigger_paths") check.trigger_paths = event.target.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    else check[event.target.dataset.field] = event.target.value;
  } else return;
  updateRuleSummary();
}
function removeRuleRow(event) {
  const button = event.target.closest(".remove-rule-row"); if (!button || !ruleState.draft) return;
  const index = Number(button.dataset.index);
  if (button.dataset.kind === "mapping") activeScope().path_mappings.splice(index, 1);
  else if (button.dataset.kind === "content") activeScope().content_checks.splice(index, 1);
  else activeScope().whitelist_paths.splice(index, 1);
  renderRuleRows(); updateRuleSummary();
}
function openPublishDialog() {
  const errors = validateDraft(); const diff = ruleDiff();
  if (!ruleState.draft || errors.length || !diff.total) { setRuleNotice(errors[0] || "当前草稿没有需要发布的变更。", "error"); return; }
  ruleUi.dialogSummary.innerHTML = `<strong>${escapeRuleHtml(ruleState.draft.rule_set_id)} / ${escapeRuleHtml(ruleState.draft.version)}</strong><span>新增 ${diff.added}，修改 ${diff.updated}，删除 ${diff.removed}</span><span>${escapeRuleHtml(ruleState.draft.notes.trim())}</span>`;
  ruleUi.dialog.showModal();
}
async function publishDraft() {
  if (!ruleState.draft || ruleState.publishing) return;
  ruleState.publishing = true; ruleState.draft.published_at = isoNow(); updateRuleSummary(); setRuleNotice("正在发布规则版本...");
  try {
    const published = await ruleRequest("/api/v1/validation-rule-sets", { method: "POST", body: ruleState.draft });
    ruleUi.dialog.close(); ruleState.draft = null;
    await loadRuleHistory({ rule_set_id: published.rule_set.rule_set_id, version: published.rule_set.version });
    setRuleNotice(`规则 ${published.rule_set.version} 已发布。`, "success");
  } catch (error) {
    if (error.status === 409) setRuleNotice("该版本号已存在，请刷新历史后重新创建草稿。", "error");
    else if (error.status === 403) setRuleNotice("规则发布仅允许从后端所在机器操作。", "error");
    else setRuleNotice(`规则发布失败：${error.message}`, "error");
  } finally { ruleState.publishing = false; updateRuleSummary(); }
}

ruleUi.rulesNav.addEventListener("click", showRulesView); ruleUi.archiveNav.addEventListener("click", showArchiveView);
ruleUi.refresh.addEventListener("click", () => loadRuleHistory()); ruleUi.newDraft.addEventListener("click", createRuleDraft);
ruleUi.addMapping.addEventListener("click", addMapping); ruleUi.addWhitelist.addEventListener("click", addWhitelist); ruleUi.addContent.addEventListener("click", addContentCheck);
ruleUi.mappingRows.addEventListener("input", handleRuleInput); ruleUi.whitelistRows.addEventListener("input", handleRuleInput); ruleUi.contentRows.addEventListener("input", handleRuleInput); ruleUi.contentRows.addEventListener("change", handleRuleInput);
ruleUi.ruleSetId.addEventListener("input", handleRuleInput); ruleUi.notes.addEventListener("input", handleRuleInput);
ruleUi.mappingRows.addEventListener("click", removeRuleRow); ruleUi.whitelistRows.addEventListener("click", removeRuleRow); ruleUi.contentRows.addEventListener("click", removeRuleRow);
ruleUi.publish.addEventListener("click", openPublishDialog);
ruleUi.scopes.addEventListener("click", (event) => { const button = event.target.closest("[data-scope]"); if (!button) return; ruleState.scope = button.dataset.scope; renderRuleEditor(); });
ruleUi.history.addEventListener("click", (event) => { const button = event.target.closest(".rule-history-item"); if (button && !ruleState.loading) loadRuleDetail(button.dataset.ruleId, button.dataset.version); });
ruleUi.dialogForm.addEventListener("submit", (event) => { event.preventDefault(); if (event.submitter?.value === "cancel") ruleUi.dialog.close(); else publishDraft(); });
renderRuleEditor();