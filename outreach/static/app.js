const state = { hospital: "mercy-general", token: "", view: "overview" };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
const badge = (value) => `<span class="badge ${escapeHtml(value)}">${escapeHtml(String(value).replaceAll("_", " "))}</span>`;

async function authenticate(role = "hospital_admin") {
  const response = await fetch("/api/v1/auth/demo-token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hospital_slug: state.hospital, role }),
  });
  if (!response.ok) throw new Error("Demo access is unavailable.");
  state.token = (await response.json()).access_token;
}

async function api(path, options = {}) {
  if (!state.token) await authenticate();
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}`, ...(options.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "The operation could not be completed.");
  }
  return response.json();
}

function rows(items, columns) {
  if (!items.length) return `<div class="empty">No records in this view.</div>`;
  return `<table><thead><tr>${columns.map((c) => `<th>${c.label}</th>`).join("")}</tr></thead><tbody>
    ${items.map((item) => `<tr>${columns.map((c) => `<td>${c.render ? c.render(item) : escapeHtml(item[c.key])}</td>`).join("")}</tr>`).join("")}
  </tbody></table>`;
}

async function overview() {
  const [queue, campaigns, escalations] = await Promise.all([api("/simulation"), api("/campaigns"), api("/escalations")]);
  const counts = queue.state_counts;
  const complete = counts.completed || 0;
  const total = queue.tasks.length;
  return `<div class="grid metrics">
    <article class="metric"><span>Queue depth</span><strong>${total - complete}</strong><small>${counts.calling || 0} active now</small></article>
    <article class="metric"><span>Capacity</span><strong>${queue.active_calls}/${queue.capacity}</strong><small>Peak ${queue.peak_concurrency}</small></article>
    <article class="metric"><span>Completed outreach</span><strong>${complete}</strong><small>${Math.round((complete / total) * 100)}% of tenant queue</small></article>
    <article class="metric"><span>Open escalations</span><strong>${escalations.filter((e) => e.status !== "resolved").length}</strong><small>Human review required</small></article>
  </div>
  <div class="grid two-column">
    <article class="panel"><div class="panel-head"><h2>Active campaigns</h2></div>${rows(campaigns, [
      { label: "Campaign", key: "name" }, { label: "Status", render: (x) => badge(x.status) },
      { label: "Eligible", key: "eligible_patients" }, { label: "Window", render: (x) => `${x.clinical_window_hours} hours` }
    ])}</article>
    <article class="panel"><div class="panel-head"><h2>Queue composition</h2></div>
      ${Object.entries(counts).map(([key, value]) => `<p><span>${escapeHtml(key.replaceAll("_", " "))}</span><strong style="float:right">${value}</strong></p><div class="bar"><span style="width:${Math.round(value / total * 100)}%"></span></div>`).join("")}
    </article>
  </div>`;
}

async function queueView() {
  const data = await api("/simulation");
  return `<article class="panel"><div class="panel-head"><div><h2>Capacity-aware queue</h2><small>Priority combines clinical risk, deadline pressure, age, callbacks, and retries.</small></div><button class="button" id="advance">Advance simulation</button></div>
    ${rows(data.tasks, [
      { label: "Priority", render: (x) => x.priority.toFixed(1) }, { label: "Patient", key: "patient_ref" },
      { label: "Risk", render: (x) => badge(x.risk) }, { label: "State", render: (x) => badge(x.state) },
      { label: "Attempts", key: "attempts" }, { label: "Deadline", render: (x) => new Date(x.deadline).toLocaleString() }
    ])}</article>`;
}

async function campaignsView() {
  const data = await api("/campaigns");
  return `<article class="panel"><div class="panel-head"><h2>Campaign operations</h2></div>${rows(data, [
    { label: "Name", key: "name" }, { label: "Status", render: (x) => badge(x.status) },
    { label: "Eligible", key: "eligible_patients" }, { label: "Retry limit", key: "retry_limit" },
    { label: "Clinical window", render: (x) => `${x.clinical_window_hours}h` }
  ])}</article>`;
}

async function patientsView() {
  const data = await api("/patients");
  return `<article class="panel"><div class="panel-head"><h2>Synthetic discharge patients</h2><small>FHIR-shaped operational records</small></div>${rows(data, [
    { label: "Patient", key: "display_name" }, { label: "ID", key: "external_id" },
    { label: "Condition", key: "condition" }, { label: "Risk", render: (x) => badge(x.risk) },
    { label: "Discharged", render: (x) => new Date(x.discharged_at).toLocaleString() }
  ])}</article>`;
}

async function escalationsView() {
  const data = await api("/escalations");
  return `<article class="panel"><div class="panel-head"><h2>Human review worklist</h2></div>${rows(data, [
    { label: "Patient", key: "patient_name" }, { label: "Priority", render: (x) => badge(x.priority) },
    { label: "Status", render: (x) => badge(x.status) }, { label: "Trigger", key: "trigger" },
    { label: "Protocol", key: "protocol_reference" }
  ])}</article>`;
}

async function safetyView() {
  const data = await api("/evaluation/safety");
  return `<div class="grid metrics">
    <article class="metric"><span>Safety cases</span><strong>${data.cases}</strong></article>
    <article class="metric"><span>True positives</span><strong>${data.true_positives}</strong></article>
    <article class="metric"><span>False negatives</span><strong>${data.false_negatives}</strong></article>
    <article class="metric"><span>False-negative rate</span><strong>${(data.false_negative_rate * 100).toFixed(1)}%</strong></article>
  </div><article class="panel"><div class="panel-head"><h2>Fixed safety evaluation dataset v${data.dataset_version}</h2></div>${rows(data.results, [
    { label: "Case", key: "case_id" }, { label: "Expected escalation", render: (x) => x.expected_escalation ? "Yes" : "No" },
    { label: "Actual", render: (x) => x.actual_escalation ? "Escalate" : "Routine" },
    { label: "Classification", render: (x) => badge(x.classification) },
    { label: "Result", render: (x) => `<span class="safety-pass">${x.passed ? "PASS" : "FAIL"}</span>` }
  ])}</article>`;
}

async function auditView() {
  const data = await api("/audit");
  return `<article class="panel"><div class="panel-head"><h2>Immutable-intent audit trail</h2></div>${rows(data, [
    { label: "Time", render: (x) => new Date(x.occurred_at).toLocaleString() }, { label: "Action", key: "action" },
    { label: "Resource", render: (x) => `${escapeHtml(x.resource_type)} · ${escapeHtml(x.resource_id.slice(0, 8))}` },
    { label: "Actor", render: (x) => escapeHtml(x.actor_id.slice(0, 8)) }
  ])}</article>`;
}

const views = { overview, queue: queueView, campaigns: campaignsView, patients: patientsView, escalations: escalationsView, safety: safetyView, audit: auditView };
const titles = { overview: "Operations overview", queue: "Outbound queue", campaigns: "Campaign management", patients: "Patient operations", escalations: "Clinical escalations", safety: "Safety evaluation", audit: "Audit trail" };

async function render() {
  $("#alert").textContent = "";
  $("#content").innerHTML = `<article class="panel"><div class="empty">Loading operational data…</div></article>`;
  $("#page-title").textContent = titles[state.view];
  try {
    $("#content").innerHTML = await views[state.view]();
    $("#advance")?.addEventListener("click", async () => { await api("/simulation/step", { method: "POST" }); render(); });
  } catch (error) {
    $("#alert").textContent = error.message;
    $("#content").innerHTML = "";
  }
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
  button.classList.add("active"); state.view = button.dataset.view; render();
}));
$("#hospital-select").addEventListener("change", async (event) => {
  state.hospital = event.target.value; state.token = ""; await render();
});
render();