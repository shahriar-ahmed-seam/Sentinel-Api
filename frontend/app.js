"use strict";

const TXN_TYPES = ["transfer", "payment", "cash_in", "cash_out", "settlement", "refund"];
const TXN_STATUS = ["completed", "failed", "pending", "reversed"];

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// API base URL (persisted in localStorage). Default to same origin so a
// reverse-proxied deploy works out of the box; override for a separate API host.
// ---------------------------------------------------------------------------
const LS_KEY = "qs_api_base";
const apiBaseInput = $("apiBase");
apiBaseInput.value = localStorage.getItem(LS_KEY) || window.location.origin;

apiBaseInput.addEventListener("change", () => {
  localStorage.setItem(LS_KEY, apiBaseInput.value.trim());
  checkHealth();
});

function apiBase() {
  return (apiBaseInput.value || "").trim().replace(/\/+$/, "");
}

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------
async function checkHealth() {
  const dot = $("healthDot");
  const text = $("healthText");
  dot.className = "health-dot unknown";
  text.textContent = "Checking…";
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 6000);
    const res = await fetch(apiBase() + "/health", { signal: ctrl.signal });
    clearTimeout(t);
    const body = await res.json();
    if (res.ok && body.status === "ok") {
      dot.className = "health-dot ok";
      dot.title = "Healthy";
      text.textContent = "API online";
    } else {
      throw new Error("bad status");
    }
  } catch {
    dot.className = "health-dot bad";
    dot.title = "Unreachable";
    text.textContent = "API unreachable";
  }
}

// ---------------------------------------------------------------------------
// Transaction rows
// ---------------------------------------------------------------------------
function txnCard(txn = {}) {
  const card = document.createElement("div");
  card.className = "txn-card";

  const id = document.createElement("input");
  id.placeholder = "TXN-id";
  id.value = txn.transaction_id || "";
  id.dataset.k = "transaction_id";

  const amount = document.createElement("input");
  amount.placeholder = "amount";
  amount.value = txn.amount ?? "";
  amount.dataset.k = "amount";

  const type = document.createElement("select");
  type.dataset.k = "type";
  TXN_TYPES.forEach((t) => type.add(new Option(t, t)));
  if (txn.type) type.value = txn.type;

  const cp = document.createElement("input");
  cp.placeholder = "counterparty";
  cp.value = txn.counterparty || "";
  cp.dataset.k = "counterparty";

  const status = document.createElement("select");
  status.dataset.k = "status";
  TXN_STATUS.forEach((s) => status.add(new Option(s, s)));
  if (txn.status) status.value = txn.status;

  // hidden timestamp carrier (kept from presets, not edited in the compact UI)
  card.dataset.ts = txn.timestamp || "";

  const del = document.createElement("button");
  del.className = "txn-del";
  del.type = "button";
  del.textContent = "×";
  del.title = "Remove";
  del.onclick = () => card.remove();

  [id, amount, type, cp, status, del].forEach((el) => card.appendChild(el));
  return card;
}

function addTxn(txn) {
  $("txnList").appendChild(txnCard(txn));
}

function collectTxns() {
  const out = [];
  $("txnList").querySelectorAll(".txn-card").forEach((card) => {
    const row = {};
    card.querySelectorAll("input,select").forEach((el) => {
      let v = el.value.trim();
      if (el.dataset.k === "amount") {
        if (v === "") return;
        const n = Number(v);
        v = Number.isNaN(n) ? el.value : n;
      }
      if (v !== "") row[el.dataset.k] = v;
    });
    if (card.dataset.ts) row.timestamp = card.dataset.ts;
    if (Object.keys(row).length) out.push(row);
  });
  return out;
}

$("addTxn").onclick = () => addTxn({});

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------
function loadPreset(p) {
  const i = p.input;
  $("ticketId").value = i.ticket_id || "";
  $("complaint").value = i.complaint || "";
  $("language").value = i.language || "";
  $("userType").value = i.user_type || "";
  $("channel").value = i.channel || "";
  $("txnList").innerHTML = "";
  (i.transaction_history || []).forEach(addTxn);
  $("errorMsg").hidden = true;
}

(function renderPresets() {
  const wrap = $("presets");
  window.PRESETS.forEach((p) => {
    const b = document.createElement("button");
    b.className = "preset-btn";
    b.type = "button";
    b.textContent = p.label;
    b.onclick = () => loadPreset(p);
    wrap.appendChild(b);
  });
})();

// ---------------------------------------------------------------------------
// Analyze
// ---------------------------------------------------------------------------
function buildPayload() {
  const payload = {
    ticket_id: $("ticketId").value.trim(),
    complaint: $("complaint").value,
  };
  if ($("language").value) payload.language = $("language").value;
  if ($("userType").value) payload.user_type = $("userType").value;
  if ($("channel").value) payload.channel = $("channel").value;
  const txns = collectTxns();
  if (txns.length) payload.transaction_history = txns;
  return payload;
}

async function analyze() {
  const btn = $("analyzeBtn");
  const err = $("errorMsg");
  err.hidden = true;
  btn.disabled = true;
  btn.classList.add("loading");
  btn.innerHTML = '<span class="spinner"></span>Analyzing…';

  const started = performance.now();
  try {
    const res = await fetch(apiBase() + "/analyze-ticket", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    const ms = Math.round(performance.now() - started);
    const body = await res.json();
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${body.error || JSON.stringify(body)}`);
    }
    renderResult(body, ms);
  } catch (e) {
    err.textContent = "Request failed — " + e.message + ". Check the API base URL and that the server is running.";
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
    btn.textContent = "Analyze ticket";
  }
}

$("analyzeBtn").onclick = analyze;

// ---------------------------------------------------------------------------
// Render result
// ---------------------------------------------------------------------------
function renderResult(r, ms) {
  $("emptyState").hidden = true;
  $("result").hidden = false;
  const lat = $("latency");
  lat.hidden = false;
  lat.textContent = ms + " ms";

  const badges = $("badges");
  badges.innerHTML = "";
  badges.appendChild(badge("case type", r.case_type, "badge-case"));
  badges.appendChild(badge("severity", r.severity, "sev-" + r.severity));

  $("relTxn").textContent = r.relevant_transaction_id ?? "null";
  $("verdict").textContent = r.evidence_verdict;
  $("dept").textContent = r.department;
  $("review").textContent = r.human_review_required ? "✓ required" : "not required";
  $("confidence").textContent = r.confidence != null ? r.confidence : "—";

  $("agentSummary").textContent = r.agent_summary;
  $("nextAction").textContent = r.recommended_next_action;
  $("customerReply").textContent = r.customer_reply;

  const codes = $("reasonCodes");
  codes.innerHTML = "";
  (r.reason_codes || []).forEach((c) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    if (c.startsWith("llm_")) chip.classList.add("llm");
    if (c.includes("injection")) chip.classList.add("inject");
    chip.textContent = c;
    codes.appendChild(chip);
  });

  $("rawJson").textContent = JSON.stringify(r, null, 2);
  $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function badge(label, value, cls) {
  const el = document.createElement("div");
  el.className = "badge " + cls;
  el.innerHTML = `<span class="lbl">${label}</span>${value}`;
  return el;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
loadPreset(window.PRESETS[0]);
checkHealth();
