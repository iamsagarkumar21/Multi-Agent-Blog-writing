# Blog Writing Multi-Agent System — Architectural Flow & Dry Run

> **How to read this file:** Top to bottom = one complete run of the system.
> Every section shows what happens inside a node, what goes in, what comes out, and what the graph decides next.
> This is not pseudocode — this is the exact execution path.

---

## The Full Graph Topology

```
User Input (topic, audience, tone)
        │
        ▼
┌───────────────┐
│  RESEARCHER   │ ◄─────────────────────┐
│               │                       │ (loop if not sufficient
└───────┬───────┘                       │  AND iterations < max)
        │                               │
        │  route_after_research()       │
        ├── sufficient=False ───────────┘
        ├── sufficient=True  ──────────────────────────┐
        └── iterations >= max ─────────────────────────┤
                                                        ▼
                                               ┌────────────────┐
                                               │    PLANNER     │
                                               └───────┬────────┘
                                                       │
                                                       │  route_after_planner()
                                                       ├── outline=None  ──► END
                                                       └── outline exists ──┐
                                                                            ▼
                                                               ┌────────────────┐
                                                               │    WRITER      │ ◄──────────────┐
                                                               └───────┬────────┘                │
                                                                       │                         │
                                                                       │  route_after_writer()    │
                                                                       ├── draft=None  ──► END   │
                                                                       └── draft exists ──┐      │
                                                                                          ▼      │
                                                                              ┌────────────────┐  │
                                                                              │     EDITOR     │  │
                                                                              └───────┬────────┘  │
                                                                                      │           │
                                                                                      │  route_after_editor()
                                                                                      ├── approved=True  ──► END (final_blog set)
                                                                                      ├── revisions < max ───────────────────────┘
                                                                                      └── revisions >= max ──► END (circuit breaker)
```

---

## The State Object — Shared Memory of the Entire System

This single object is the only way agents communicate. No agent calls another agent directly.

```python
BlogState {
    # ── INPUT (set once, never changed) ──────────────
    topic:                    "Building multi-agent systems with LangGraph"
    audience:                 "developers"
    tone:                     "technical but approachable"

    # ── RESEARCH PHASE (grows across iterations) ──────
    research_results:         []          → list[ResearchResult], appends each iteration
    research_iterations:      0           → int, increments each iteration

    # ── PLANNING PHASE (set once) ─────────────────────
    outline:                  None        → BlogOutline, set by planner

    # ── WRITING PHASE (overwritten on each revision) ──
    draft:                    None        → BlogDraft, version number increments

    # ── EDITING PHASE (grows across revisions) ────────
    edit_feedback:            []          → list[EditFeedback], appends each review
    revision_count:           0           → int, increments on each rejection

    # ── CONTROL SIGNALS (read by routing functions) ───
    current_agent:            "researcher"
    error:                    None        → str if any node fails
    final_blog:               None        → str, set when editor approves

    # ── CIRCUIT BREAKERS (hard limits) ────────────────
    max_research_iterations:  3           → researcher loops max 3 times
    max_revision_cycles:      2           → writer↔editor loops max 2 times
}
```

> **Why state is designed this way:**
> - `research_results` is a **list** (append) — planner needs ALL findings from all iterations, not just the latest
> - `edit_feedback` is a **list** (append) — editor in revision 2 must see what was wrong in revision 1 to verify it was fixed
> - `outline` and `draft` are **single values** (overwrite) — only one active outline/draft at a time
> - Circuit breakers live in **state**, not agent logic — routing functions are pure Python, agents are non-deterministic LLMs

---

## DRY RUN — Full Execution Trace

**Input:**
```
topic    = "Building multi-agent systems with LangGraph"
audience = "developers"
tone     = "technical but approachable"
```

---

### STEP 1 — Graph initialises

