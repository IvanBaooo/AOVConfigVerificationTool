"use strict";

const PAGE_SIZE = 20;
const TOKEN_KEY = "aov_archive_backend_token";

function readStoredToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch (_error) {
    return "";
  }
}

function storeToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch (_error) {
    // The current page can still use the in-memory token.
  }
}

const state = {
  token: readStoredToken(),
  authRequired: true,
  offset: 0,
  total: 0,
  items: [],
  knownVersions: new Set(),
  filters: {},
  loading: false,
  reloadRequested: false,
  pendingManagement: null,
  audit: { offset: 0, total: 0, items: [], loading: false, loaded: false },
  dashboard: { loading: false, loaded: false },
  activity: { loading: false, loaded: false, region: "" },
  ruleStats: { loading: false, loaded: false, days: null },
};

const elements = {
  dashboardNav: document.querySelector("#nav-dashboard"),
  archiveNav: document.querySelector("#nav-archives"),
  rulesNav: document.querySelector("#nav-rules"),
  dashboardView: document.querySelector("#dashboard-view"),
  archiveView: document.querySelector("#archive-view"),
  rulesView: document.querySelector("#rules-view"),
  pageKicker: document.querySelector("#page-kicker"),
  pageTitle: document.querySelector("#page-title"),
  serviceState: document.querySelector("#service-state"),
  serviceLabel: document.querySelector("#service-label"),
  refreshButton: document.querySelector("#refresh-button"),
  connectionButton: document.querySelector("#connection-button"),
  filterForm: document.querySelector("#filter-form"),
  regionButtons: document.querySelectorAll(".region-button"),
  filterVersion: document.querySelector("#filter-version"),
  filterPackageStatus: document.querySelector("#filter-package-status"),
  filterValidationStatus: document.querySelector("#filter-validation-status"),
  filterRecordState: document.querySelector("#filter-record-state"),
  resetButton: document.querySelector("#reset-button"),
  rows: document.querySelector("#archive-rows"),
  tableState: document.querySelector("#table-state"),
  pageNotice: document.querySelector("#page-notice"),
  resultCaption: document.querySelector("#result-caption"),
  previousPage: document.querySelector("#previous-page"),
  nextPage: document.querySelector("#next-page"),
  pageLabel: document.querySelector("#page-label"),
  summaryTotal: document.querySelector("#summary-total"),
  summaryWarnings: document.querySelector("#summary-warnings"),
  summaryErrors: document.querySelector("#summary-errors"),
  summaryRegion: document.querySelector("#summary-region"),
  drawer: document.querySelector("#detail-drawer"),
  drawerBackdrop: document.querySelector("#drawer-backdrop"),
  closeDetail: document.querySelector("#close-detail"),
  detailTitle: document.querySelector("#detail-title"),
  detailLoading: document.querySelector("#detail-loading"),
  detailContent: document.querySelector("#detail-content"),
  connectionDialog: document.querySelector("#connection-dialog"),
  connectionForm: document.querySelector("#connection-form"),
  tokenInput: document.querySelector("#token-input"),
  archiveActionDialog: document.querySelector("#archive-action-dialog"),
  archiveActionForm: document.querySelector("#archive-action-form"),
  archiveActionTitle: document.querySelector("#archive-action-title"),
  archiveActionPackage: document.querySelector("#archive-action-package"),
  archiveBaselineFields: document.querySelector("#archive-baseline-fields"),
  archiveBaselineReplacement: document.querySelector("#archive-baseline-replacement"),
  archiveActionReason: document.querySelector("#archive-action-reason"),
  archiveActionWarning: document.querySelector("#archive-action-warning"),
  archiveActionClose: document.querySelector("#archive-action-close"),
  archiveActionCancel: document.querySelector("#archive-action-cancel"),
  archiveActionConfirm: document.querySelector("#archive-action-confirm"),
  auditPanel: document.querySelector("#admin-audit-panel"),
  auditSummaryCount: document.querySelector("#audit-summary-count"),
  auditNotice: document.querySelector("#audit-notice"),
  auditRows: document.querySelector("#audit-rows"),
  auditTableState: document.querySelector("#audit-table-state"),
  auditFilterAction: document.querySelector("#audit-filter-action"),
  auditFilterRegion: document.querySelector("#audit-filter-region"),
  auditPreviousPage: document.querySelector("#audit-previous-page"),
  auditNextPage: document.querySelector("#audit-next-page"),
  auditPageLabel: document.querySelector("#audit-page-label"),
  dashboardUpdatedAt: document.querySelector("#dashboard-updated-at"),
  dashboardActiveCount: document.querySelector("#dashboard-active-count"),
  dashboardAttentionCount: document.querySelector("#dashboard-attention-count"),
  dashboardPendingReviewCount: document.querySelector("#dashboard-pending-review-count"),
  dashboardDeletedCount: document.querySelector("#dashboard-deleted-count"),
  dashboardBaselineCount: document.querySelector("#dashboard-baseline-count"),
  dashboardNotice: document.querySelector("#dashboard-notice"),
  dashboardRegionRows: document.querySelector("#dashboard-region-rows"),
  dashboardRegionState: document.querySelector("#dashboard-region-state"),
  dashboardRecentRows: document.querySelector("#dashboard-recent-rows"),
  dashboardRecentState: document.querySelector("#dashboard-recent-state"),
  heatmapGrid: document.querySelector("#heatmap-grid"),
  heatmapMonths: document.querySelector("#heatmap-months"),
  heatmapState: document.querySelector("#heatmap-state"),
  heatmapRegionButtons: document.querySelectorAll(".heatmap-region-button"),
  ruleStatsRangeButtons: document.querySelectorAll(".rule-stats-range-button"),
  ruleStatsCovered: document.querySelector("#rule-stats-covered"),
  ruleStatsLegacy: document.querySelector("#rule-stats-legacy"),
  ruleStatsWhitelist: document.querySelector("#rule-stats-whitelist"),
  ruleStatsRules: document.querySelector("#rule-stats-rules"),
  ruleStatsTables: document.querySelector("#rule-stats-tables"),
  ruleStatsState: document.querySelector("#rule-stats-state"),
  filterDateChip: document.querySelector("#filter-date-chip"),
  filterDateChipText: document.querySelector("#filter-date-chip-text"),
  filterDateChipClear: document.querySelector("#filter-date-chip-clear"),
};

