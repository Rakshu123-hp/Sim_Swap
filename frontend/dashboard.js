/* SecureBank Fraud Analytics dashboard — plain JS, no framework.

   Role-aware: customer accounts see only their own profile/activity;
   analyst/admin accounts additionally get system-wide analytics and a
   customer explorer. Every panel is updated in place by a 5s poll so typing
   and selections survive refreshes.
*/

const app = document.getElementById("app");
const toast = document.getElementById("toast");
const POLL_MS = 5000;

let pollTimer = null;
let currentUser = null;
let currentCustomer = null;
let shellBuilt = false;
let lastAdminCustomers = "";

// ------------------------------------------------------------------ helpers

function esc(v) {
  if (v === null || v === undefined) return "";
  return String(v).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[m]));
}

function money(v) {
  if (v === null || v === undefined) return "—";
  return "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function badge(decision) {
  return `<span class="badge ${esc(decision)}">${esc(decision)}</span>`;
}

function asErr(data) {
  if (!data) return "Request failed";
  const e = data.error;
  if (typeof e === "object" && e !== null) return Object.values(e).join("; ");
  return String(e);
}

async function api(path, options = {}) {
  const headers = {};
  if (window.localStorage.getItem("token")) {
    headers["Authorization"] = "Bearer " + window.localStorage.getItem("token");
  }
  if (options.body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...options, headers });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  return { status: res.status, data };
}

function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.classList.toggle("err", isError);
  toast.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add("hidden"), 5000);
}

function isAnalyst() {
  return currentUser && (currentUser.role === "analyst" || currentUser.role === "admin");
}

function logout() {
  window.localStorage.removeItem("token");
  window.localStorage.removeItem("user");
  clearInterval(pollTimer);
  pollTimer = null;
  currentUser = null;
  currentCustomer = null;
  shellBuilt = false;
  renderLogin();
}

// ------------------------------------------------------------------ login

let authMode = "login";

function renderLogin(errorMsg = "", mode = authMode) {
  authMode = mode;
  const isRegister = mode === "register";
  app.innerHTML = `
    <div class="login-wrap">
      <div class="login-card">
        <div class="brand">SecureBank</div>
        <div class="sub">SIM Swap & Transaction Fraud Risk Analytics</div>

        <div class="auth-switch">
          <button id="tabLogin" class="${!isRegister ? "active" : ""}">Sign in</button>
          <button id="tabRegister" class="${isRegister ? "active" : ""}">Create account</button>
        </div>

        ${isRegister ? `
          <label>Full name</label>
          <input id="regName" autocomplete="name" placeholder="Your name">
        ` : ""}
        <label>Email</label>
        <input id="user" type="email" autocomplete="username" placeholder="you@example.com">
        ${isRegister ? `
          <label>Username</label>
          <input id="regUsername" autocomplete="username" placeholder="choose-a-username">
        ` : ""}
        <label>Password</label>
        <input id="pass" type="password" autocomplete="current-password" placeholder="••••••••">
        <button id="loginBtn" style="width:100%;margin-top:16px">${isRegister ? "Create account & sign in" : "Sign in"}</button>
        <div class="error-msg">${esc(errorMsg)}</div>
        <div class="login-hint">New accounts get a customer profile automatically. Demo logins: analyst / demo123, sim-customer / demo123, admin / demo123.</div>
      </div>
    </div>`;

  document.getElementById("loginBtn").addEventListener("click", () =>
    isRegister ? doRegister() : doLogin());
  document.getElementById("pass").addEventListener("keydown", (e) => {
    if (e.key === "Enter") (isRegister ? doRegister() : doLogin());
  });
  document.getElementById("tabLogin").addEventListener("click", () => renderLogin("", "login"));
  document.getElementById("tabRegister").addEventListener("click", () => renderLogin("", "register"));
}

async function doLogin() {
  const email = document.getElementById("user").value.trim();
  const password = document.getElementById("pass").value;
  if (!email || !password) {
    renderLogin("Enter your email and password", "login");
    return;
  }
  const { status, data } = await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username: email, password }),
  });
  if (status === 200 && data.token) {
    window.localStorage.setItem("token", data.token);
    window.localStorage.setItem("user", JSON.stringify(data.user));
    bootDashboard();
  } else {
    renderLogin(asErr(data), "login");
    showToast("Login failed", true);
  }
}