```
graph.stream(initial_state.model_dump())

State snapshot at t=0:
  topic                   = "Building multi-agent systems with LangGraph"
  research_results        = []
  research_iterations     = 0
  outline                 = None
  draft                   = None
  edit_feedback           = []
  revision_count          = 0
  current_agent           = "researcher"
  error                   = None
  final_blog              = None
```

Graph sets entry point → **RESEARCHER NODE**

---

### STEP 2 — Researcher Node (Iteration 1)

**What runs:**

```
current_iter = state.research_iterations + 1  →  1

query = QUERY_TEMPLATES[1].format(topic=...)
      = "Building multi-agent systems with LangGraph tutorial guide explained"

web_search.invoke({"query": query})
  → Tavily API called
  → Returns 5 results (content trimmed to 300 chars each)

findings = [
  "LangGraph is a library for building stateful, multi-actor applications...",
  "Multi-agent systems allow specialised AI agents to collaborate on complex tasks...",
  "LangGraph uses a StateGraph model where nodes represent agents and edges...",
  "Production LangGraph systems require careful state management using Pydantic...",
  "LangSmith provides observability for LangGraph runs with full trace visibility..."
]
sources = [
  "https://langchain-ai.github.io/langgraph/",
  "https://blog.langchain.dev/langgraph-multi-agent-workflows/",
  ...
]
```

**Evaluation step (separate, small model):**

```
llm_fast.invoke(eval_prompt)
  Prompt contains: topic + 5 findings trimmed to 100 chars each
  Returns: {"sufficient": true}   ← 8B model judges binary question

  sufficient = True
```

**Node returns (only changed fields):**

```python
{
    "research_results":    [ResearchResult(
                               query    = "Building multi-agent systems... tutorial guide explained",
                               findings = [...5 items...],
                               sources  = [...5 urls...],
                               sufficient = True
                           )],
    "research_iterations": 1,
    "current_agent":       "planner",
}
```

**State after RESEARCHER (iter 1):**

```
research_results      = [ResearchResult#1]   ← appended
research_iterations   = 1
current_agent         = "planner"
```

---

### STEP 3 — Routing: route_after_research()

```python
def route_after_research(state) -> str:
    if state.error:                                       → None, skip
    if state.research_iterations >= 3:                   → 1 >= 3? No, skip
    if state.research_results[-1].sufficient:            → True ✓
        return "planner"                                 ← ROUTE TO PLANNER
```

> **If sufficient had been False and iterations < 3:**
> The function returns `"researcher"` and the loop runs again with a new query template.
> On iteration 2 the query would be: `"...best practices production architecture"`
> On iteration 3 (max): regardless of sufficient, routes to `"planner"` anyway (circuit breaker)

---

### STEP 4 — Planner Node

**What runs:**

```
# Aggregate all research (currently just 1 iteration)
all_findings = research_results[0].findings  →  5 items
all_sources  = research_results[0].sources   →  5 urls

# Compress findings before passing to LLM
# [Token budget: deduplicate, trim to 150 chars, cap at 8 items]
findings_summary = [
  "LangGraph is a library for building stateful, multi-actor applications with LLMs...",
  "Multi-agent systems allow specialised AI agents to collaborate on complex...",
  "LangGraph uses a StateGraph model where nodes represent agents and edges...",
  "Production LangGraph systems require careful state management using Pydantic...",
  "LangSmith provides observability for LangGraph runs with full trace visibility..."
]
# 5 items × ~150 chars = ~750 chars passed to planner
# vs 5 items × 300 chars = ~1500 chars (without trimming)
# Over 3 iterations: 750 chars vs 4500 chars — token savings compound
```

**LLM call (70B model):**