class ApiError extends Error {
  constructor(message, status = 0, code = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function formatBytes(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "--";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let current = size;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  return `${current.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function statusMeta(status) {
  const values = {
    success: ["成功", "success"],
    passed: ["通过", "success"],
    warning: ["有告警", "warning"],
    confirm: ["待确认", "warning"],
    partial: ["部分成功", "warning"],
    failed: ["失败", "error"],
    error: ["错误", "error"],
    skipped: ["未执行", "neutral"],
    packaged: ["已打包", "success"],
    missing: ["缺失", "error"],
    add_failed: ["加入失败", "error"],
    deleted_skipped: ["删除跳过", "neutral"],
    active: ["正常", "success"],
    deleted: ["已删除", "error"],
    baseline: ["对外基线", "neutral"],
    delete: ["删除", "error"],
    restore: ["恢复", "success"],
    baseline_set: ["设置基线", "neutral"],
    review_confirm: ["确认归档", "success"],
    pending_review: ["待复核", "warning"],
    confirmed: ["已确认", "success"],
  };
  return values[String(status)] || [String(status || "未知"), "neutral"];
}

function badge(status) {
  const [label, tone] = statusMeta(status);
  return `<span class="badge badge-${tone}">${escapeHtml(label)}</span>`;
}

function setNotice(message = "", tone = "warning") {
  elements.pageNotice.textContent = message;
  elements.pageNotice.classList.toggle("hidden", !message);
  elements.pageNotice.classList.toggle("error", tone === "error");
}

function setTableState(message = "") {
  elements.tableState.textContent = message;
  elements.tableState.classList.toggle("hidden", !message);
}

function setServiceState(mode, label) {
  elements.serviceState.classList.remove("online", "offline");
  if (mode) elements.serviceState.classList.add(mode);
  elements.serviceLabel.textContent = label;
}

async function apiRequest(path, { authenticated = true, method = "GET", body = null } = {}) {
  const headers = { Accept: "application/json" };
  if (authenticated && state.authRequired && state.token) {
    headers.Authorization = "Bearer " + state.token;
  }
  if (body !== null) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === null ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiError(`无法连接归档后端：${error.message}`);
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    throw new ApiError(`后端返回了无法识别的响应（HTTP ${response.status}）`, response.status);
  }
  if (!response.ok) {
    const detail = payload?.error || {};
    throw new ApiError(detail.message || `请求失败（HTTP ${response.status}）`, response.status, detail.code || "");
  }
  return payload;
}
async function checkHealth() {
  setServiceState("", "检查服务");
  try {
    const health = await apiRequest("/health", { authenticated: false });
    state.authRequired = health.auth_required !== false;
    elements.connectionButton.classList.toggle("hidden", !state.authRequired);
    setServiceState(health.status === "ok" ? "online" : "offline", health.status === "ok" ? "服务正常" : "服务异常");
    return true;
  } catch (_error) {
    setServiceState("offline", "服务不可用");
    return false;
  }
}

function activeRegion() {
  return document.querySelector(".region-button.active")?.dataset.region || "";
}

function readFilters() {
  return {
    region_code: activeRegion(),
    package_version: elements.filterVersion.value.trim(),
    package_status: elements.filterPackageStatus.value.trim(),
    validation_status: elements.filterValidationStatus.value.trim(),
    record_state: elements.filterRecordState.value.trim(),
  };
}

function selectRegion(region) {
  elements.regionButtons.forEach((button) => {
    const selected = button.dataset.region === region;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function buildListUrl() {
  const parameters = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(state.offset),
  });
  Object.entries(state.filters).forEach(([key, value]) => {
    if (value) parameters.set(key, value);
  });
  return `/api/v1/package-archives?${parameters.toString()}`;
}

function updateVersionOptions(items) {
  const selected = elements.filterVersion.value;
  items.forEach((item) => {
    if (item.package_version) state.knownVersions.add(String(item.package_version));
  });
  const options = [new Option("全部", "")];
  Array.from(state.knownVersions).sort().forEach((version) => {
    options.push(new Option(version, version));
  });
  elements.filterVersion.replaceChildren(...options);
  if (state.knownVersions.has(selected)) elements.filterVersion.value = selected;
}

function renderList() {
  updateVersionOptions(state.items);
  elements.rows.innerHTML = state.items.map((item) => {
    const deleted = Boolean(item.deleted_at);
    const baseline = Boolean(item.is_release_baseline);
    const managementButtons = deleted
      ? `<button class="record-action record-action-restore" type="button" data-action="restore" data-package-id="${escapeHtml(item.package_id)}" data-region="${escapeHtml(item.region_code)}">恢复</button>`
      : `${baseline ? "" : `<button class="record-action record-action-baseline" type="button" data-action="set-baseline" data-package-id="${escapeHtml(item.package_id)}" data-region="${escapeHtml(item.region_code)}">设为基线</button>`}
         <button class="record-action" type="button" data-action="soft-delete" data-package-id="${escapeHtml(item.package_id)}" data-region="${escapeHtml(item.region_code)}" data-is-baseline="${String(baseline)}">删除</button>`;
    return `
      <tr class="${deleted ? "record-deleted" : ""}" tabindex="0" data-package-id="${escapeHtml(item.package_id)}" aria-label="查看 ${escapeHtml(item.package_id)}">
        <td>${escapeHtml(formatDate(item.received_at))}</td>
        <td class="package-cell">${escapeHtml(item.package_id)}</td>
        <td><span class="badge badge-neutral">${escapeHtml(item.region_code)}</span></td>
        <td>${escapeHtml(item.package_version)}</td>
        <td class="number-cell">${escapeHtml(item.file_count)}</td>
        <td class="number-cell">${escapeHtml(item.warning_count)}</td>
        <td>${badge(item.validation_status)}</td>
        <td>${badge(item.review_status || "confirmed")}</td>
        <td>${badge(item.package_status)}</td>
        <td>${badge(deleted ? "deleted" : baseline ? "baseline" : "active")}</td>
        <td><div class="record-actions">${managementButtons}</div></td>
      </tr>
    `;
  }).join("");

  const page = Math.floor(state.offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  elements.pageLabel.textContent = `第 ${page} / ${pageCount} 页`;
  elements.previousPage.disabled = state.offset === 0 || state.loading;
  elements.nextPage.disabled = state.offset + PAGE_SIZE >= state.total || state.loading;
  elements.resultCaption.textContent = state.total === 0 ? "没有符合条件的记录" : `共 ${state.total} 条，当前显示 ${state.items.length} 条`;
  elements.summaryTotal.textContent = String(state.total);
  elements.summaryWarnings.textContent = String(state.items.filter((item) => Number(item.warning_count) > 0).length);
  elements.summaryErrors.textContent = String(state.items.filter((item) => item.validation_status === "failed").length);
  elements.summaryRegion.textContent = state.filters.region_code || "全部";

  const dateFrom = state.filters.received_from || "";
  const dateTo = state.filters.received_to || "";
  elements.filterDateChip.classList.toggle("hidden", !dateFrom && !dateTo);
  elements.filterDateChipText.textContent = dateFrom === dateTo
    ? `归档日期 ${dateFrom}`
    : `归档日期 ${dateFrom || "…"} 至 ${dateTo || "…"}`;

  if (state.items.length === 0) {
    setTableState("没有符合当前筛选条件的归档记录");
  } else {
    setTableState();
  }
}
function setDashboardNotice(message = "", tone = "error") {
  elements.dashboardNotice.textContent = message;
  elements.dashboardNotice.classList.toggle("hidden", !message);
  elements.dashboardNotice.classList.toggle("error", tone === "error");
}

function setDashboardState(target, message = "") {
  target.textContent = message;
  target.classList.toggle("hidden", !message);
}

function dashboardRegionBadge(region) {
  if (!region.baseline) return '<span class="badge badge-error">未建立基线</span>';
  if (Number(region.attention_count) > 0) return '<span class="badge badge-warning">需要关注</span>';
  return '<span class="badge badge-success">正常</span>';
}

function renderDashboard(payload) {
  const overview = payload.overview || {};
  const regions = Array.isArray(payload.regions) ? payload.regions : [];
  const recent = Array.isArray(payload.recent_archives) ? payload.recent_archives : [];
  elements.dashboardUpdatedAt.textContent = `更新于 ${formatDate(payload.generated_at)}`;
  elements.dashboardActiveCount.textContent = String(overview.active_count || 0);
  elements.dashboardAttentionCount.textContent = String(overview.attention_count || 0);
  elements.dashboardPendingReviewCount.textContent = String(overview.pending_review_count || 0);
  elements.dashboardDeletedCount.textContent = String(overview.deleted_count || 0);
  elements.dashboardBaselineCount.textContent = `${overview.baseline_count || 0} / 4`;
  elements.dashboardRegionRows.innerHTML = regions.map((region) => {
    const baseline = region.baseline || null;
    const packageId = baseline?.package_id || "";
    return `
      <tr ${packageId ? `tabindex="0" data-package-id="${escapeHtml(packageId)}" aria-label="查看区域基线 ${escapeHtml(region.region_code)}"` : ""}>
        <td><span class="badge badge-neutral">${escapeHtml(region.region_code)}</span></td>
        <td class="dashboard-baseline-cell">${baseline
          ? `<strong>${escapeHtml(baseline.package_id)}</strong><code>${escapeHtml(baseline.package_version || "--")}</code>`
          : "--"}</td>
        <td><code>${escapeHtml(baseline?.released_revision_spec || "--")}</code></td>
        <td>${escapeHtml(formatDate(baseline?.release_time))}</td>
        <td class="number-cell">${escapeHtml(region.active_count || 0)}</td>
        <td class="number-cell">${escapeHtml(region.attention_count || 0)}</td>
        <td>${dashboardRegionBadge(region)}</td>
      </tr>
    `;
  }).join("");
  elements.dashboardRecentRows.innerHTML = recent.map((item) => `
    <tr tabindex="0" data-package-id="${escapeHtml(item.package_id)}" aria-label="查看最近归档 ${escapeHtml(item.package_id)}">
      <td>${escapeHtml(formatDate(item.received_at))}</td>
      <td class="package-cell">${escapeHtml(item.package_id)}</td>
      <td><span class="badge badge-neutral">${escapeHtml(item.region_code)}</span></td>
      <td class="number-cell">${escapeHtml(item.file_count)}</td>
      <td class="number-cell">${escapeHtml(item.warning_count)}</td>
      <td>${badge(item.validation_status)}</td>
      <td>${badge(item.is_release_baseline ? "baseline" : "active")}</td>
    </tr>
  `).join("");
  setDashboardState(elements.dashboardRegionState, regions.length ? "" : "没有区域数据");
  setDashboardState(elements.dashboardRecentState, recent.length ? "" : "尚无正常归档");
}

const HEATMAP_DAYS = 365;

function toLocalIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function heatmapLevel(count) {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count <= 3) return 2;
  if (count <= 6) return 3;
  return 4;
}

function renderActivity(payload) {
  const entries = new Map(
    (Array.isArray(payload.days) ? payload.days : [])
      .filter((day) => day && day.date)
      .map((day) => [String(day.date), day]),
  );
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - (HEATMAP_DAYS - 1));
  const cursor = new Date(start);
  cursor.setDate(cursor.getDate() - ((cursor.getDay() + 6) % 7));

  const weeks = [];
  while (cursor <= today) {
    const week = [];
    for (let day = 0; day < 7; day += 1) {
      week.push(new Date(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  }

  let previousMonth = -1;
  elements.heatmapMonths.innerHTML = weeks.map((week) => {
    const month = week[0].getMonth();
    const label = month === previousMonth ? "" : `${month + 1}月`;
    previousMonth = month;
    return `<span>${label}</span>`;
  }).join("");

  elements.heatmapGrid.innerHTML = weeks.map((week) => week.map((date) => {
    if (date < start || date > today) {
      return '<span class="heatmap-cell heatmap-cell-empty" aria-hidden="true"></span>';
    }
    const iso = toLocalIsoDate(date);
    const entry = entries.get(iso) || {};
    const archives = Number(entry.archives) || 0;
    const warnings = Number(entry.warnings) || 0;
    const rulePublishes = Number(entry.rule_publishes) || 0;
    const baselineChanges = Number(entry.baseline_changes) || 0;
    const tooltip = `${iso}：归档 ${archives} 次 · 告警 ${warnings} 条`
      + (rulePublishes ? ` · 规则发布 ${rulePublishes} 次` : "")
      + (baselineChanges ? ` · 基线变更 ${baselineChanges} 次` : "");
    const classes = [
      "heatmap-cell",
      `heatmap-level-${heatmapLevel(archives)}`,
      rulePublishes ? "heatmap-rule-day" : "",
    ].filter(Boolean).join(" ");
    return `<button class="${classes}" type="button" data-date="${iso}" title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}，查看当天归档记录"></button>`;
  }).join("")).join("");
  setDashboardState(elements.heatmapState);
}

