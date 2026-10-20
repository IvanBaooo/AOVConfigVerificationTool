"use strict";

const userUi = {
  nav: document.querySelector("#nav-users"),
  view: document.querySelector("#users-view"),
  dashboardView: document.querySelector("#dashboard-view"),
  archiveView: document.querySelector("#archive-view"),
  rulesView: document.querySelector("#rules-view"),
  dashboardNav: document.querySelector("#nav-dashboard"),
  archiveNav: document.querySelector("#nav-archives"),
  rulesNav: document.querySelector("#nav-rules"),
  pageKicker: document.querySelector("#page-kicker"),
  pageTitle: document.querySelector("#page-title"),
  notice: document.querySelector("#users-notice"),
  profileEmail: document.querySelector("#profile-email"),
  profileName: document.querySelector("#profile-name"),
  profileRole: document.querySelector("#profile-role"),
  adminPanel: document.querySelector("#users-admin-panel"),
  usersCount: document.querySelector("#users-count"),
  usersRows: document.querySelector("#users-rows"),
  addForm: document.querySelector("#user-add-form"),
  addEmail: document.querySelector("#user-add-email"),
  addRole: document.querySelector("#user-add-role"),
  tokensPanel: document.querySelector("#tokens-panel"),
  tokensCount: document.querySelector("#tokens-count"),
  tokensRows: document.querySelector("#tokens-rows"),
  tokenForm: document.querySelector("#token-create-form"),
  tokenName: document.querySelector("#token-create-name"),
  tokenBox: document.querySelector("#token-plaintext-box"),
  tokenPlaintext: document.querySelector("#token-plaintext"),
  tokenCopy: document.querySelector("#token-copy"),
};

const usersPageState = { users: [], tokens: [], loading: false, loaded: false };

function escapeUserHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function formatUserTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

function setUsersNotice(message = "", kind = "") {
  userUi.notice.textContent = message;
  userUi.notice.className = "rules-notice notice";
  if (kind) userUi.notice.classList.add(`is-${kind}`);
  userUi.notice.classList.toggle("hidden", !message);
}

async function userRequest(path, { method = "GET", body = null } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== null) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { method, headers, body: body === null ? undefined : JSON.stringify(body), cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.error || {};
    const error = new Error(detail.message || `请求失败 (${response.status})`);
    error.status = response.status;
    error.code = detail.code || "";
    throw error;
  }
  return payload;
}

function showUsersView() {
  userUi.dashboardView.classList.add("hidden");
  userUi.archiveView.classList.add("hidden");
  userUi.rulesView.classList.add("hidden");
  userUi.view.classList.remove("hidden");
  userUi.dashboardNav.classList.remove("active");
  userUi.dashboardNav.removeAttribute("aria-current");
  userUi.archiveNav.classList.remove("active");
  userUi.archiveNav.removeAttribute("aria-current");
  userUi.rulesNav.classList.remove("active");
  userUi.rulesNav.removeAttribute("aria-current");
  userUi.nav.classList.add("active");
  userUi.nav.setAttribute("aria-current", "page");
  userUi.pageKicker.textContent = "账号与访问";
  userUi.pageTitle.textContent = "账号管理";
  if (!usersPageState.loaded && !usersPageState.loading) loadUsersPage();
}

function renderProfile() {
  const user = state.user || {};
  userUi.profileEmail.textContent = user.email || "-";
  userUi.profileName.textContent = user.display_name || "-";
  userUi.profileRole.innerHTML = user.role === "admin"
    ? '<span class="badge badge-success">管理员</span>'
    : '<span class="badge badge-neutral">成员</span>';
}

async function loadUsersPage() {
  usersPageState.loading = true;
  setUsersNotice("");
  renderProfile();
  const isAdmin = state.user?.role === "admin";
  userUi.adminPanel.classList.toggle("hidden", !isAdmin);
  const jobs = [loadTokens()];
  if (isAdmin) jobs.push(loadUsers());
  await Promise.all(jobs);
  usersPageState.loading = false;
  usersPageState.loaded = true;
}

async function loadUsers() {
  try {
    const payload = await userRequest("/api/v1/admin/users");
    usersPageState.users = Array.isArray(payload.items) ? payload.items : [];
    renderUsers();
  } catch (error) {
    if (error.status === 403) userUi.adminPanel.classList.add("hidden");
    else setUsersNotice(error.message || "用户列表读取失败。", "error");
  }
}