```
Input:  topic + audience + tone + findings_summary (compressed)
Output: {
  "title": "Building Production-Grade Multi-Agent Systems with LangGraph",
  "target_audience": "Python developers familiar with LLMs and LangChain",
  "sections": [
    "Why Single Agents Hit a Ceiling",
    "LangGraph Core Concepts: StateGraph, Nodes, and Edges",
    "Designing Agent Responsibilities and Communication",
    "State Management and the Reducer Pattern",
    "Control Flow: Deterministic vs Dynamic Routing",
    "Production Concerns: Observability, Cost, and Failure Handling",
    "Putting It All Together: A Working Multi-Agent System"
  ],
  "estimated_word_count": 2800
}
```

**Node returns:**

```python
{
    "outline": BlogOutline(
        title                = "Building Production-Grade Multi-Agent Systems with LangGraph",
        target_audience      = "Python developers familiar with LLMs and LangChain",
        sections             = [...7 sections...],
        estimated_word_count = 2800
    ),
    "current_agent": "writer",
    "error":         None,
}
```

---

### STEP 5 — Routing: route_after_planner()

```python
def route_after_planner(state) -> str:
    if state.error:           → None, skip
    if state.outline is None: → outline exists, skip
    return "writer"           ← ROUTE TO WRITER
```

---

### STEP 6 — Writer Node (Version 1)

**What runs:**

```
outline   = state.outline          → 7 sections, est. 2800 words
findings  = _get_findings_summary(state)  → same compression as planner used
is_revision = state.revision_count > 0   → 0 > 0? False → first draft

words_per_section = 2800 // 7 = 400 words per section
```

**Internal section loop (7 LLM calls, sequential):**

```
Section 1/7: "Why Single Agents Hit a Ceiling"
  Input:  tone + audience + word_target(400) + title + full_outline
          + findings + section_title + previous_content("This is the first section.")
          + editor_feedback("First draft.")
  Output: ~420 words of content
  previous_content updated: "" → "## Why Single Agents...\n[420 words]"

Section 2/7: "LangGraph Core Concepts: StateGraph, Nodes, and Edges"
  Input:  same as above +
          previous_content[-800:] = last 800 chars of section 1
          [800 chars gives continuity without full context blowout]
  Output: ~390 words

Section 3/7: "Designing Agent Responsibilities and Communication"
  Input:  previous_content[-800:] = last 800 chars of section 2
  Output: ~410 words

... (sections 4, 5, 6, 7 follow same pattern) ...

Section 7/7: "Putting It All Together: A Working Multi-Agent System"
  Input:  previous_content[-800:] = last 800 chars of section 6
  Output: ~380 words
```

**Assembly:**

```
full_content = "# Building Production-Grade Multi-Agent Systems with LangGraph\n\n"
full_content += "## Why Single Agents Hit a Ceiling\n\n[~420 words]\n\n"
full_content += "## LangGraph Core Concepts...\n\n[~390 words]\n\n"
... (all 7 sections)

total_words = ~2750
```

**Node returns:**

```python
{
    "draft": BlogDraft(
        title      = "Building Production-Grade Multi-Agent Systems with LangGraph",
        content    = full_content,   # full markdown blog
        word_count = 2750,
        version    = 1,              # revision_count(0) + 1
    ),
    "current_agent": "editor",
    "error":         None,
}
```

---

### STEP 7 — Routing: route_after_writer()

```python
def route_after_writer(state) -> str:
    if state.error:         → None, skip
    if state.draft is None: → draft exists, skip
    return "editor"         ← ROUTE TO EDITOR
```

---

### STEP 8 — Editor Node (Review 1)

**What runs:**

```
draft            = state.draft          → v1, 2750 words
outline          = state.outline        → 7 sections
previous_feedback = _format_previous_feedback([])
                 = "No previous feedback — this is the first review."

# Cap draft passed to editor
# [Token budget: editor judges quality, doesn't need to re-read every word]
draft_content_passed = draft.content[:3000]   # first 3000 chars only
```

**LLM call (70B model):**