async function loadActivity() {
  if (state.activity.loading) return;
  state.activity.loading = true;
  setDashboardState(elements.heatmapState, "正在读取更新热点");
  try {
    const parameters = new URLSearchParams({ days: String(HEATMAP_DAYS) });
    if (state.activity.region) parameters.set("region_code", state.activity.region);
    const payload = await apiRequest(`/api/v1/dashboard-activity?${parameters.toString()}`);
    renderActivity(payload);
    state.activity.loaded = true;
  } catch (error) {
    setDashboardNotice(error.message || "更新热点读取失败。", "error");
    setDashboardState(elements.heatmapState, "更新热点加载失败");
  } finally {
    state.activity.loading = false;
  }
}

function renderRuleStats(payload) {
  const rules = Array.isArray(payload.rules) ? payload.rules : [];
  const tables = Array.isArray(payload.tables) ? payload.tables : [];
  const covered = Number(payload.covered_archives) || 0;
  const legacy = Number(payload.skipped_legacy) || 0;
  elements.ruleStatsCovered.textContent = String(covered);
  elements.ruleStatsLegacy.textContent = String(legacy);
  elements.ruleStatsWhitelist.textContent = String(Number(payload.whitelist_exemptions) || 0);

  const ruleMax = Math.max(1, ...rules.map((rule) => (Number(rule.warning_count) || 0) + (Number(rule.confirm_count) || 0)));
  elements.ruleStatsRules.innerHTML = rules.map((rule) => {
    const warnings = Number(rule.warning_count) || 0;
    const confirms = Number(rule.confirm_count) || 0;
    const errors = Number(rule.error_archives) || 0;
    const acknowledged = Number(rule.acknowledged_count) || 0;
    const warningWidth = (warnings / ruleMax) * 100;
    const confirmWidth = (confirms / ruleMax) * 100;
    return `
      <div class="rule-bar-row">
        <div class="rule-bar-head">
          <span class="rule-bar-name" title="${escapeHtml(rule.type)}">${escapeHtml(rule.name)}</span>
          <span class="rule-bar-count">${escapeHtml(rule.triggered_archives)} 归档触发</span>
        </div>
        <div class="rule-bar-track" role="img" aria-label="告警 ${warnings} 条，待确认 ${confirms} 条">
          ${warnings ? `<span class="rule-bar-seg rule-bar-seg-warning" style="width:${warningWidth}%"></span>` : ""}
          ${confirms ? `<span class="rule-bar-seg rule-bar-seg-confirm" style="width:${confirmWidth}%"></span>` : ""}
        </div>
        <div class="rule-bar-foot">
          <span class="rule-bar-stat rule-bar-stat-warning">告警 ${warnings}</span>
          <span class="rule-bar-stat rule-bar-stat-confirm">待确认 ${confirms}</span>
          ${acknowledged ? `<span class="rule-bar-stat rule-bar-stat-acked">已确认 ${acknowledged}</span>` : ""}
          ${errors ? `<span class="rule-bar-stat rule-bar-stat-error">错误归档 ${errors}</span>` : ""}
        </div>
      </div>
    `;
  }).join("");

  const tableMax = Math.max(1, ...tables.map((table) => Number(table.problem_count) || 0));
  elements.ruleStatsTables.innerHTML = tables.map((table) => {
    const count = Number(table.problem_count) || 0;
    const width = (count / tableMax) * 100;
    return `
      <div class="rule-bar-row">
        <div class="rule-bar-head">
          <span class="rule-bar-name">${escapeHtml(table.table)}</span>
          <span class="rule-bar-count">${count} 问题</span>
        </div>
        <div class="rule-bar-track" role="img" aria-label="问题 ${count} 条">
          ${count ? `<span class="rule-bar-seg rule-bar-seg-warning" style="width:${width}%"></span>` : ""}
        </div>
      </div>
    `;
  }).join("");

  if (covered === 0) {
    setDashboardState(
      elements.ruleStatsState,
      legacy > 0
        ? `当前范围内的 ${legacy} 条归档均为旧版记录，不含规则校验明细，暂无法统计`
        : "当前范围内没有归档记录，暂无规则告警统计",
    );
  } else if (rules.length === 0 && tables.length === 0) {
    setDashboardState(elements.ruleStatsState, "当前范围内没有触发告警或待确认的规则");
  } else {
    setDashboardState(elements.ruleStatsState);
  }
}

