const $ = (s) => document.querySelector(s);
let skill = "reading";
let current = null;

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.add("hidden"));
    t.classList.add("active");
    $("#tab-" + t.dataset.tab).classList.remove("hidden");
    if (t.dataset.tab === "learned") loadProfile();
    if (t.dataset.tab === "chat") loadChat();
  };
});

async function api(path, body) {
  const opt = body !== undefined
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const esc = (s) => (s || "").replace(/</g, "&lt;");

// ---------- providers ----------
async function loadProviders() {
  try {
    const h = await api("/api/health");
    const active = h.providers.filter((p) => p.active).map((p) => p.name);
    const inactive = h.providers.filter((p) => !p.active).map((p) => p.name);
    $("#providers").innerHTML =
      `LLM fallback: ${active.map((n) => `<b>${n}</b>`).join(" → ") || "<span class='bad'>none</span>"}` +
      (inactive.length ? ` · inactive: ${inactive.join(", ")}` : "");
  } catch { $("#providers").textContent = ""; }
}

// ---------- profile / learning progress (cached, manual refresh) ----------
let progressCache = null; // { profile, known, due:Set }

function renderProgress() {
  if (!progressCache) return;
  const { profile, known, due } = progressCache;
  const lvl = profile.current_level || "A1";
  $("#level-label").textContent = lvl;
  $("#level-select").value = lvl;
  $("#known-head").textContent = `Known concepts (${known.length})`;

  if (!known.length) {
    $("#known").innerHTML = `<span class="muted">Nothing yet. Use the <b>Chat</b> tab
      or Quick add below — saved concepts show up here.</span>`;
    return;
  }
  // group by kind
  const groups = {};
  known.forEach((c) => (groups[c.kind] = groups[c.kind] || []).push(c));
  $("#known").innerHTML = Object.entries(groups).map(([kind, items]) => `
    <div class="kind-group">
      <div class="kind-label">${esc(kind)}</div>
      ${items.map((c) => {
        const details = [];
        if (c.description) details.push(esc(c.description));
        if (c.meta) for (const [k, v] of Object.entries(c.meta))
          details.push(`<b>${esc(k)}:</b> ${esc(typeof v === "string" ? v : JSON.stringify(v))}`);
        const body = details.length ? `<div class="concept-body">${details.join("<br>")}</div>` : "";
        return `<div class="concept ${details.length ? "has-body" : ""}">
          <div class="concept-top">
            <span class="chip ${due.has(c.code) ? "due" : ""}">${esc(c.level)}</span>
            <span class="concept-name">${esc(c.name)}</span>
            ${due.has(c.code) ? `<span class="due-tag">due for review</span>` : ""}
          </div>${body}</div>`;
      }).join("")}
    </div>`).join("");
}

async function loadProfile(force = false) {
  if (progressCache && !force) { renderProgress(); return; }
  $("#known").innerHTML = `<span class="muted">Loading…</span>`;
  try {
    const { profile, known } = await api("/api/profile");
    const due = new Set((await api("/api/review/due")).due.map((d) => d.code));
    progressCache = { profile, known, due };
    renderProgress();
  } catch (e) {
    $("#known").innerHTML = `<span class="bad small">Couldn't load progress: ${esc(e.message)}. Hit ↻ Refresh.</span>`;
  }
}
function invalidateProgress() { progressCache = null; }

$("#level-select").onchange = async (e) => {
  await api("/api/profile/level", { level: e.target.value });
  loadProfile(true);
};
$("#suggest-level").onclick = async () => {
  $("#suggest-level").disabled = true;
  try { const r = await api("/api/profile/suggest-level", {}); $("#level-label").textContent = r.level; }
  finally { $("#suggest-level").disabled = false; loadProfile(true); loadChat(); }
};
$("#refresh-known").onclick = () => loadProfile(true);

// ---------- intake (confirm-first) ----------
$("#analyze").onclick = async () => {
  const text = $("#intake-text").value.trim();
  if (!text) return;
  const btn = $("#analyze");
  btn.disabled = true; btn.textContent = "Analyzing…";
  try {
    const a = await api("/api/intake/analyze", { text });
    renderProposals(a);
  } catch (e) {
    $("#proposals").innerHTML = `<div class="bad small">Failed: ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = "Analyze"; loadChat(); }
};

function renderProposals(a) {
  if (!a.proposals || !a.proposals.length) {
    $("#proposals").innerHTML = `<div class="muted small">No concepts found. Try describing more.</div>`;
    return;
  }
  const rows = a.proposals.map((p, i) => `
    <div class="proposal" data-i="${i}">
      <div class="ptop">
        <input type="checkbox" class="keep" checked />
        <b>${esc(p.name)}</b> <span class="tag">${p.kind} · ${p.level}</span>
      </div>
      ${p.needs_clarification && p.question ? `
        <div class="clarify">❓ ${esc(p.question)}</div>
        <input type="text" class="answer" placeholder="Your answer (optional)…" />` : ""}
    </div>`).join("");
  $("#proposals").innerHTML =
    `<p class="muted small">${esc(a.summary || "")}</p>${rows}
     <div class="row"><button id="confirm" class="primary">Confirm selected</button>
       <span class="muted small">Nothing is saved until you confirm.</span></div>`;
  $("#confirm").onclick = confirmIntake;
  $("#proposals")._proposals = a.proposals;
}

async function confirmIntake() {
  const props = $("#proposals")._proposals || [];
  const items = [];
  document.querySelectorAll("#proposals .proposal").forEach((el) => {
    if (!el.querySelector(".keep").checked) return;
    const p = props[+el.dataset.i];
    const ans = el.querySelector(".answer");
    items.push({ name: p.name, kind: p.kind, level: p.level, ...(ans && ans.value.trim() ? { answer: ans.value.trim() } : {}) });
  });
  if (!items.length) { $("#proposals").innerHTML = ""; return; }
  const btn = $("#confirm");
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    const r = await api("/api/intake/confirm", { items });
    $("#proposals").innerHTML = `<div class="good small">Saved ${r.saved.length} concept(s). Level: <b>${r.level}</b> — ${esc(r.rationale || "")}</div>`;
    $("#intake-text").value = "";
    loadProfile(true);
  } catch (e) {
    $("#proposals").innerHTML = `<div class="bad small">Failed: ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = "Confirm selected"; loadChat(); }
}

// ---------- chat ----------
function bubble(role, content, applied) {
  const badges = (applied || []).length
    ? `<div class="applied">${applied.map((a) =>
        `<span class="badge ${a.op === "updated" ? "updated" : a.op === "removed" ? "removed" : ""}">${a.op} · ${esc(a.name || "")}</span>`).join("")}</div>`
    : "";
  return `<div class="bubble ${role}">${esc(content)}${badges}</div>`;
}

async function loadChat() {
  const { messages } = await api("/api/chat");
  const log = $("#chat-log");
  log.innerHTML = messages.length
    ? messages.map((m) => bubble(m.role, m.content, (m.meta || {}).applied)).join("")
    : `<div class="muted small">No messages yet. Say hello, or tell me what you know.</div>`;
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const ta = $("#chat-text");
  const text = ta.value.trim();
  if (!text) return;
  const btn = $("#chat-send");
  btn.disabled = true;
  const log = $("#chat-log");
  if (log.querySelector(".muted")) log.innerHTML = "";
  log.insertAdjacentHTML("beforeend", bubble("user", text));
  log.insertAdjacentHTML("beforeend", `<div class="bubble assistant" id="typing">…</div>`);
  log.scrollTop = log.scrollHeight;
  ta.value = "";
  try {
    const r = await api("/api/chat", { text });
    $("#typing").remove();
    log.insertAdjacentHTML("beforeend", bubble("assistant", r.reply, r.applied));
    log.scrollTop = log.scrollHeight;
    if ((r.applied || []).length) loadProfile(true); // refresh known concepts + level
  } catch (e) {
    const t = $("#typing"); if (t) t.remove();
    log.insertAdjacentHTML("beforeend", `<div class="bubble assistant bad">Failed: ${esc(e.message)}</div>`);
  } finally { btn.disabled = false; loadChat(); }
}

$("#chat-send").onclick = sendChat;
$("#chat-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});
$("#chat-reset").onclick = async () => {
  if (!confirm("Clear the whole conversation? (Your saved concepts stay.)")) return;
  await api("/api/chat/reset", {});
  loadChat();
};

// ---------- skills ----------
document.querySelectorAll(".skill").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".skill").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    skill = b.dataset.skill;
  };
});