```
Input:  topic + audience + tone + outline(7 sections)
        + revision_count(1) + draft[:3000] + previous_feedback
Output: {
  "approved": false,
  "score": 6,
  "issues": [
    "Section 3 is too abstract — no code examples showing agent communication",
    "Section 5 routing explanation doesn't show the actual conditional edge syntax",
    "Introduction lacks a concrete hook — starts with definition not a problem"
  ],
  "suggestions": [
    "Add a short code snippet in Section 3 showing state read/write pattern",
    "Show the add_conditional_edges() call with the routing function in Section 5",
    "Rewrite first paragraph to open with a real failure scenario, not a definition"
  ]
}
```

**Node returns:**

```python
{
    "edit_feedback": [EditFeedback(      # appended to list
        approved    = False,
        issues      = [...3 issues...],
        suggestions = [...3 suggestions...],
    )],
    "revision_count": 1,               # incremented from 0
    "current_agent":  "writer",        # signal: send back for revision
    "error":          None,
}
```

---

### STEP 9 — Routing: route_after_editor() (Revision needed)

```python
def route_after_editor(state) -> str:
    if state.final_blog:                          → None, skip
    if state.revision_count >= 2:                 → 1 >= 2? No, skip
    if state.current_agent == "writer":           → True ✓
        return "writer"                           ← ROUTE BACK TO WRITER
```

> **Circuit breaker check:** revision_count is 1, max is 2. Loop continues.
> If revision_count had been 2 here, it would have routed to END regardless of approval.

---

### STEP 10 — Writer Node (Version 2 — Revision)

**What runs:**

```
is_revision    = state.revision_count > 0  →  1 > 0? True → revision mode
revision_count = 1

feedback = _format_feedback_for_writer(state.edit_feedback)
# Formats the LATEST feedback into writer instructions:
= """REVISION REQUIRED. Address these specific issues:

1. Issue: Section 3 is too abstract — no code examples showing agent communication
2. Issue: Section 5 routing explanation doesn't show the actual conditional edge syntax
3. Issue: Introduction lacks a concrete hook — starts with definition not a problem

Suggested fixes:
• Add a short code snippet in Section 3 showing state read/write pattern
• Show the add_conditional_edges() call with the routing function in Section 5
• Rewrite first paragraph to open with a real failure scenario, not a definition"""
```

**Internal section loop (7 LLM calls again, with feedback in prompt):**

```
Section 1/7: "Why Single Agents Hit a Ceiling"
  editor_feedback = [full feedback text above]
  [Writer rewrites introduction with real failure scenario as hook]

Section 2/7: "LangGraph Core Concepts..."
  [Less changed — no specific feedback on this section]

Section 3/7: "Designing Agent Responsibilities and Communication"
  [Writer adds code snippet showing state read/write]

Section 4/7: "State Management and the Reducer Pattern"
  [Minor revisions]

Section 5/7: "Control Flow: Deterministic vs Dynamic Routing"
  [Writer adds add_conditional_edges() example]

Section 6/7: "Production Concerns..."
  [Minor revisions]

Section 7/7: "Putting It All Together..."
  [Minor revisions]

total_words = ~2900  (slightly more with code examples added)
```

**Node returns:**

```python
{
    "draft": BlogDraft(
        title      = "Building Production-Grade Multi-Agent Systems with LangGraph",
        content    = full_content_v2,  # revised with code examples
        word_count = 2900,
        version    = 2,                # revision_count(1) + 1
    ),
    "current_agent": "editor",
    "error":         None,
}
```

---

### STEP 11 — Editor Node (Review 2)

**What runs:**

```
draft            = state.draft      → v2, 2900 words
previous_feedback = _format_previous_feedback(state.edit_feedback)
# Now contains Review 1 feedback — editor checks if issues were fixed:
= """Review 1:
  Issues: ["Section 3 is too abstract...", "Section 5 routing...", "Introduction..."]
  Suggestions: ["Add code snippet...", "Show add_conditional_edges...", "Rewrite first paragraph..."]"""

draft_content_passed = draft.content[:3000]   # first 3000 chars
```