async function doRegister() {
  const name = document.getElementById("regName").value.trim();
  const email = document.getElementById("user").value.trim();
  const username = document.getElementById("regUsername").value.trim();
  const password = document.getElementById("pass").value;
  if (!email || !username || !password) {
    renderLogin("Fill in email, username and password", "register");
    return;
  }
  const { status, data } = await api("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, email, password, name, role: "customer" }),
  });
  if (status === 201 && data.token) {
    window.localStorage.setItem("token", data.token);
    window.localStorage.setItem("user", JSON.stringify(data.user));
    showToast("Account created with a customer profile");
    bootDashboard();
  } else {
    renderLogin(asErr(data), "register");
    showToast("Registration failed", true);
  }
}

// ------------------------------------------------------------------ dashboard

async function bootDashboard() {
  const r = await api("/api/auth/me");
  if (r.status === 401) { logout(); return; }
  if (r.status !== 200) { showToast("Could not load profile", true); renderLogin(); return; }
  currentUser = r.data.user;
  currentCustomer = r.data.customer;
  renderDashboardShell();
  await loadSummary();
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  pollTimer = setInterval(loadSummary, POLL_MS);
}

function renderDashboardShell() {
  shellBuilt = false;
  app.innerHTML = `
    <div class="topbar">
      <div class="title">
        <h1>Fraud Risk Analytics</h1>
        <span class="user"><span class="live-dot"></span>live</span>
      </div>
      <div>
        <span class="user">${esc(currentUser ? currentUser.name || currentUser.username : "")} · ${esc(currentUser ? currentUser.role : "")}</span>
        <button class="secondary" id="logoutBtn" style="margin-left:12px">Log out</button>
      </div>
    </div>
    <div id="content"><p class="muted">Loading…</p></div>`;

  document.getElementById("logoutBtn").addEventListener("click", logout);
}

async function loadSummary() {
  if (!shellBuilt) { shellBuilt = true; buildShell(); }
  const { status, data } = await api("/api/dashboard/summary");
  if (status === 401) { logout(); return; }
  if (status !== 200) {
    showToast("Failed to load dashboard", true);
    return;
  }
  updateAll(data);
}

// ------------------------------------------------------------------ shell

function buildShell() {
  if (!currentUser) return;
  const content = document.getElementById("content");
  const adminBlock = isAnalyst() ? `
    <section class="panel" id="adminAnalyticsPanel"><h2>System analytics</h2><div id="adminAnalyticsBody">…</div></section>
    <section class="panel" id="adminExplorerPanel"><h2>Customer explorer (analyst/admin)</h2>
      <div class="explorer-toolbar">
        <select id="explorerSelect"><option value="">— select a customer —</option></select>
      </div>
      <div id="explorerDetail"></div>
    </section>` : "";

  content.innerHTML = `
    <div class="panel profile-panel"><div id="profileBody"></div></div>
    <div class="last-updated">Last updated: <span id="updatedAt">—</span></div>
    <div class="stats" id="statsRow"></div>

    ${isAnalyst() ? adminBlock : ""}

    <div class="grid">
      ${isAnalyst() ? "" : '<section class="panel"><h2>Risk summary</h2><div id="riskBody"></div></section>'}
      <section class="panel" id="otpPanel"><h2>OTP Step-Up Verification</h2>
        <div class="otp-grid">
          <div style="flex:1;min-width:220px">
            <label>Transaction requiring OTP</label>
            <select id="otpTxn"><option value="">— none pending —</option></select>
          </div>
          <div style="flex:0 0 140px">
            <label>OTP code</label>
            <input id="otpCode" maxlength="6" placeholder="6-digit code">
          </div>
          <button id="otpBtn">Verify OTP</button>
        </div>
        <div id="otpResult" class="otp-result"></div>
      </section>
    </div>

    <div class="grid">
      <section class="panel"><h2>Recent transactions</h2><div id="txnsBody"></div></section>
      <section class="panel"><h2>Recent login activity</h2><div id="loginsBody"></div></section>
    </div>

    <div class="grid">
      <section class="panel"><h2>SIM change history</h2><div id="simsBody"></div></section>
      <section class="panel"><h2>Alerts</h2><div id="alertsBody"></div></section>
    </div>

    ${isAnalyst() ? `
    <div class="grid">
      <section class="panel"><h2>Agent status</h2><div id="agentsBody"></div></section>
    </div>` : ""}
  `;

  const otpBtn = document.getElementById("otpBtn");
  if (otpBtn) otpBtn.addEventListener("click", verifyOtp);
  const otpCode = document.getElementById("otpCode");
  if (otpCode) otpCode.addEventListener("keydown", (e) => { if (e.key === "Enter") verifyOtp(); });

  const explorerSelect = document.getElementById("explorerSelect");
  if (explorerSelect) explorerSelect.addEventListener("change", (e) => {
    const id = e.target.value;
    if (id) loadExplorerDetail(id);
  });
}

