// ── DOM references ──────────────────────────────────────────────────────
const form           = document.querySelector("#run-form");
const timeline       = document.querySelector("#timeline");
const statusPill     = document.querySelector("#status-pill");
const checkpointText = document.querySelector("#checkpoint-text");
const humanNotes     = document.querySelector("#human-notes");
const continueBtn    = document.querySelector("#continue-btn");
const researchBtn    = document.querySelector("#research-btn");
const reviseBtn      = document.querySelector("#revise-btn");
const acceptBtn      = document.querySelector("#accept-btn");
const stopBtn        = document.querySelector("#stop-btn");
const clearLog       = document.querySelector("#clear-log");
const runTitle       = document.querySelector("#run-title");
const outlineEditor  = document.querySelector("#outline-editor");
const researchList   = document.querySelector("#research-list");
const overviewGrid   = document.querySelector("#overview-grid");
const draftPreview   = document.querySelector("#draft-preview");
const draftMeta      = document.querySelector("#draft-meta");
const metricResearch = document.querySelector("#metric-research");
const metricVersions = document.querySelector("#metric-versions");
const metricFeedback = document.querySelector("#metric-feedback");

// ── State ────────────────────────────────────────────────────────────────
let currentRunId    = null;
let eventSource     = null;
let currentRun      = null;
let completedAgents = new Set();

// ── Start a new run ──────────────────────────────────────────────────────
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  closeStream();
  timeline.innerHTML = "";
  completedAgents    = new Set();

  const payload = {
    topic:                  document.querySelector("#topic").value.trim(),
    audience:               document.querySelector("#audience").value.trim(),
    tone:                   document.querySelector("#tone").value.trim(),
    max_research_iterations: Number(document.querySelector("#max-research").value),
    max_revision_cycles:     Number(document.querySelector("#max-revisions").value),
  };

  const response = await fetch("/api/runs", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    addEvent({ kind: "error", time: "--", message: data.error || "Could not start run" });
    return;
  }
  currentRunId = data.id;
  currentRun   = data;
  renderRun(data);
  openStream(currentRunId);
});

// ── Control buttons ──────────────────────────────────────────────────────
clearLog.addEventListener("click", () => { timeline.innerHTML = ""; });

continueBtn.addEventListener("click", () => {
  const outline = parseOutlineIfNeeded();
  if (outline === false) return;
  sendControl({ action: "continue", outline });
});

researchBtn.addEventListener("click", () =>
  sendControl({ action: "research_more", notes: humanNotes.value }));

reviseBtn.addEventListener("click", () =>
  sendControl({ action: "revise", notes: humanNotes.value }));

acceptBtn.addEventListener("click", () =>
  sendControl({ action: "accept_final" }));

stopBtn.addEventListener("click", () =>
  sendControl({ action: "stop" }));

// ── Tab switching ────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-view").forEach((v) => v.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}`).classList.add("active");
  });
});

// ── SSE stream ──────────────────────────────────────────────────────────
function openStream(runId) {
  eventSource = new EventSource(`/api/runs/${runId}/events`);
  eventSource.addEventListener("run-event", async (event) => {
    const data = JSON.parse(event.data);
    addEvent(data);
    if (data.kind === "agent_finished" && data.payload?.agent) {
      completedAgents.add(data.payload.agent);
    }
    await refreshRun();
  });
  eventSource.onerror = () => {
    if (currentRun && ["completed", "failed", "stopped"].includes(currentRun.status)) {
      closeStream();
    }
  };
}

function closeStream() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}

// ── Polling fallback ─────────────────────────────────────────────────────
async function refreshRun() {
  if (!currentRunId) return;
  const response = await fetch(`/api/runs/${currentRunId}`);
  const data     = await response.json();
  if (response.ok) {
    currentRun = data;
    renderRun(data);
    if (["completed", "failed", "stopped"].includes(data.status)) closeStream();
  }
}