**LLM call (70B model):**

```
Input:  same as before + previous_feedback now shows Review 1 issues
Output: {
  "approved": true,
  "score": 8,
  "issues": [],
  "suggestions": []
}
# Editor sees that prior issues (code in S3, edge syntax in S5, hook in intro)
# are now addressed in the v2 draft
```

**Node returns:**

```python
{
    "edit_feedback": [EditFeedback#1, EditFeedback(   # appended
        approved    = True,
        issues      = [],
        suggestions = [],
    )],
    "final_blog":    draft.content,     # ← this signals completion
    "current_agent": "done",
    "error":         None,
}
```

---

### STEP 12 — Routing: route_after_editor() (Approved)

```python
def route_after_editor(state) -> str:
    if state.final_blog:    → set ✓
        return "end"        ← ROUTE TO END
```

---

### STEP 13 — Graph exits

```
main.py detects final_blog in node_output
Writes to output_draft.md
Prints: "💾 Final blog saved → output_draft.md"
```

**Final state snapshot:**

```
topic                   = "Building multi-agent systems with LangGraph"
research_results        = [ResearchResult#1]          # 1 iteration was enough
research_iterations     = 1
outline                 = BlogOutline(7 sections)
draft                   = BlogDraft(v2, 2900 words)
edit_feedback           = [EditFeedback#1(rejected), EditFeedback#2(approved)]
revision_count          = 1
current_agent           = "done"
error                   = None
final_blog              = "# Building Production-Grade..."   # 2900 words
```

---

## Complete LLM Call Count

```
Node          │ Model           │ Calls │ Purpose
──────────────┼─────────────────┼───────┼──────────────────────────────────
Researcher    │ llama-3.1-8b    │  1    │ Sufficiency evaluation
Planner       │ llama-3.3-70b   │  1    │ Outline generation
Writer (v1)   │ llama-3.3-70b   │  7    │ One call per section
Editor (r1)   │ llama-3.3-70b   │  1    │ Quality review
Writer (v2)   │ llama-3.3-70b   │  7    │ One call per section (revision)
Editor (r2)   │ llama-3.3-70b   │  1    │ Quality review
──────────────┼─────────────────┼───────┼──────────────────────────────────
TOTAL         │                 │ 18    │
```

> **Token budget breakdown (approximate):**
> - Researcher eval: ~500 tokens in + ~20 out
> - Planner: ~800 tokens in + ~300 out
> - Each writer section: ~700 tokens in + ~600 out (×14 = 18,200)
> - Each editor review: ~1,200 tokens in + ~200 out (×2 = 2,800)
> - **Total: ~22,000 tokens across the full run**

---

## What Each Circuit Breaker Protects Against

```
Circuit Breaker               │ Default │ Protects Against
──────────────────────────────┼─────────┼──────────────────────────────────────────────
max_research_iterations = 3   │    3    │ Researcher looping forever if LLM keeps
                              │         │ returning sufficient=False despite good data
──────────────────────────────┼─────────┼──────────────────────────────────────────────
max_revision_cycles = 2       │    2    │ Writer↔Editor loop running indefinitely if
                              │         │ editor standards are too high or writer can't
                              │         │ improve further
──────────────────────────────┼─────────┼──────────────────────────────────────────────
draft_content[:3000]          │ 3000    │ Editor receiving the full 3000-word draft
(soft cap, not state field)   │ chars   │ every review = 3x token cost per review cycle
──────────────────────────────┼─────────┼──────────────────────────────────────────────
findings trimmed to 150 chars │  150    │ Planner receiving full 300-char findings ×
per item, capped at 8 items   │  ×8     │ all iterations = 413 token limit error
──────────────────────────────┼─────────┼──────────────────────────────────────────────
previous_content[-800:]       │  800    │ Writer context window growing unboundedly
                              │ chars   │ across 7 sections — section 7 would otherwise
                              │         │ carry all prior sections in its prompt
```