// ------------------------------------------------------------------ updates

function updateAll(d) {
  document.getElementById("updatedAt").textContent = new Date().toLocaleTimeString();
  renderProfileBody(d.profile);
  renderStatsRow(d.stats);

  setBody("txnsBody", transactionsTable(d.transactions || [], isAnalyst()));
  setBody("loginsBody", loginsTable(d.logins || []));
  setBody("simsBody", simEventsTable(d.sim_events || [], isAnalyst()));
  setBody("alertsBody", alertsTable(d.alerts || [], isAnalyst()));
  setBody("riskBody", riskPanel(d.risk_summary));
  setBody("agentsBody", agentsTable(d.agents || []));

  const otpTxn = document.getElementById("otpTxn");
  if (otpTxn) {
    const prev = otpTxn.value;
    otpTxn.innerHTML = `<option value="">— none pending —</option>` +
      (d.otps || []).map((o) =>
        `<option value="${o.transaction_id}" ${String(o.transaction_id) === prev ? "selected" : ""}>#${o.transaction_id} · ${esc(o.customer_name || "?")} · ${money(o.amount)}</option>`).join("");
  }

  if (isAnalyst()) {
    loadAdminAnalytics();
    loadAdminCustomers();
  }
}

function setBody(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function renderProfileBody(p) {
  const customer = p && p.customer ? p.customer : currentCustomer || {};
  const el = document.getElementById("profileBody");
  if (!el) return;
  el.innerHTML = `
    <div class="profile-head">
      <h2>Welcome, ${esc((p && p.name) || (p && p.username) || "User")}</h2>
    </div>
    <div class="profile-grid">
      ${kv("Name", (p && p.name) || "—")}
      ${kv("Username", (p && p.username) || "—")}
      ${kv("Email", (p && p.email) || "—")}
      ${kv("Role", (p && p.role) || "—")}
      ${kv("Account status", customer.status || "active")}
      ${kv("Customer ID", customer.id != null ? "#" + customer.id : "—")}
      ${kv("Home city", customer.home_city || "—")}
      ${kv("Registered", (p && p.created_at) || "—")}
    </div>`;
}

function kv(k, v) {
  return `<div><span class="kv-key">${esc(k)}</span><span class="kv-val">${esc(v)}</span></div>`;
}

function renderStatsRow(s) {
  const stats = s || {};
  const own = stats.login_attempts !== undefined;
  const cards = [];
  cards.push({ value: stats.total ?? 0, name: "Transactions", color: "" });
  cards.push({ value: stats.ALLOW ?? 0, name: "Allowed", color: "var(--allow)" });
  cards.push({ value: stats.STEP_UP ?? 0, name: "Step-Up", color: "var(--stepup)" });
  cards.push({ value: stats.BLOCK ?? 0, name: "Blocked", color: "var(--block)" });
  cards.push({ value: stats.alerts ?? 0, name: "Alerts", color: "var(--block)" });
  if (own) {
    cards.push({ value: stats.login_attempts ?? 0, name: "Login attempts", color: "" });
    cards.push({ value: stats.sim_changes ?? 0, name: "SIM changes", color: "" });
  } else {
    cards.push({ value: stats.customers ?? 0, name: "Customers", color: "" });
    cards.push({ value: stats.agents_online != null ? stats.agents_online + " online" : (stats.agents ?? 0), name: "Agents", color: "var(--online)" });
  }
  const el = document.getElementById("statsRow");
  if (!el) return;
  el.innerHTML = cards.map((c) => `
    <div class="stat"><div class="value" style="${c.color ? "color:" + c.color : ""}">${esc(c.value)}</div><div class="name">${esc(c.name)}</div></div>`).join("");
}

function riskPanel(summary) {
  if (!summary) return `<div class="empty">No risk history yet.</div>`;
  const d = summary.distribution || {};
  return `
    <p class="muted">${summary.total_events} evaluated events · avg score <b>${summary.avg_risk_score}</b> · max <b>${summary.max_risk_score}</b></p>
    <ul class="reasons">
      <li>Low (0-24): <b>${d.low ?? 0}</b></li>
      <li>Medium (25-69): <b>${d.medium ?? 0}</b></li>
      <li>High (70-100): <b>${d.high ?? 0}</b></li>
    </ul>`;
}

// ------------------------------------------------------------------ tables

function transactionsTable(rows, showCustomer) {
  if (!rows.length) return `<div class="empty">No transactions yet — enable demo traffic or run the traffic generator.</div>`;
  return `
    <table>
      <thead><tr><th>ID</th>${showCustomer ? "<th>Customer</th>" : ""}<th>When</th><th>Amount</th><th>Type</th><th>Channel</th><th>City</th><th>Device</th><th>Risk</th><th>Decision</th><th>Reasons</th></tr></thead>
      <tbody>
        ${rows.map((t) => `<tr>
          <td>#${t.id}</td>
          ${showCustomer ? `<td>${esc(t.customer_name || t.customer_id)}</td>` : ""}
          <td class="muted">${esc(t.created_at || t.event_time || "—")}</td>
          <td>${money(t.amount)}</td>
          <td>${esc(t.txn_type || "—")}</td>
          <td>${esc(t.channel || "—")}</td>
          <td>${esc(t.city || "—")}</td>
          <td class="muted">${esc(t.device_id || "—")}</td>
          <td>${t.risk_score ?? "—"}</td>
          <td>${badge(t.decision)}${t.otp_verified ? " <span class='muted'>(otp ✓)</span>" : ""}</td>
          <td>${reasonsList(t.reasons)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function loginsTable(rows) {
  if (!rows.length) return `<div class="empty">No login events yet.</div>`;
  return `
    <table>
      <thead><tr><th>When</th><th>Channel</th><th>Device</th><th>IP</th><th>City</th><th>Result</th><th>Risk</th><th>Decision</th></tr></thead>
      <tbody>
        ${rows.map((t) => `<tr>
          <td class="muted">${esc(t.created_at || "—")}</td>
          <td>${esc(t.channel || "—")}</td>
          <td class="muted">${esc(t.device_id || "—")}</td>
          <td class="muted">${esc(t.ip_address || "—")}</td>
          <td>${esc(t.city || "—")}</td>
          <td>${t.success ? `<span class="ok">success</span>` : `<span class="bad">failure</span>`}</td>
          <td>${t.risk_score ?? "—"}</td>
          <td>${badge(t.decision)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function simEventsTable(rows, showCustomer) {
  if (!rows.length) return `<div class="empty">No SIM change events yet.</div>`;
  return `
    <table>
      <thead><tr>${showCustomer ? "<th>Customer</th>" : ""}<th>When</th><th>SIM ID</th><th>Device</th><th>IP</th><th>Risk</th><th>Decision</th></tr></thead>
      <tbody>
        ${rows.map((s) => `<tr>
          ${showCustomer ? `<td>${esc(s.customer_name || s.customer_id)}</td>` : ""}
          <td class="muted">${esc(s.recorded_at || "—")}</td>
          <td>${esc(s.new_sim_id)}</td>
          <td class="muted">${esc(s.device_id || "—")}</td>
          <td class="muted">${esc(s.ip_address || "—")}</td>
          <td>${s.risk_score ?? "—"}</td>
          <td>${badge(s.decision || "—")}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function alertsTable(rows, showCustomer) {
  if (!rows.length) return `<div class="empty">No alerts yet.</div>`;
  return `
    <table>
      <thead><tr>${showCustomer ? "<th>Customer</th>" : ""}<th>Severity</th><th>Message</th><th>When</th><th>Status</th></tr></thead>
      <tbody>
        ${rows.map((a) => `<tr>
          ${showCustomer ? `<td>${esc(a.customer_name || "—")}</td>` : ""}
          <td>${badge(a.severity === "high" ? "BLOCK" : "STEP_UP")}</td>
          <td>${esc(a.message)}</td>
          <td class="muted">${esc(a.notified_at || "—")}</td>
          <td><span class="status ${a.status === "open" ? "stale" : "online"}">${esc(a.status || "open")}</span></td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function agentsTable(rows) {
  if (!rows.length) return `<div class="empty">No agents have reported in yet.</div>`;
  return `
    <table>
      <thead><tr><th>Agent</th><th>Last heartbeat</th><th>Status</th></tr></thead>
      <tbody>
        ${rows.map((a) => `<tr>
          <td>${esc(a.agent_name)}</td>
          <td class="muted">${esc(a.last_heartbeat)}</td>
          <td><span class="status ${a.status === "online" ? "online" : "stale"}">${a.status}</span></td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function reasonsList(rows) {
  if (!rows || !rows.length) return `<span class="muted">—</span>`;
  return `<ul class="reasons">${rows.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`;
}

// ------------------------------------------------------------------ admin

async function loadAdminAnalytics() {
  const { status, data } = await api("/api/admin/analytics");
  const el = document.getElementById("adminAnalyticsBody");
  if (!el) return;
  if (status !== 200) { el.innerHTML = `<p class="muted">Analytics unavailable.</p>`; return; }
  const a = data;
  el.innerHTML = `
    <div class="stats nested">
      <div class="stat"><div class="value">${a.users ?? 0}</div><div class="name">Users</div></div>
      <div class="stat"><div class="value">${a.customers ?? 0}</div><div class="name">Customers</div></div>
      <div class="stat"><div class="value">${a.total_transactions ?? 0}</div><div class="name">Transactions</div></div>
      <div class="stat"><div class="value" style="color:var(--allow)">${a.allowed ?? 0}</div><div class="name">Allowed</div></div>
      <div class="stat"><div class="value" style="color:var(--stepup)">${a.step_up ?? 0}</div><div class="name">Step-Up</div></div>
      <div class="stat"><div class="value" style="color:var(--block)">${a.blocked ?? 0}</div><div class="name">Blocked</div></div>
      <div class="stat"><div class="value" style="color:var(--block)">${a.active_alerts ?? 0}</div><div class="name">Active alerts</div></div>
    </div>
    <div class="analytics-grid">
      ${simpleList("Risk distribution", a.risk_distribution)}
      ${simpleList("Transactions by city", a.transactions_by_city, "city", "n")}
      ${simpleList("Transactions by channel", a.transactions_by_channel, "channel", "n")}
      ${simpleList("Transactions over time", a.transactions_over_time, "day", "n")}
      ${simpleList("High-risk customers", a.high_risk_customers, "customer_name", "blocked")}
    </div>`;
}

function simpleList(title, objOrArr, key, valKey) {
  const rows = Array.isArray(objOrArr) ? objOrArr : (objOrArr ? Object.entries(objOrArr).map(([k, v]) => ({ [key || "name"]: k, [valKey || "n"]: v })) : []);
  return `<div class="mini"><h3>${esc(title)}</h3><table><tbody>
    ${rows.map((r) => `<tr><td>${esc(r[key || "name"]) || "—"}</td><td class="num">${esc(r[valKey || "n"])}</td></tr>`).join("") || `<tr><td class="muted">No data</td></tr>`}
    </tbody></table></div>`;
}

async function loadAdminCustomers() {
  const { status, data } = await api("/api/admin/customers");
  const el = document.getElementById("explorerSelect");
  if (!el || status !== 200) return;
  const key = JSON.stringify((data.customers || []).map((c) => c.id));
  if (key === lastAdminCustomers) return;
  lastAdminCustomers = key;
  const prev = el.value;
  el.innerHTML = `<option value="">— select a customer —</option>` +
    (data.customers || []).map((c) =>
      `<option value="${c.id}" ${String(c.id) === prev ? "selected" : ""}>#${c.id} ${esc(c.name)}${c.owner_username ? " (" + esc(c.owner_username) + ")" : ""}</option>`).join("");
}

async function loadExplorerDetail(id) {
  const detail = document.getElementById("explorerDetail");
  detail.innerHTML = `<p class="muted">Loading…</p>`;
  const { status, data } = await api("/api/admin/customers/" + id);
  if (status !== 200) { detail.innerHTML = `<p class="err">Could not load customer.</p>`; return; }
  const c = data.customer || {};
  detail.innerHTML = `
    <div class="profile-grid compact">
      ${kv("Customer", c.name)}
      ${kv("Customer ID", "#" + c.id)}
      ${kv("Home city", c.home_city || "—")}
      ${kv("Status", c.status || "active")}
      ${kv("Owner", (data.owner && data.owner.username) || "— (bank demo customer)")}
      ${kv("Owner role", (data.owner && data.owner.role) || "—")}
    </div>
    <div class="stats nested">
      <div class="stat"><div class="value">${data.stats.total ?? 0}</div><div class="name">Transactions</div></div>
      <div class="stat"><div class="value" style="color:var(--allow)">${data.stats.ALLOW ?? 0}</div><div class="name">Allowed</div></div>
      <div class="stat"><div class="value" style="color:var(--stepup)">${data.stats.STEP_UP ?? 0}</div><div class="name">Step-Up</div></div>
      <div class="stat"><div class="value" style="color:var(--block)">${data.stats.BLOCK ?? 0}</div><div class="name">Blocked</div></div>
      <div class="stat"><div class="value">${data.stats.login_attempts ?? 0}</div><div class="name">Logins</div></div>
      <div class="stat"><div class="value">${data.stats.sim_changes ?? 0}</div><div class="name">SIM changes</div></div>
      <div class="stat"><div class="value">${data.stats.alerts ?? 0}</div><div class="name">Alerts</div></div>
    </div>
    <div class="grid">
      <div class="mini"><h3>Transactions</h3>${transactionsTable(data.transactions || [], false)}</div>
      <div class="mini"><h3>Logins</h3>${loginsTable(data.logins || [])}</div>
    </div>
    <div class="grid">
      <div class="mini"><h3>SIM changes</h3>${simEventsTable(data.sim_events || [], false)}</div>
      <div class="mini"><h3>Alerts</h3>${alertsTable(data.alerts || [], false)}</div>
    </div>
    <div class="mini"><h3>Risk history</h3>${riskPanel(data.risk_summary)}</div>`;
}

// ------------------------------------------------------------------ otp

async function verifyOtp() {
  const txn = document.getElementById("otpTxn").value;
  const code = document.getElementById("otpCode").value.trim();
  const result = document.getElementById("otpResult");
  if (!txn || !code) {
    result.className = "otp-result err";
    result.textContent = "Select a transaction and enter the 6-digit code.";
    return;
  }
  const { status, data } = await api("/api/otp/verify", {
    method: "POST",
    body: JSON.stringify({ transaction_id: Number(txn), code }),
  });
  if (status === 200) {
    result.className = "otp-result ok";
    result.textContent = `✓ ${data.message} (#${txn})`;
    showToast(`Transaction #${txn} approved`);
    document.getElementById("otpCode").value = "";
    loadSummary();
  } else {
    result.className = "otp-result err";
    result.textContent = `✗ ${asErr(data)}`;
  }
}

// ------------------------------------------------------------------ init

(async function init() {
  if (window.localStorage.getItem("token")) {
    bootDashboard();
  } else {
    renderLogin();
  }
})();