// ---------- TTS ----------
function speak(text) {
  if (!("speechSynthesis" in window)) return alert("Speech synthesis not available in this browser.");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "fr-FR"; u.rate = 0.9;
  const fr = speechSynthesis.getVoices().find((v) => v.lang.startsWith("fr"));
  if (fr) u.voice = fr;
  speechSynthesis.speak(u);
}

// ---------- render ----------
function renderMcq(q, isListening) {
  const opts = Object.entries(q.options || {})
    .map(([k, v]) => `<button class="opt" data-k="${k}"><span class="key">${k.toUpperCase()}</span><span>${esc(v)}</span></button>`).join("");
  const top = isListening
    ? `<div class="row"><button id="play" class="primary">▶︎ Listen</button>
         <button id="replay">↻ Replay</button><span class="tag">spoken by your browser</span></div>`
    : `<div class="passage">${esc(q.passage)}</div>`;
  $("#card").innerHTML = `
    <div class="tag">${isListening ? "Listening" : "Reading"} · ${q.level} · ${esc(q.concept || "")}</div>
    ${top}<div class="qtext">${esc(q.question)}</div><div class="options">${opts}</div>`;
  if (isListening) {
    $("#play").onclick = () => speak(q.transcript);
    $("#replay").onclick = () => speak(q.transcript);
    setTimeout(() => speak(q.transcript), 300);
  }
  document.querySelectorAll(".opt").forEach((b) => (b.onclick = () => submitMcq(b.dataset.k)));
}