// ── Control API ──────────────────────────────────────────────────────────
async function sendControl(payload) {
  if (!currentRunId) return;
  const response = await fetch(`/api/runs/${currentRunId}/control`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    addEvent({ kind: "error", time: "--", message: data.error || "Control action failed" });
    return;
  }
  humanNotes.value = "";
  currentRun = data;
  renderRun(data);
}

// ── Outline parse helper ─────────────────────────────────────────────────
function parseOutlineIfNeeded() {
  if (!currentRun || currentRun.checkpoint_agent !== "planner") return undefined;
  const text = outlineEditor.value.trim();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    addEvent({ kind: "error", time: "--", message: "Outline JSON is invalid. Fix it before continuing." });
    return false;
  }
}

// ── Master render ────────────────────────────────────────────────────────
function renderRun(run) {
  const state   = run.state || {};
  const waiting = run.status === "waiting";

  // Header
  runTitle.textContent      = state.topic || "No run yet";
  statusPill.textContent    = titleCase(run.status || "idle");
  statusPill.className      = `status ${run.status || "idle"}`;
  checkpointText.textContent = run.pending_prompt || summarizeStatus(run.status);

  // Control button states
  continueBtn.disabled = !waiting;
  researchBtn.disabled = !waiting || run.checkpoint_agent !== "researcher";
  reviseBtn.disabled   = !waiting || !["writer", "editor"].includes(run.checkpoint_agent);
  acceptBtn.disabled   = !waiting || !state.draft;
  stopBtn.disabled     = !currentRunId || ["completed", "failed", "stopped"].includes(run.status);

  // Metrics
  metricResearch.textContent = state.research_iterations || 0;
  metricVersions.textContent = state.draft?.version       || 0;
  metricFeedback.textContent = state.edit_feedback?.length || 0;

  // Panels
  renderAgents(run);
  renderOverview(run);
  renderResearch(state);
  renderOutline(state);
  renderDraft(state);
}

// ── Agent strip ──────────────────────────────────────────────────────────
function renderAgents(run) {
  document.querySelectorAll("#agent-strip [data-agent]").forEach((node) => {
    const agent = node.dataset.agent;
    node.classList.toggle("active", run.next_agent === agent || run.checkpoint_agent === agent);
    node.classList.toggle("done",   completedAgents.has(agent));
  });
}

// ── Overview cards ───────────────────────────────────────────────────────
function renderOverview(run) {
  const state          = run.state || {};
  const feedback       = state.edit_feedback || [];
  const latestFeedback = feedback[feedback.length - 1];

  const cards = [
    ["Run ID",         run.id            || "Not started"],
    ["Status",         titleCase(run.status || "idle")],
    ["Active Agent",   run.checkpoint_agent || run.next_agent || state.current_agent || "—"],
    ["Output file",    run.output_file   || "Not saved yet"],
    ["Outline",        state.outline     ? `${state.outline.sections.length} sections` : "Pending"],
    ["Draft",          state.draft       ? `${state.draft.word_count} words · v${state.draft.version}` : "Pending"],
    ["Latest review",  latestFeedback    ? (latestFeedback.approved ? "✅ Approved" : "🔄 Needs revision") : "Pending"],
    ["Human notes",    run.human_notes?.length ? `${run.human_notes.length} note(s)` : "None"],
  ];

  overviewGrid.innerHTML = cards.map(([label, value]) => `
    <div class="stat-card">
      <h3>${escapeHtml(label)}</h3>
      <p>${escapeHtml(String(value))}</p>
    </div>
  `).join("");

  if (latestFeedback) {
    overviewGrid.insertAdjacentHTML("beforeend", `
      <div class="feedback-card">
        <h3>Issues</h3>
        ${listHtml(latestFeedback.issues)}
      </div>
      <div class="feedback-card">
        <h3>Suggestions</h3>
        ${listHtml(latestFeedback.suggestions)}
      </div>
    `);
  }
}