function renderUsers() {
  userUi.usersCount.textContent = String(usersPageState.users.length);
  const selfEmail = String(state.user?.email || "");
  userUi.usersRows.innerHTML = usersPageState.users.map((user) => {
    const isSelf = user.email === selfEmail;
    const disabled = user.status !== "active";
    const roleBadge = user.role === "admin"
      ? '<span class="badge badge-success">管理员</span>'
      : '<span class="badge badge-neutral">成员</span>';
    const statusBadge = disabled
      ? '<span class="badge badge-error">已停用</span>'
      : '<span class="badge badge-neutral">正常</span>';
    const actions = isSelf
      ? '<span class="users-self">当前账号</span>'
      : `
        <button class="record-action" type="button" data-action="role" data-id="${user.id}" data-role="${user.role === "admin" ? "member" : "admin"}">${user.role === "admin" ? "降为成员" : "设为管理员"}</button>
        <button class="record-action" type="button" data-action="status" data-id="${user.id}" data-status="${disabled ? "active" : "disabled"}">${disabled ? "启用" : "停用"}</button>
      `;
    return `
      <tr>
        <td>${escapeUserHtml(user.email)}</td>
        <td>${roleBadge}</td>
        <td>${statusBadge}</td>
        <td>${escapeUserHtml(formatUserTime(user.last_login_at))}</td>
        <td class="users-actions">${actions}</td>
      </tr>
    `;
  }).join("") || '<tr><td colspan="5">暂无授权用户</td></tr>';
}

async function loadTokens() {
  try {
    const payload = await userRequest("/api/v1/tokens");
    usersPageState.tokens = Array.isArray(payload.items) ? payload.items : [];
    renderTokens();
  } catch (error) {
    if (error.code === "tokens_unsupported" || error.status === 400) {
      userUi.tokensRows.innerHTML = '<tr><td colspan="4">API Token 仅在账号登录模式（Google / 公司账号）下可用</td></tr>';
      userUi.tokensCount.textContent = "0";
      userUi.tokenForm.classList.add("hidden");
    } else {
      setUsersNotice(error.message || "Token 列表读取失败。", "error");
    }
  }
}

function renderTokens() {
  userUi.tokensCount.textContent = String(usersPageState.tokens.length);
  userUi.tokensRows.innerHTML = usersPageState.tokens.map((token) => `
    <tr>
      <td>${escapeUserHtml(token.name || "未命名")}</td>
      <td>${escapeUserHtml(formatUserTime(token.created_at))}</td>
      <td>${escapeUserHtml(formatUserTime(token.last_used_at))}</td>
      <td class="users-actions">
        <button class="record-action" type="button" data-revoke="${token.id}">吊销</button>
      </td>
    </tr>
  `).join("") || '<tr><td colspan="4">尚未生成 Token</td></tr>';
}

userUi.nav.addEventListener("click", showUsersView);

userUi.addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = userUi.addEmail.value.trim();
  if (!email) return;
  try {
    await userRequest("/api/v1/admin/users", {
      method: "POST",
      body: { email, role: userUi.addRole.value },
    });
    userUi.addEmail.value = "";
    setUsersNotice(`已添加授权：${email}`, "success");
    await loadUsers();
  } catch (error) {
    setUsersNotice(error.message || "添加用户失败。", "error");
  }
});

userUi.usersRows.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const userId = button.dataset.id;
  const body = button.dataset.action === "role"
    ? { role: button.dataset.role }
    : { status: button.dataset.status };
  try {
    await userRequest(`/api/v1/admin/users/${userId}`, { method: "PATCH", body });
    setUsersNotice("用户信息已更新。", "success");
    await loadUsers();
  } catch (error) {
    setUsersNotice(error.message || "更新用户失败。", "error");
  }
});

userUi.tokenForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = await userRequest("/api/v1/tokens", {
      method: "POST",
      body: { name: userUi.tokenName.value.trim() },
    });
    userUi.tokenName.value = "";
    userUi.tokenPlaintext.textContent = payload.token;
    userUi.tokenBox.classList.remove("hidden");
    setUsersNotice("Token 已生成，请立即复制保存。", "success");
    await loadTokens();
  } catch (error) {
    setUsersNotice(error.message || "生成 Token 失败。", "error");
  }
});

userUi.tokenCopy.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(userUi.tokenPlaintext.textContent);
    userUi.tokenCopy.textContent = "已复制";
    window.setTimeout(() => { userUi.tokenCopy.textContent = "复制"; }, 1500);
  } catch (_error) {
    setUsersNotice("复制失败，请手动选择复制。", "error");
  }
});

userUi.tokensRows.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-revoke]");
  if (!button) return;
  try {
    await userRequest(`/api/v1/tokens/${button.dataset.revoke}/revoke`, { method: "POST" });
    setUsersNotice("Token 已吊销。", "success");
    await loadTokens();
  } catch (error) {
    setUsersNotice(error.message || "吊销 Token 失败。", "error");
  }
});
