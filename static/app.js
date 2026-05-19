const form = document.querySelector("#run-form");
const timeline = document.querySelector("#timeline");
const statusPill = document.querySelector("#status-pill");
const checkpointText = document.querySelector("#checkpoint-text");
const humanNotes = document.querySelector("#human-notes");
const continueBtn = document.querySelector("#continue-btn");
const researchBtn = document.querySelector("#research-btn");
const reviseBtn = document.querySelector("#revise-btn");
const acceptBtn = document.querySelector("#accept-btn");
const stopBtn = document.querySelector("#stop-btn");
const clearLog = document.querySelector("#clear-log");
const runTitle = document.querySelector("#run-title");
const rawState = document.querySelector("#raw-state");
const outlineEditor = document.querySelector("#outline-editor");
const researchList = document.querySelector("#research-list");
const overviewGrid = document.querySelector("#overview-grid");
const draftPreview = document.querySelector("#draft-preview");
const draftMeta = document.querySelector("#draft-meta");
const metricResearch = document.querySelector("#metric-research");
const metricVersions = document.querySelector("#metric-versions");
const metricFeedback = document.querySelector("#metric-feedback");

let currentRunId = null;
let eventSource = null;
let currentRun = null;
let completedAgents = new Set();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  closeStream();
  timeline.innerHTML = "";
  completedAgents = new Set();

  const payload = {
    topic: document.querySelector("#topic").value,
    audience: document.querySelector("#audience").value,
    tone: document.querySelector("#tone").value,
    max_research_iterations: Number(document.querySelector("#max-research").value),
    max_revision_cycles: Number(document.querySelector("#max-revisions").value),
  };

  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    addEvent({ kind: "error", time: "--", message: data.error || "Could not start run" });
    return;
  }
  currentRunId = data.id;
  currentRun = data;
  renderRun(data);
  openStream(currentRunId);
});

clearLog.addEventListener("click", () => {
  timeline.innerHTML = "";
});

continueBtn.addEventListener("click", () => {
  const outline = parseOutlineIfNeeded();
  if (outline === false) return;
  sendControl({ action: "continue", outline });
});

researchBtn.addEventListener("click", () => {
  sendControl({ action: "research_more", notes: humanNotes.value });
});

reviseBtn.addEventListener("click", () => {
  sendControl({ action: "revise", notes: humanNotes.value });
});

acceptBtn.addEventListener("click", () => {
  sendControl({ action: "accept_final" });
});