---

## Alternate Paths — What Could Have Happened Differently

### Path A: Researcher loops twice

```
Iteration 1: sufficient=False → route back to researcher
Iteration 2: sufficient=True  → route to planner
[Planner receives 2×ResearchResult objects — findings from both iterations aggregated]
```

### Path B: Research hits circuit breaker

```
Iteration 1: sufficient=False
Iteration 2: sufficient=False
Iteration 3: sufficient=False
route_after_research: iterations(3) >= max(3) → force route to "planner"
[Planner proceeds with whatever was found — better than infinite loop]
```

### Path C: Planner fails (bad JSON from LLM)

```
planner_node catches exception
returns: {"error": "Planner failed: JSONDecodeError..."}
route_after_planner reads state.error → routes to END
[Graph exits cleanly — error visible in LangSmith trace]
```

### Path D: One writer section fails

```
Section 4/7 LLM call raises exception
writer_node catches it: sections_content["Section 4"] = "[SECTION FAILED: ...]"
Loop continues for sections 5, 6, 7
Final draft contains a placeholder for section 4
Editor sees the placeholder → marks as issue → revision requested
[Partial failure tolerance — 6 good sections > 0 sections]
```

### Path E: Editor approves on first review (score >= 7, no critical issues)

```
Editor returns approved=True on review 1
route_after_editor: final_blog is set → routes to END
revision_count stays at 0
Total writer LLM calls: 7 (not 14)
[Happy path — saves 7 LLM calls and ~10 seconds of latency]
```

### Path F: Revision cycle hits circuit breaker

```
Editor rejects after revision 1 (score still < 7)
route_after_editor: revision_count(2) >= max_revision_cycles(2) → route to END
[Draft publishes as-is — a imperfect blog > no blog after burning budget]
```

---

## LangSmith — What You See in the Trace

```
Run: "Building multi-agent systems with LangGraph"
├── researcher                    [node]  450ms
│   ├── web_search               [tool]  820ms  → 5 results
│   └── llm_fast.invoke          [llm]   180ms  → {"sufficient": true}
│
├── planner                       [node]  1200ms
│   └── llm.invoke               [llm]   1200ms → BlogOutline (7 sections)
│
├── writer                        [node]  38000ms
│   ├── llm.invoke (section 1)   [llm]   5200ms
│   ├── llm.invoke (section 2)   [llm]   5100ms
│   ├── llm.invoke (section 3)   [llm]   5400ms
│   ├── llm.invoke (section 4)   [llm]   5300ms
│   ├── llm.invoke (section 5)   [llm]   5600ms
│   ├── llm.invoke (section 6)   [llm]   5500ms
│   └── llm.invoke (section 7)   [llm]   5900ms
│
├── editor                        [node]  1400ms
│   └── llm.invoke               [llm]   1400ms → approved=false, score=6
│
├── writer                        [node]  37000ms  ← second run of same node
│   ├── llm.invoke (section 1)   [llm]   5100ms
│   ... (7 calls)
│
└── editor                        [node]  1300ms
    └── llm.invoke               [llm]   1300ms → approved=true, score=8

Total wall time: ~80 seconds
Total tokens:    ~22,000
```

> **When something goes wrong:** click the node, click the LLM call inside it,
> see exact prompt (input) and exact response (output). No guessing.

---

## The One Mental Model to Remember

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Agent = a Python function that reads state, calls an LLM,    │
│            optionally calls a tool, writes back to state.       │
│                                                                 │
│   Graph  = the thing that decides which agent runs next,        │
│            based on what the last agent wrote to state.         │
│                                                                 │
│   State  = the only shared memory. The only communication       │
│            channel. The only source of truth.                   │
│                                                                 │
│   You    = the person who designs the state schema, the graph   │
│            topology, and the circuit breakers.                  │
│            The LLM fills in the content. You control the flow.  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```