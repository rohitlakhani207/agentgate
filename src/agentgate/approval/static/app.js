// AgentGate approval page: cards arrive over a WebSocket, you tap Approve or Deny.
// Everything shown comes from tool calls, which can carry hostile text from injected
// documents, so the DOM is built with textContent only -- never innerHTML.
"use strict";

const TOKEN_KEY = "agentgate.token";
const $ = (id) => document.getElementById(id);
const cards = new Map(); // id -> { el, deadline, total }
let ws = null;
let retry = 0;
let toastTimer = null;

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of children) if (c != null) el.append(c);
  return el;
}

// ---- Token: from the QR code's #token=..., then remembered on this phone ----
function readToken() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const fromHash = hash.get("token");
  if (fromHash) {
    saveToken(fromHash);
    history.replaceState(null, "", location.pathname);
  }
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return fromHash || ""; }
}
function saveToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch {} }
function forgetToken() { try { localStorage.removeItem(TOKEN_KEY); } catch {} }
let token = readToken();

// ---- Connection ----
function setStatus(state, text) {
  const s = $("status");
  s.dataset.state = state;
  s.textContent = text;
}

function connect() {
  if (!token) return showPairing();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws?token=${encodeURIComponent(token)}`);
  setStatus("wait", "Connecting");
  ws.onopen = () => { retry = 0; setStatus("on", "Connected"); showView("pending"); };
  ws.onmessage = (ev) => handle(JSON.parse(ev.data));
  ws.onclose = (ev) => {
    if (ev.code === 4401) {
      forgetToken();
      token = "";
      showPairing("That token was not accepted. Scan the QR code again.");
      return setStatus("off", "Not paired");
    }
    setStatus("wait", "Reconnecting");
    const delay = Math.min(10000, 500 * 2 ** retry++);
    setTimeout(connect, delay);
  };
}

function handle(msg) {
  if (msg.type === "card") addCard(msg);
  else if (msg.type === "resolved") resolveCard(msg.id, msg.answer);
  else if (msg.type === "ack" && !msg.ok) toast("Too late, that request already closed");
}

// ---- Cards ----
const VOTE_NAMES = { decider: "Decider", clef: "Clef-flash", llm_judge: "LLM judge", classifier: "Classifier", keyword: "Rules" };

function addCard(c) {
  if (cards.has(c.id)) return;
  const total = c.expires_ms - c.created_ms;
  const deadline = Date.now() + (c.expires_ms - c.now_ms);

  const timer = h("span", { class: "timer" });
  const bar = h("i");
  const approve = h("button", { class: "btn approve", onclick: () => answer(c.id, "approve") }, "Approve");
  const deny = h("button", { class: "btn deny", onclick: () => answer(c.id, "deny") }, "Deny");

  const args = h("dl", { class: "args" });
  for (const [k, v] of Object.entries(c.args || {})) {
    const text = typeof v === "string" ? v : JSON.stringify(v, null, 2);
    args.append(h("div", { class: "arg" }, h("dt", { text: k }), h("dd", { text })));
  }

  const votes = h("div", { class: "votes" });
  for (const v of c.votes || []) {
    const pct = Math.round((v.confidence || 0) * 100);
    votes.append(h("div", { class: "vote" },
      h("span", { class: "who", text: VOTE_NAMES[v.source] || v.source }),
      h("span", { class: `tag ${v.decision}`, text: v.decision }),
      h("span", { class: "meter", title: "confidence" }, h("i", { class: `fill-${v.decision}`, style: `width:${pct}%` })),
      h("span", { class: "num", text: (v.confidence || 0).toFixed(2) }),
    ));
  }

  const el = h("article", { class: "card", "aria-label": `Approve ${c.tool}?` },
    h("div", { class: "card-body" },
      h("div", { class: "card-top" }, h("span", { class: "tool", text: c.tool }), timer),
      h("div", {}, h("p", { class: "label", text: "You asked" }), h("p", { class: "request", text: c.user_request })),
      h("div", {}, h("p", { class: "label", text: "The agent wants to" }), args),
      h("div", {}, h("p", { class: "label", text: "Why you're seeing this" }), h("p", { class: "why", text: c.reason })),
      c.votes && c.votes.length ? votes : null,
    ),
    h("div", { class: "countdown", "aria-hidden": "true" }, bar),
    h("div", { class: "actions", style: "padding-top:14px" }, deny, approve),
  );

  cards.set(c.id, { el, deadline, total, timer, bar, buttons: [approve, deny] });
  $("cards").prepend(el);
  tick();
  refreshCount();
  try { navigator.vibrate?.([120, 60, 120]); } catch {}
}

function answer(id, ans) {
  const c = cards.get(id);
  if (!c || !ws || ws.readyState !== WebSocket.OPEN) return toast("Not connected");
  c.buttons.forEach((b) => (b.disabled = true));
  ws.send(JSON.stringify({ type: "answer", id, answer: ans }));
}

function resolveCard(id, ans) {
  const c = cards.get(id);
  if (!c) return;
  cards.delete(id);
  toast({ approve: "Approved", deny: "Denied", timeout: "No answer in time, denied" }[ans] || ans);
  c.el.classList.add("leaving");
  c.el.addEventListener("animationend", () => c.el.remove(), { once: true });
  setTimeout(() => c.el.remove(), 400);
  refreshCount();
}

function tick() {
  const now = Date.now();
  for (const c of cards.values()) {
    const left = Math.max(0, c.deadline - now);
    c.timer.textContent = `${Math.ceil(left / 1000)}s`;
    c.timer.classList.toggle("low", left < 10000);
    c.bar.style.transform = `scaleX(${c.total ? left / c.total : 0})`;
  }
}
setInterval(tick, 250);

function refreshCount() {
  const n = cards.size;
  $("count").textContent = n;
  $("count").hidden = n === 0;
  $("empty").hidden = n > 0;
  document.title = n ? `(${n}) AgentGate` : "AgentGate";
}

// ---- History ----
async function loadHistory() {
  const list = $("history");
  try {
    const res = await fetch("/api/history?limit=50", { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(res.status);
    const rows = await res.json();
    list.replaceChildren(...rows.map(historyRow));
    $("history-empty").hidden = rows.length > 0;
  } catch {
    list.replaceChildren();
    $("history-empty").hidden = false;
    $("history-empty").textContent = "Could not load history.";
  }
}

// The check that settled the call: the vote at that step (gates differ), or you at step 3.
function settledBy(r) {
  if (r.step === 3) return "you";
  const v = (r.votes || [])[r.step - 1];
  return (v && VOTE_NAMES[v.source]) || r.gate;
}

function historyRow(r) {
  const when = new Date(r.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const human = r.human ? ` · you: ${r.human}` : "";
  return h("li", {},
    h("span", { class: "h-tool", text: r.tool }),
    h("span", { class: `tag ${r.decision}`, text: r.decision }),
    h("p", { class: "h-req", text: r.user_request }),
    h("p", { class: "h-meta", text: `${when} · settled by ${settledBy(r)} · ${r.gate_ms < 1 ? "<1" : Math.round(r.gate_ms)} ms · ${r.outcome}${human}` }),
  );
}

// ---- Views ----
function showView(name) {
  for (const v of ["pair", "pending", "history"]) $(`view-${v}`).hidden = v !== name;
  $("tab-pending").setAttribute("aria-selected", String(name === "pending"));
  $("tab-history").setAttribute("aria-selected", String(name === "history"));
  if (name === "history") loadHistory();
}

function showPairing(error) {
  showView("pair");
  $("pair-error").hidden = !error;
  if (error) $("pair-error").textContent = error;
  setStatus("off", "Not paired");
}

for (const b of document.querySelectorAll(".tabs button")) {
  b.addEventListener("click", () => token && showView(b.dataset.view));
}

$("pair-form").addEventListener("submit", (e) => {
  e.preventDefault();
  token = $("pair-token").value.trim();
  if (!token) return;
  saveToken(token);
  connect();
});

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2200);
}

refreshCount();
connect();