async function loadRuleStats() {
  if (state.ruleStats.loading) return;
  state.ruleStats.loading = true;
  setDashboardState(elements.ruleStatsState, "正在读取规则告警统计");
  try {
    const parameters = new URLSearchParams();
    if (state.ruleStats.days !== null) parameters.set("days", String(state.ruleStats.days));
    if (state.activity.region) parameters.set("region_code", state.activity.region);
    const query = parameters.toString();
    const payload = await apiRequest(`/api/v1/dashboard-rule-stats${query ? `?${query}` : ""}`);
    renderRuleStats(payload);
    state.ruleStats.loaded = true;
  } catch (error) {
    setDashboardNotice(error.message || "规则告警统计读取失败。", "error");
    setDashboardState(elements.ruleStatsState, "规则告警统计加载失败");
  } finally {
    state.ruleStats.loading = false;
  }
}

function filterArchivesByDate(date) {
  selectRegion(state.activity.region);
  state.knownVersions.clear();
  elements.filterVersion.replaceChildren(new Option("全部", ""));
  elements.filterForm.reset();
  state.filters = { ...readFilters(), received_from: date, received_to: date };
  state.offset = 0;
  showArchiveView();
  loadArchives();
}

async function loadDashboard() {
  if (state.dashboard.loading) return;
  state.dashboard.loading = true;
  setDashboardNotice();
  setDashboardState(elements.dashboardRegionState, "正在读取区域基线");
  setDashboardState(elements.dashboardRecentState, "正在读取最近归档");
  try {
    const payload = await apiRequest("/api/v1/dashboard-summary");
    renderDashboard(payload);
    state.dashboard.loaded = true;
  } catch (error) {
    setDashboardNotice(error.message || "Dashboard读取失败。", "error");
    setDashboardState(elements.dashboardRegionState, "区域基线加载失败");
    setDashboardState(elements.dashboardRecentState, "最近归档加载失败");
  } finally {
    state.dashboard.loading = false;
  }
  loadActivity();
  loadRuleStats();
}