// ── Research panel ───────────────────────────────────────────────────────
function renderResearch(state) {
  const results = state.research_results || [];
  if (!results.length) {
    researchList.innerHTML = `<p class="muted">Research output will appear here once the researcher agent runs.</p>`;
    return;
  }
  researchList.innerHTML = results.map((result, index) => `
    <article class="research-card">
      <h3>Pass ${index + 1}: ${escapeHtml(result.query)}</h3>
      <p class="muted">Sufficient: <strong>${result.sufficient ? "Yes" : "No"}</strong></p>
      <ol>${(result.findings || []).map((f) => `<li>${escapeHtml(f)}</li>`).join("")}</ol>
      <ul>${(result.sources || []).map((s) => `<li><a href="${escapeAttr(s)}" target="_blank" rel="noreferrer">${escapeHtml(s)}</a></li>`).join("")}</ul>
    </article>
  `).join("");
}

// ── Outline editor ───────────────────────────────────────────────────────
function renderOutline(state) {
  if (!state.outline) {
    outlineEditor.value       = "";
    outlineEditor.placeholder = "Outline JSON will appear here once the planner finishes.";
    return;
  }
  const nextValue = JSON.stringify(state.outline, null, 2);
  // Don't overwrite if the user is actively editing
  if (document.activeElement !== outlineEditor && outlineEditor.value !== nextValue) {
    outlineEditor.value = nextValue;
  }
}

// ── Draft preview ────────────────────────────────────────────────────────
function renderDraft(state) {
  if (!state.draft) {
    draftMeta.textContent   = "No draft yet";
    draftPreview.innerHTML  = `<p class="muted">The writer output will appear here.</p>`;
    return;
  }
  draftMeta.textContent  = `${state.draft.word_count} words · version ${state.draft.version}`;
  draftPreview.innerHTML = markdownToHtml(state.draft.content);
}

// ── Timeline event card ──────────────────────────────────────────────────
function addEvent(event) {
  const el = document.createElement("article");
  el.className = `event ${event.kind || "system"}`;
  el.innerHTML = `
    <div class="event-head">
      <span>${escapeHtml(event.kind || "system")}</span>
      <span>${escapeHtml(event.time || "")}</span>
    </div>
    <p>${escapeHtml(event.message || "")}</p>
  `;
  timeline.prepend(el);
}

// ── Markdown → HTML (handles h1/h2/h3, bold, italic, inline-code, lists) ─
function markdownToHtml(markdown) {
  const lines = (markdown || "").split("\n");
  const html  = [];
  let paragraph = [];
  let inList    = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (inList) { html.push("</ul>"); inList = false; }
  };

  for (const raw of lines) {
    const line = raw;

    if (line.startsWith("### ")) {
      flushParagraph(); closeList();
      html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      flushParagraph(); closeList();
      html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      flushParagraph(); closeList();
      html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    } else if (/^[-*+] /.test(line)) {
      flushParagraph();
      if (!inList) { html.push("<ul>"); inList = true; }
      html.push(`<li>${inlineMarkdown(line.slice(2).trim())}</li>`);
    } else if (!line.trim()) {
      flushParagraph(); closeList();
    } else {
      if (inList) closeList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  closeList();
  return html.join("\n");
}

// Inline markdown: **bold**, *italic*, `code`
function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,     "<em>$1</em>")
    .replace(/`(.+?)`/g,       "<code>$1</code>");
}

// ── Utility helpers ──────────────────────────────────────────────────────
function listHtml(items) {
  if (!items?.length) return `<p class="muted">None</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function summarizeStatus(status) {
  const map = {
    running:   "Agents are running — the next checkpoint will appear automatically.",
    completed: "Run completed successfully.",
    failed:    "Run failed. Check the timeline for details.",
    stopped:   "Run was stopped manually.",
  };
  return map[status] || "Start a run to inspect each agent handoff.";
}

function titleCase(value) {
  return String(value || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&",  "&amp;")
    .replaceAll("<",  "&lt;")
    .replaceAll(">",  "&gt;")
    .replaceAll('"',  "&quot;")
    .replaceAll("'",  "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

// Initial idle render
renderRun({ status: "idle", state: {} });