function renderWriting(q) {
  $("#card").innerHTML = `
    <div class="tag">Writing · ${q.level} · ${esc(q.concept || "")}</div>
    <div class="qtext">${esc(q.task)}</div>
    <div class="muted">Target length: ${esc(q.word_count || "")}</div>
    <ul>${(q.rubric || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    <textarea id="essay" placeholder="Write your answer in French…"></textarea>
    <div class="row"><button id="submit-essay" class="primary">Get feedback</button>
      <span class="muted" id="wc">0 words</span></div>`;
  const ta = $("#essay");
  ta.oninput = () => ($("#wc").textContent = `${ta.value.trim().split(/\s+/).filter(Boolean).length} words`);
  $("#submit-essay").onclick = submitWriting;
}

function renderSpeaking(q) {
  const block =
`You are a TCF (French) speaking examiner for a learner at level ${q.level}. My task:

"${q.task}"

Points to cover: ${(q.guidance || []).join("; ")}.

I'll give you my spoken answer (transcribed). Assess it against TCF criteria
(task fit, fluency, vocabulary, grammar, and pronunciation if possible), estimate my
CEFR level, then correct and explain my mistakes so I can improve.

My answer: """ [paste what you said here] """`;
  $("#card").innerHTML = `
    <div class="tag">Speaking · ${q.level} · ${esc(q.concept || "")}</div>
    <div class="qtext">${esc(q.task)}</div>
    <div class="muted">Prep: ${esc(q.prep_time || "")} · Speak: ${esc(q.speak_time || "")}</div>
    <ul>${(q.guidance || []).map((g) => `<li>${esc(g)}</li>`).join("")}</ul>
    <p class="muted small">Practice out loud, then copy this into any AI chat
       (e.g. Claude on your phone) with your answer to be graded and taught:</p>
    <pre class="copy">${esc(block)}</pre>
    <div class="row"><button id="copy" class="primary">Copy block</button>
      <button id="read-task">▶︎ Hear the task</button></div>`;
  $("#copy").onclick = async () => { await navigator.clipboard.writeText(block); $("#copy").textContent = "Copied ✓"; };
  $("#read-task").onclick = () => speak(q.task);
}

// ---------- actions ----------
async function generate() {
  const btn = $("#generate");
  btn.disabled = true; btn.textContent = "Generating…";
  $("#result").classList.add("hidden");
  try {
    current = await api("/api/generate", { skill, topic: $("#topic").value.trim() });
    const note = $("#ground-note");
    note.classList.remove("hidden");
    note.innerHTML = current.personalized
      ? `Built for level <b>${current.level}</b>${current.focus.length ? `, reinforcing: ${current.focus.map(esc).join(", ")}` : ""}.`
      : `⚠️ Not personalized yet — add what you know in <b>My progress</b> so exercises match you. (Level ${current.level})`;
    $("#card").classList.remove("hidden");
    if (skill === "reading") renderMcq(current, false);
    else if (skill === "listening") renderMcq(current, true);
    else if (skill === "writing") renderWriting(current);
    else renderSpeaking(current);
  } catch (e) {
    $("#card").classList.remove("hidden");
    $("#card").innerHTML = `<div class="bad">Generation failed: ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = "New exercise"; loadChat(); }
}

async function submitMcq(choice) {
  document.querySelectorAll(".opt").forEach((b) => (b.disabled = true));
  const res = await api("/api/grade/mcq", { question_id: current.question_id, choice });
  document.querySelectorAll(".opt").forEach((b) => {
    if (b.dataset.k === res.correct_option) b.classList.add("correct");
    else if (b.dataset.k === choice) b.classList.add("wrong");
  });
  $("#result").classList.remove("hidden");
  $("#result").innerHTML =
    `<div class="${res.correct ? "good" : "bad"}"><b>${res.correct ? "Correct!" : "Not quite."}</b>
       Answer: ${res.correct_option.toUpperCase()}</div><p>${esc(res.explanation || "")}</p>` +
    (res.transcript ? `<div class="passage"><b>Transcript:</b>\n${esc(res.transcript)}</div>` : "");
  loadProfile(true); loadChat();
}

async function submitWriting() {
  const text = $("#essay").value.trim();
  if (!text) return;
  const btn = $("#submit-essay");
  btn.disabled = true; btn.textContent = "Checking…";
  try {
    const r = await api("/api/grade/writing", { question_id: current.question_id, text });
    $("#result").classList.remove("hidden");
    $("#result").innerHTML = `
      <div>Estimated level: <span class="band">${r.overall_band || "?"}</span></div>
      <ul>${Object.entries(r.scores || {}).map(([k, v]) => `<li>${esc(k)}: <b>${esc(v)}</b></li>`).join("")}</ul>
      <p>${esc(r.feedback || "")}</p>
      ${(r.corrections || []).length ? `<b>Corrections:</b><ul>${r.corrections.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}`;
  } catch (e) {
    $("#result").classList.remove("hidden");
    $("#result").innerHTML = `<div class="bad">Failed: ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = "Get feedback"; loadProfile(true); loadChat(); }
}

$("#generate").onclick = generate;

loadProviders(); loadProfile(); loadChat();
if ("speechSynthesis" in window) speechSynthesis.getVoices();