stopBtn.addEventListener("click", () => {
  sendControl({ action: "stop" });
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".tab-view").forEach((view) => view.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}`).classList.add("active");
  });
});

function openStream(runId) {
  eventSource = new EventSource(`/api/runs/${runId}/events`);
  eventSource.addEventListener("run-event", async (event) => {
    const data = JSON.parse(event.data);
    addEvent(data);
    if (data.kind === "agent_finished" && data.payload.agent) {
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
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

async function refreshRun() {
  if (!currentRunId) return;
  const response = await fetch(`/api/runs/${currentRunId}`);
  const data = await response.json();
  if (response.ok) {
    currentRun = data;
    renderRun(data);
    if (["completed", "failed", "stopped"].includes(data.status)) {
      closeStream();
    }
  }
}

async function sendControl(payload) {
  if (!currentRunId) return;
  const response = await fetch(`/api/runs/${currentRunId}/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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

function parseOutlineIfNeeded() {
  if (!currentRun || currentRun.checkpoint_agent !== "planner") return undefined;
  const text = outlineEditor.value.trim();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch (error) {
    addEvent({ kind: "error", time: "--", message: "Outline JSON is invalid. Fix it before continuing." });
    return false;
  }
}

function renderRun(run) {
  const state = run.state || {};
  runTitle.textContent = state.topic || "No run yet";
  statusPill.textContent = titleCase(run.status || "idle");
  statusPill.className = `status ${run.status || "idle"}`;
  checkpointText.textContent = run.pending_prompt || summarizeStatus(run.status);

  const waiting = run.status === "waiting";
  continueBtn.disabled = !waiting;
  researchBtn.disabled = !waiting || run.checkpoint_agent !== "researcher";
  reviseBtn.disabled = !waiting || !["writer", "editor"].includes(run.checkpoint_agent);
  acceptBtn.disabled = !waiting || !state.draft;
  stopBtn.disabled = !currentRunId || ["completed", "failed", "stopped"].includes(run.status);

  metricResearch.textContent = state.research_iterations || 0;
  metricVersions.textContent = state.draft?.version || 0;
  metricFeedback.textContent = state.edit_feedback?.length || 0;

  renderAgents(run);
  renderOverview(run);
  renderResearch(state);
  renderOutline(state);
  renderDraft(state);
  rawState.textContent = JSON.stringify(state, null, 2);
}

function renderAgents(run) {
  document.querySelectorAll("#agent-strip [data-agent]").forEach((node) => {
    const agent = node.dataset.agent;
    node.classList.toggle("active", run.next_agent === agent || run.checkpoint_agent === agent);
    node.classList.toggle("done", completedAgents.has(agent));
  });
}

function renderOverview(run) {
  const state = run.state || {};
  const feedback = state.edit_feedback || [];
  const latestFeedback = feedback[feedback.length - 1];
  const cards = [
    ["Run ID", run.id || "Not started"],
    ["Status", titleCase(run.status || "idle")],
    ["Current Agent", run.checkpoint_agent || run.next_agent || state.current_agent || "none"],
    ["Output", run.output_file || "Not saved yet"],
    ["Outline", state.outline ? `${state.outline.sections.length} sections` : "Pending"],
    ["Draft", state.draft ? `${state.draft.word_count} words, v${state.draft.version}` : "Pending"],
    ["Latest Review", latestFeedback ? (latestFeedback.approved ? "Approved" : "Needs revision") : "Pending"],
    ["Human Notes", run.human_notes?.length ? `${run.human_notes.length} note(s)` : "None"],
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

function renderResearch(state) {
  const results = state.research_results || [];
  if (!results.length) {
    researchList.innerHTML = `<p class="muted">Research output will appear here.</p>`;
    return;
  }

  researchList.innerHTML = results.map((result, index) => `
    <article class="research-card">
      <h3>Pass ${index + 1}: ${escapeHtml(result.query)}</h3>
      <p class="muted">Sufficient: ${result.sufficient ? "yes" : "no"}</p>
      <ol>${(result.findings || []).map((finding) => `<li>${escapeHtml(finding)}</li>`).join("")}</ol>
      <ul>${(result.sources || []).map((source) => `<li><a href="${escapeAttr(source)}" target="_blank" rel="noreferrer">${escapeHtml(source)}</a></li>`).join("")}</ul>
    </article>
  `).join("");
}

function renderOutline(state) {
  if (!state.outline) {
    outlineEditor.value = "";
    outlineEditor.placeholder = "Outline JSON will appear here once planner finishes.";
    return;
  }
  const nextValue = JSON.stringify(state.outline, null, 2);
  if (document.activeElement !== outlineEditor && outlineEditor.value !== nextValue) {
    outlineEditor.value = nextValue;
  }
}

function renderDraft(state) {
  if (!state.draft) {
    draftMeta.textContent = "No draft yet";
    draftPreview.innerHTML = `<p class="muted">The writer output will appear here.</p>`;
    return;
  }
  draftMeta.textContent = `${state.draft.word_count} words · version ${state.draft.version}`;
  draftPreview.innerHTML = markdownToHtml(state.draft.content);
}

function addEvent(event) {
  const element = document.createElement("article");
  element.className = `event ${event.kind || "system"}`;
  element.innerHTML = `
    <div class="event-head">
      <span>${escapeHtml(event.kind || "system")}</span>
      <span>${escapeHtml(event.time || "")}</span>
    </div>
    <p>${escapeHtml(event.message || "")}</p>
  `;
  timeline.prepend(element);
}

function markdownToHtml(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let paragraph = [];

  const flush = () => {
    if (paragraph.length) {
      html.push(`<p>${escapeHtml(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };

  for (const line of lines) {
    if (line.startsWith("# ")) {
      flush();
      html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    } else if (line.startsWith("## ")) {
      flush();
      html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    } else if (!line.trim()) {
      flush();
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return html.join("");
}

function listHtml(items) {
  if (!items || !items.length) return `<p class="muted">None</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function summarizeStatus(status) {
  if (status === "running") return "Agents are running. The next human gate will appear automatically.";
  if (status === "completed") return "Run completed.";
  if (status === "failed") return "Run failed. Check the timeline and raw state.";
  if (status === "stopped") return "Run stopped.";
  return "Start a run to inspect each agent handoff.";
}

function titleCase(value) {
  return String(value || "").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

renderRun({ status: "idle", state: {} });