function showDashboardView() {
  elements.dashboardView.classList.remove("hidden");
  elements.archiveView.classList.add("hidden");
  elements.rulesView.classList.add("hidden");
  elements.dashboardNav.classList.add("active");
  elements.dashboardNav.setAttribute("aria-current", "page");
  elements.archiveNav.classList.remove("active");
  elements.archiveNav.removeAttribute("aria-current");
  elements.rulesNav.classList.remove("active");
  elements.rulesNav.removeAttribute("aria-current");
  elements.pageKicker.textContent = "发布状态总览";
  elements.pageTitle.textContent = "Dashboard";
  elements.refreshButton.classList.remove("hidden");
  if (!state.dashboard.loaded) loadDashboard();
}
function setAuditTableState(message = "") {
  elements.auditTableState.textContent = message;
  elements.auditTableState.classList.toggle("hidden", !message);
}

function setAuditNotice(message = "", tone = "error") {
  elements.auditNotice.textContent = message;
  elements.auditNotice.classList.toggle("hidden", !message);
  elements.auditNotice.classList.toggle("error", tone === "error");
}

function buildAuditUrl() {
  const parameters = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(state.audit.offset),
  });
  const action = elements.auditFilterAction.value.trim();
  const region = elements.auditFilterRegion.value.trim();
  if (action) parameters.set("action", action);
  if (region) parameters.set("region_code", region);
  return `/api/v1/admin/archive-audit?${parameters.toString()}`;
}

function renderAudit() {
  elements.auditRows.innerHTML = state.audit.items.map((item) => `
    <tr tabindex="0" data-package-id="${escapeHtml(item.package_id)}" aria-label="查看操作记录 ${escapeHtml(item.package_id)}">
      <td>${escapeHtml(formatDate(item.created_at))}</td>
      <td><strong>${escapeHtml(item.actor)}</strong></td>
      <td>${badge(item.action)}</td>
      <td><span class="badge badge-neutral">${escapeHtml(item.region_code)}</span></td>
      <td class="package-cell">${escapeHtml(item.package_id)}</td>
      <td class="audit-reason">${escapeHtml(item.reason)}</td>
    </tr>
  `).join("");
  const page = Math.floor(state.audit.offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(state.audit.total / PAGE_SIZE));
  elements.auditPageLabel.textContent = `第 ${page} / ${pageCount} 页`;
  elements.auditPreviousPage.disabled = state.audit.offset === 0 || state.audit.loading;
  elements.auditNextPage.disabled = state.audit.offset + PAGE_SIZE >= state.audit.total || state.audit.loading;
  elements.auditSummaryCount.textContent = `共 ${state.audit.total} 条`;
  setAuditTableState(state.audit.items.length ? "" : "没有符合当前筛选条件的操作记录");
}

async function loadAudit() {
  if (state.audit.loading) return;
  state.audit.loading = true;
  setAuditNotice();
  setAuditTableState("正在读取管理员操作记录");
  try {
    const payload = await apiRequest(buildAuditUrl());
    state.audit.total = Number(payload.total) || 0;
    state.audit.items = Array.isArray(payload.items) ? payload.items : [];
    if (state.audit.offset >= state.audit.total && state.audit.offset > 0) {
      state.audit.offset = Math.max(0, Math.floor(Math.max(0, state.audit.total - 1) / PAGE_SIZE) * PAGE_SIZE);
      state.audit.loading = false;
      await loadAudit();
      return;
    }
    state.audit.loaded = true;
    renderAudit();
  } catch (error) {
    state.audit.items = [];
    state.audit.total = 0;
    setAuditNotice(error.message || "管理员操作记录读取失败。", "error");
    setAuditTableState("操作记录加载失败");
  } finally {
    state.audit.loading = false;
    elements.auditPreviousPage.disabled = state.audit.offset === 0;
    elements.auditNextPage.disabled = state.audit.offset + PAGE_SIZE >= state.audit.total;
  }
}
function handleApiError(error) {
  if (error instanceof ApiError && error.status === 401) {
    state.token = "";
    storeToken("");
    setNotice("访问凭据无效，请重新连接。", "error");
    setTableState("需要有效的后端访问凭据");
    openConnectionDialog();
    return;
  }
  setNotice(error.message || "读取归档记录失败。", "error");
  setTableState("归档记录加载失败");
}

async function loadArchives() {
  if (state.loading) {
    state.reloadRequested = true;
    return;
  }
  if (state.authRequired && !state.token) {
    setTableState("需要后端访问凭据");
    openConnectionDialog();
    return;
  }
  state.loading = true;
  setNotice();
  setTableState("正在加载归档记录");
  elements.refreshButton.disabled = true;
  try {
    const payload = await apiRequest(buildListUrl());
    state.total = Number(payload.total) || 0;
    state.items = Array.isArray(payload.items) ? payload.items : [];
    if (state.offset >= state.total && state.offset > 0) {
      state.offset = Math.max(0, Math.floor(Math.max(0, state.total - 1) / PAGE_SIZE) * PAGE_SIZE);
      state.loading = false;
      await loadArchives();
      return;
    }
    renderList();
  } catch (error) {
    state.items = [];
    state.total = 0;
    elements.rows.innerHTML = "";
    handleApiError(error);
  } finally {
    state.loading = false;
    elements.refreshButton.disabled = false;
    elements.previousPage.disabled = state.offset === 0;
    elements.nextPage.disabled = state.offset + PAGE_SIZE >= state.total;
    if (state.reloadRequested) {
      state.reloadRequested = false;
      loadArchives();
    }
  }
}

function describeWarnings(warnings) {
  if (!Array.isArray(warnings) || warnings.length === 0) return "";
  return `<ul class="warning-list">${warnings.map((warning) => {
    if (typeof warning === "string") return `<li>${escapeHtml(warning)}</li>`;
    const text = warning?.message || warning?.path || warning?.reason || JSON.stringify(warning);
    return `<li>${escapeHtml(text)}</li>`;
  }).join("")}</ul>`;
}

function keyValue(label, value, code = false) {
  const tag = code ? "code" : "strong";
  return `<div class="key-value"><span>${escapeHtml(label)}</span><${tag}>${escapeHtml(value ?? "--")}</${tag}></div>`;
}

function validationRow(label, data, detail) {
  return `<div class="validation-row">
    <strong>${escapeHtml(label)}</strong>
    <p>${escapeHtml(detail)}</p>
    ${badge(data?.status || "skipped")}
  </div>`;
}

