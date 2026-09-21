/* SecureBank Fraud Analytics dashboard — plain JS, no framework. */

const app = document.getElementById("app");
const toast = document.getElementById("toast");
const POLL_MS = 5000;

let pollTimer = null;
let currentUser = null;

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
    currentUser = data.user;
    bootDashboard();
  } else {
    renderLogin(data && data.error ? data.error : "Login failed", "login");
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
    body: JSON.stringify({ username, email, password, name, role: "analyst" }),
  });
  if (status === 201 && data.token) {
    renderLogin(`Account created — sign in with ${data.user.email || username}`);
    showToast("Account created, please sign in");
  } else {
    renderLogin(data && data.error ? data.error : "Registration failed", "register");
    showToast("Registration failed", true);
  }
}

// ------------------------------------------------------------------ dashboard

function bootDashboard() {
  renderDashboardShell(currentUser);
  loadSummary();
  pollTimer = setInterval(loadSummary, POLL_MS);
}

function renderDashboardShell(user) {
  app.innerHTML = `
    <div class="topbar">
      <div class="title">
        <h1>Fraud Risk Analytics</h1>
        <span class="user"><span class="live-dot"></span>live</span>
      </div>
      <div>
        <span class="user">${esc(user ? user.name || user.username : "")} · ${esc(user ? user.role : "")}</span>
        <button class="secondary" id="logoutBtn" style="margin-left:12px">Log out</button>
      </div>
    </div>
    <div id="content"><p class="muted">Loading…</p></div>`;

  document.getElementById("logoutBtn").addEventListener("click", () => {
    window.localStorage.removeItem("token");
    clearInterval(pollTimer);
    renderLogin();
  });
}

async function loadSummary() {
  const { status, data } = await api("/api/dashboard/summary");
  if (status === 401) {
    renderLogin("Session expired, please sign in again");
    return;
  }
  if (status !== 200) {
    showToast("Failed to load dashboard", true);
    return;
  }
  if (currentUser === null) {
    const me = JSON.parse(window.localStorage.getItem("user") || "null");
    currentUser = me;
  }
  renderContent(data);
}

function renderContent(d) {
  const s = d.stats || {};
  document.getElementById("content").innerHTML = `
    <div class="stats">
      <div class="stat"><div class="value">${s.total ?? 0}</div><div class="name">Transactions</div></div>
      <div class="stat"><div class="value" style="color:var(--allow)">${s.ALLOW ?? 0}</div><div class="name">Allowed</div></div>
      <div class="stat"><div class="value" style="color:var(--stepup)">${s.STEP_UP ?? 0}</div><div class="name">Step-Up</div></div>
      <div class="stat"><div class="value" style="color:var(--block)">${s.BLOCK ?? 0}</div><div class="name">Blocked</div></div>
      <div class="stat"><div class="value" style="color:var(--block)">${s.alerts ?? 0}</div><div class="name">Alerts</div></div>
      <div class="stat ${(s.agents ?? 0) > 0 ? "online" : ""}"><div class="value">${s.agents ?? 0}</div><div class="name">Agents</div></div>
    </div>

    <div class="panel">
      <h2>OTP Step-Up Verification</h2>
      <div class="otp-grid">
        <div style="flex:1;min-width:220px">
          <label>Transaction requiring OTP</label>
          <select id="otpTxn">
            <option value="">— none pending —</option>
            ${(d.otps || []).map((o) =>
              `<option value="${o.transaction_id}">#${o.transaction_id} · ${esc(o.customer_name || "?")} · ${money(o.amount)}</option>`).join("")}
          </select>
        </div>
        <div style="flex:0 0 140px">
          <label>OTP code</label>
          <input id="otpCode" maxlength="6" placeholder="6-digit code">
        </div>
        <button id="otpBtn">Verify OTP</button>
      </div>
      <div id="otpResult" class="otp-result"></div>
    </div>

    <div class="grid">
      <section class="panel">
        <h2>Recent transactions</h2>
        ${transactionsTable(d.transactions || [])}
      </section>
      <section class="panel">
        <h2>SIM change events</h2>
        ${simEventsTable(d.sim_events || [])}
      </section>
    </div>

    <div class="grid">
      <section class="panel">
        <h2>Alerts</h2>
        ${alertsTable(d.alerts || [])}
      </section>
      <section class="panel">
        <h2>Agent status</h2>
        ${agentsTable(d.agents || [])}
      </section>
    </div>`;

  document.getElementById("otpBtn").addEventListener("click", verifyOtp);
  document.getElementById("otpCode").addEventListener("keydown", (e) => {
    if (e.key === "Enter") verifyOtp();
  });
}

function transactionsTable(rows) {
  if (!rows.length) return `<div class="empty">No transactions yet — start the traffic generator.</div>`;
  return `
    <table>
      <thead><tr><th>ID</th><th>Customer</th><th>Amount</th><th>City</th><th>Device</th><th>Decision</th><th>Risk</th><th>Reasons</th></tr></thead>
      <tbody>
        ${rows.map((t) => `<tr>
          <td>#${t.id}</td>
          <td>${esc(t.customer_name || t.customer_id)}</td>
          <td>${money(t.amount)}</td>
          <td>${esc(t.city || "—")}</td>
          <td class="muted">${esc(t.device_id || "—")}</td>
          <td>${badge(t.decision)}${t.otp_verified ? " <span class='muted'>(otp ✓)</span>" : ""}</td>
          <td>${t.risk_score ?? "—"}</td>
          <td>${reasonsList(t.reasons)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function simEventsTable(rows) {
  if (!rows.length) return `<div class="empty">No SIM change events yet.</div>`;
  return `
    <table>
      <thead><tr><th>ID</th><th>Customer</th><th>Sim</th><th>Device</th><th>When</th><th>Decision</th></tr></thead>
      <tbody>
        ${rows.map((s) => `<tr>
          <td>#${s.id}</td>
          <td>${esc(s.customer_name || s.customer_id)}</td>
          <td>${esc(s.new_sim_id)}</td>
          <td class="muted">${esc(s.device_id || "—")}</td>
          <td class="muted">${esc(s.recorded_at || "—")}</td>
          <td>${badge(s.decision || "—")}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function alertsTable(rows) {
  if (!rows.length) return `<div class="empty">No alerts yet.</div>`;
  return `
    <table>
      <thead><tr><th>ID</th><th>Severity</th><th>Customer</th><th>Message</th></tr></thead>
      <tbody>
        ${rows.map((a) => `<tr>
          <td>#${a.id}</td>
          <td>${badge(a.severity === "high" ? "BLOCK" : "STEP_UP")}</td>
          <td>${esc(a.customer_name || "—")}</td>
          <td>${esc(a.message)}</td>
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
    loadSummary();
  } else {
    result.className = "otp-result err";
    const msg = data && data.error ? (typeof data.error === "object" ? Object.values(data.error).join("; ") : data.error) : "Verification failed";
    result.textContent = `✗ ${msg}`;
  }
}

// ------------------------------------------------------------------ init

(function init() {
  if (window.localStorage.getItem("token")) {
    bootDashboard();
  } else {
    renderLogin();
  }
})();