function renderDetail(archive, management = {}) {
  const release = archive.release || {};
  const packageInfo = archive.package || {};
  const status = archive.status || {};
  const validation = archive.validation || {};
  const ruleSet = validation.rule_set || {};
  const summary = validation.summary || {};
  const commit = validation.commit_record || {};
  const skin = validation.skin_precheck || {};
  const files = Array.isArray(archive.files) ? archive.files : [];
  const currentRevisions = Array.isArray(release.current_revisions) ? release.current_revisions : [];
  const previousRevisions = Array.isArray(release.previous_external_revisions) ? release.previous_external_revisions : [];
  elements.detailTitle.textContent = archive.package_id || "归档详情";

  const deleted = management.record_state === "deleted";
  const reviewStatus = management.review_status || "confirmed";
  const reviewSection = reviewStatus === "pending_review" ? `
    <section class="detail-section detail-review">
      <h3>归档复核</h3>
      <div class="validation-row">
        <strong>复核状态</strong>
        <p>该归档包含告警或待确认项，人工复核通过后才会标记为已确认</p>
        ${badge("pending_review")}
      </div>
      <div class="notice error hidden" id="review-notice" role="status"></div>
      <label class="review-note-field">
        <span>复核备注（选填）</span>
        <textarea id="review-note" maxlength="500" rows="3" placeholder="确认说明，会写入操作记录"></textarea>
      </label>
      <div class="record-actions">
        <button class="button button-primary" id="review-confirm-button" type="button">确认归档</button>
      </div>
    </section>
  ` : `
    <section class="detail-section detail-review">
      <h3>归档复核</h3>
      <div class="validation-row">
        <strong>复核状态</strong>
        <p>${escapeHtml(management.reviewed_by === "auto" || management.reviewed_by === "migration" ? "无告警或待确认项，自动确认" : "人工复核确认")}</p>
        ${badge("confirmed")}
      </div>
      <div class="key-grid">
        ${keyValue("确认人", management.reviewed_by)}
        ${keyValue("确认时间", formatDate(management.reviewed_at))}
        ${management.review_note ? keyValue("复核备注", management.review_note) : ""}
      </div>
    </section>
  `;
  elements.detailContent.innerHTML = `
    <section class="detail-section detail-management">
      <h3>记录管理</h3>
      <div class="key-grid">
        ${keyValue("记录状态", deleted ? "已删除" : management.is_release_baseline ? "对外基线" : "正常")}
        ${keyValue("操作账号", deleted ? management.deleted_by : "admin")}
        ${deleted ? keyValue("删除时间", formatDate(management.deleted_at)) : ""}
        ${deleted ? keyValue("删除原因", management.delete_reason) : ""}
      </div>
    </section>
    ${reviewSection}
    <section class="detail-section">
      <h3>发布信息</h3>
      <div class="key-grid">
        ${keyValue("区域", `${release.region_code || "--"} / ${release.region_dir || "--"}`)}
        ${keyValue("版本", release.package_version)}
        ${keyValue("归档时间", formatDate(archive.created_at))}
        ${keyValue("输入方式", release.input_method)}
        ${keyValue("本次 Revision", release.current_revision_spec, true)}
        ${keyValue("上次对外 Revision", release.previous_external_revision_spec, true)}
        ${keyValue("上次对外时间", release.previous_external_time || "--")}
        ${keyValue("契约版本", archive.schema_version)}
      </div>
      ${currentRevisions.length ? `<ul class="revision-list"><li>本次包含：${escapeHtml(currentRevisions.map((item) => `r${item}`).join(", "))}</li>${previousRevisions.length ? `<li>上次对外：${escapeHtml(previousRevisions.map((item) => `r${item}`).join(", "))}</li>` : ""}</ul>` : ""}
    </section>

    <section class="detail-section">
      <h3>包体状态</h3>
      <div class="key-grid">
        ${keyValue("包名", packageInfo.name, true)}
        ${keyValue("文件数量", packageInfo.file_count)}
        ${keyValue("失败 / 跳过", `${packageInfo.failed_count || 0} / ${packageInfo.skipped_count || 0}`)}
        ${keyValue("归档根目录", packageInfo.archive_root, true)}
        ${keyValue("MD5", packageInfo.md5, true)}
        ${keyValue("SHA256", packageInfo.sha256, true)}
      </div>
      <div class="validation-row">
        <strong>打包结果</strong>
        <p>${escapeHtml(packageInfo.file_count || 0)} 个文件</p>
        ${badge(status.package_status)}
      </div>
    </section>

    <section class="detail-section">
      <h3>校验结果</h3>
      <div class="key-grid">
        ${keyValue("规则版本", `${ruleSet.rule_set_id || "--"} / ${ruleSet.version || "--"}`, true)}
        ${keyValue("规则来源", ({ remote: "后端最新规则", local_cache: "本地缓存", built_in: "内置规则" })[ruleSet.source] || ruleSet.source || "--")}
        ${keyValue("规则发布时间", formatDate(ruleSet.published_at))}
        ${keyValue("规则 Hash", ruleSet.rule_hash || "--", true)}
        ${keyValue("错误", summary.error_count || 0)}
        ${keyValue("告警", summary.warning_count || 0)}
        ${keyValue("待确认", summary.confirm_count || 0)}
        ${keyValue("未执行", summary.skipped_count || 0)}
      </div>
      ${validationRow("提交记录", commit, `${commit.package_path_count || 0} 个包内路径，${commit.warning_count || 0} 个告警`)}
      ${describeWarnings(commit.warnings)}
      ${validationRow("皮肤预检", skin, skin.reason || `${skin.item_count || 0} 个资源，${skin.warning_count || 0} 个告警`)}
      ${describeWarnings(skin.warnings)}
    </section>

    <section class="detail-section">
      <h3>文件清单（${files.length}）</h3>
      <div class="detail-table-wrap">
        <table>
          <thead><tr><th>动作</th><th>路径</th><th>大小</th><th>状态</th></tr></thead>
          <tbody>${files.map((file) => `<tr>
            <td>${escapeHtml(file.action)}</td>
            <td class="package-cell">${escapeHtml(file.fixed_path || file.archive_path)}</td>
            <td>${escapeHtml(formatBytes(file.size))}</td>
            <td>${badge(file.status)}</td>
          </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>
  `;
  const confirmButton = elements.detailContent.querySelector("#review-confirm-button");
  if (confirmButton) {
    confirmButton.addEventListener("click", () => confirmArchiveReview(archive.package_id));
  }
}

async function confirmArchiveReview(packageId) {
  const button = elements.detailContent.querySelector("#review-confirm-button");
  const noteInput = elements.detailContent.querySelector("#review-note");
  const notice = elements.detailContent.querySelector("#review-notice");
  const note = noteInput ? noteInput.value.trim() : "";
  if (button) button.disabled = true;
  if (notice) notice.classList.add("hidden");
  try {
    await apiRequest(
      `/api/v1/admin/package-archives/${encodeURIComponent(packageId)}/review-confirm`,
      { method: "POST", body: note ? { note } : {} },
    );
    state.dashboard.loaded = false;
    state.audit.loaded = false;
    loadArchives();
    await loadDetail(packageId);
  } catch (error) {
    if (button) button.disabled = false;
    if (notice) {
      notice.textContent = error.message || "确认归档失败。";
      notice.classList.remove("hidden");
    }
    if (error instanceof ApiError && error.status === 401) handleApiError(error);
  }
}

function openDrawer() {
  elements.drawer.classList.add("open");
  elements.drawer.setAttribute("aria-hidden", "false");
  elements.drawerBackdrop.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  elements.closeDetail.focus();
}

function closeDrawer() {
  elements.drawer.classList.remove("open");
  elements.drawer.setAttribute("aria-hidden", "true");
  elements.drawerBackdrop.classList.add("hidden");
  document.body.style.overflow = "";
}

async function loadDetail(packageId) {
  openDrawer();
  elements.detailTitle.textContent = packageId;
  elements.detailContent.innerHTML = "";
  elements.detailLoading.classList.remove("hidden");
  try {
    const payload = await apiRequest(`/api/v1/package-archives/${encodeURIComponent(packageId)}`);
    renderDetail(payload.archive || {}, payload.management || {});
  } catch (error) {
    elements.detailContent.innerHTML = `<div class="notice error">${escapeHtml(error.message || "详情加载失败")}</div>`;
    if (error instanceof ApiError && error.status === 401) handleApiError(error);
  } finally {
    elements.detailLoading.classList.add("hidden");
  }
}

function openConnectionDialog() {
  elements.tokenInput.value = state.token;
  if (!elements.connectionDialog.open) elements.connectionDialog.showModal();
  window.setTimeout(() => elements.tokenInput.focus(), 0);
}

elements.dashboardNav.addEventListener("click", showDashboardView);

function handleDashboardRow(event) {
  const row = event.target.closest("tr[data-package-id]");
  if (row) loadDetail(row.dataset.packageId);
}

function handleDashboardRowKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-package-id]");
  if (!row) return;
  event.preventDefault();
  loadDetail(row.dataset.packageId);
}

elements.dashboardRegionRows.addEventListener("click", handleDashboardRow);
elements.dashboardRegionRows.addEventListener("keydown", handleDashboardRowKeydown);
elements.dashboardRecentRows.addEventListener("click", handleDashboardRow);
elements.dashboardRecentRows.addEventListener("keydown", handleDashboardRowKeydown);
elements.regionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (state.loading || button.classList.contains("active")) return;
    selectRegion(button.dataset.region || "");
    state.knownVersions.clear();
    elements.filterVersion.replaceChildren(new Option("全部", ""));
    state.filters = readFilters();
    state.offset = 0;
    loadArchives();
  });
});

function applyListFilters() {
  state.filters = readFilters();
  state.offset = 0;
  loadArchives();
}

elements.filterForm.addEventListener("submit", (event) => {
  event.preventDefault();
  applyListFilters();
});

elements.filterVersion.addEventListener("change", applyListFilters);
elements.filterPackageStatus.addEventListener("change", applyListFilters);
elements.filterValidationStatus.addEventListener("change", applyListFilters);
elements.filterRecordState.addEventListener("change", applyListFilters);

elements.resetButton.addEventListener("click", () => {
  elements.filterForm.reset();
  applyListFilters();
});

elements.filterDateChipClear.addEventListener("click", applyListFilters);

elements.heatmapGrid.addEventListener("click", (event) => {
  const cell = event.target.closest("[data-date]");
  if (cell) filterArchivesByDate(cell.dataset.date);
});

elements.heatmapRegionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (state.activity.loading || button.classList.contains("active")) return;
    elements.heatmapRegionButtons.forEach((item) => {
      const selected = item === button;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    state.activity.region = button.dataset.region || "";
    loadActivity();
    loadRuleStats();
  });
});

elements.ruleStatsRangeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (state.ruleStats.loading || button.classList.contains("active")) return;
    elements.ruleStatsRangeButtons.forEach((item) => {
      const selected = item === button;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    const days = button.dataset.days || "";
    state.ruleStats.days = days === "" ? null : Number(days);
    loadRuleStats();
  });
});

elements.refreshButton.addEventListener("click", async () => {
  await checkHealth();
  if (!elements.dashboardView.classList.contains("hidden")) loadDashboard();
  else loadArchives();
});

elements.connectionButton.addEventListener("click", openConnectionDialog);
elements.connectionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    elements.connectionDialog.close();
    return;
  }
  state.token = elements.tokenInput.value.trim();
  if (!state.token) return;
  storeToken(state.token);
  elements.connectionDialog.close();
  state.offset = 0;
  loadArchives();
});

elements.previousPage.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - PAGE_SIZE);
  loadArchives();
});

elements.nextPage.addEventListener("click", () => {
  if (state.offset + PAGE_SIZE < state.total) {
    state.offset += PAGE_SIZE;
    loadArchives();
  }
});

function closeArchiveActionDialog() {
  state.pendingManagement = null;
  elements.archiveActionDialog.close();
}

async function openArchiveActionDialog(action, packageId, region, isBaseline = false) {
  const restoring = action === "restore";
  const settingBaseline = action === "set-baseline";
  state.pendingManagement = {
    action,
    packageId,
    region,
    isBaseline,
    baselineCandidateCount: 0,
  };
  elements.archiveActionTitle.textContent = restoring
    ? "恢复归档记录"
    : settingBaseline
      ? "设置对外基线"
      : "删除归档记录";
  elements.archiveActionPackage.textContent = packageId;
  elements.archiveActionReason.value = "";
  elements.archiveBaselineFields.classList.toggle("hidden", !isBaseline || action !== "soft-delete");
  elements.archiveBaselineReplacement.required = false;
  elements.archiveBaselineReplacement.disabled = false;
  elements.archiveBaselineReplacement.replaceChildren();
  elements.archiveActionWarning.textContent = restoring
    ? "恢复只会让记录重新可见，不会自动改动当前对外基线。"
    : settingBaseline
      ? "确认后，本地打包工具会把这条记录作为该区域的上次对外版本。"
      : "删除后记录不会进入默认列表，归档正文和审计记录仍会保留。";
  elements.archiveActionConfirm.disabled = false;
  elements.archiveActionConfirm.textContent = restoring
    ? "确认恢复"
    : settingBaseline
      ? "确认设为基线"
      : "确认删除";
  if (!elements.archiveActionDialog.open) elements.archiveActionDialog.showModal();

  if (isBaseline && action === "soft-delete") {
    elements.archiveActionConfirm.disabled = true;
    elements.archiveBaselineReplacement.replaceChildren(new Option("正在读取历史归档...", ""));
    try {
      const parameters = new URLSearchParams({
        region_code: region,
        record_state: "active",
        limit: "200",
      });
      const payload = await apiRequest(`/api/v1/package-archives?${parameters.toString()}`);
      if (state.pendingManagement?.packageId !== packageId) return;
      const candidates = (Array.isArray(payload.items) ? payload.items : [])
        .filter((item) => item.package_id !== packageId);
      state.pendingManagement.baselineCandidateCount = candidates.length;
      if (candidates.length) {
        const options = [new Option("请选择回退版本", "")];
        candidates.forEach((item) => {
          options.push(new Option(`${item.package_id} · ${formatDate(item.received_at)}`, item.package_id));
        });
        elements.archiveBaselineReplacement.replaceChildren(...options);
        elements.archiveBaselineReplacement.required = true;
        elements.archiveActionWarning.textContent = "删除当前对外基线后，所选历史归档会立即成为该区域的新基线。";
      } else {
        elements.archiveBaselineReplacement.replaceChildren(new Option("没有可用历史归档，将清空基线", ""));
        elements.archiveBaselineReplacement.disabled = true;
        elements.archiveActionWarning.textContent = "该区域没有其他正常归档。删除后将暂时没有上次对外版本。";
      }
      elements.archiveActionConfirm.disabled = false;
    } catch (error) {
      if (state.pendingManagement?.packageId !== packageId) return;
      elements.archiveBaselineReplacement.replaceChildren(new Option("历史归档读取失败", ""));
      elements.archiveBaselineReplacement.disabled = true;
      elements.archiveActionWarning.textContent = error.message || "无法读取可用的历史归档。";
    }
  }
  window.setTimeout(() => elements.archiveActionReason.focus(), 0);
}
elements.rows.addEventListener("click", (event) => {
  const actionButton = event.target.closest(".record-action");
  if (actionButton) {
    event.stopPropagation();
    openArchiveActionDialog(
      actionButton.dataset.action,
      actionButton.dataset.packageId,
      actionButton.dataset.region,
      actionButton.dataset.isBaseline === "true",
    );
    return;
  }
  const row = event.target.closest("tr[data-package-id]");
  if (row) loadDetail(row.dataset.packageId);
});

elements.rows.addEventListener("keydown", (event) => {
  if (event.target.closest(".record-action")) return;
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-package-id]");
  if (!row) return;
  event.preventDefault();
  loadDetail(row.dataset.packageId);
});

elements.archiveActionClose.addEventListener("click", closeArchiveActionDialog);
elements.archiveActionCancel.addEventListener("click", closeArchiveActionDialog);
elements.archiveActionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const pending = state.pendingManagement;
  const reason = elements.archiveActionReason.value.trim();
  if (!pending || !reason) return;
  const replacement = elements.archiveBaselineReplacement.value;
  if (pending.isBaseline && pending.baselineCandidateCount > 0 && !replacement) return;
  elements.archiveActionConfirm.disabled = true;
  try {
    if (pending.action === "set-baseline") {
      await apiRequest(`/api/v1/admin/release-baselines/${encodeURIComponent(pending.region)}`, {
        method: "POST",
        body: { package_id: pending.packageId, reason },
      });
    } else {
      const body = { reason };
      if (pending.isBaseline && replacement) body.replacement_package_id = replacement;
      await apiRequest(
        `/api/v1/admin/package-archives/${encodeURIComponent(pending.packageId)}/${pending.action}`,
        { method: "POST", body },
      );
    }
    const labels = {
      restore: "恢复",
      "soft-delete": "删除",
      "set-baseline": "设为对外基线",
    };
    const label = labels[pending.action] || "更新";
    closeArchiveActionDialog();
    await loadArchives();
    state.audit.loaded = false;
    state.dashboard.loaded = false;
    state.ruleStats.loaded = false;
    if (elements.auditPanel.open) {
      state.audit.offset = 0;
      await loadAudit();
    }
    setNotice(`归档记录已${label}，操作账号：admin。`, "warning");
  } catch (error) {
    setNotice(error.message || "归档记录管理失败。", "error");
  } finally {
    elements.archiveActionConfirm.disabled = false;
  }
});
function reloadAuditFromStart() {
  state.audit.offset = 0;
  loadAudit();
}

elements.auditPanel.addEventListener("toggle", () => {
  if (elements.auditPanel.open && !state.audit.loaded) loadAudit();
});
elements.auditFilterAction.addEventListener("change", reloadAuditFromStart);
elements.auditFilterRegion.addEventListener("change", reloadAuditFromStart);
elements.auditPreviousPage.addEventListener("click", () => {
  state.audit.offset = Math.max(0, state.audit.offset - PAGE_SIZE);
  loadAudit();
});
elements.auditNextPage.addEventListener("click", () => {
  if (state.audit.offset + PAGE_SIZE < state.audit.total) {
    state.audit.offset += PAGE_SIZE;
    loadAudit();
  }
});
elements.auditRows.addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-package-id]");
  if (row) loadDetail(row.dataset.packageId);
});
elements.auditRows.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-package-id]");
  if (!row) return;
  event.preventDefault();
  loadDetail(row.dataset.packageId);
});

elements.closeDetail.addEventListener("click", closeDrawer);
elements.drawerBackdrop.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.drawer.classList.contains("open")) closeDrawer();
});

async function bootstrap() {
  await checkHealth();
  state.filters = readFilters();
  if (!state.authRequired || state.token) {
    loadArchives();
  } else {
    setTableState("需要后端访问凭据");
    openConnectionDialog();
  }
}

bootstrap();
