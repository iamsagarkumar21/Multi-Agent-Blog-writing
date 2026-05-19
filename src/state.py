# src/state.py

from typing import Annotated, Optional
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
import operator


# ─────────────────────────────────────────
# Sub-schemas — typed contracts per domain
# ─────────────────────────────────────────

class ResearchResult(BaseModel):
    query: str
    findings: list[str]
    sources: list[str]
    sufficient: bool          # agent's own judgment: is this enough to write?


class BlogOutline(BaseModel):
    title: str
    target_audience: str
    sections: list[str]
    estimated_word_count: int


class BlogDraft(BaseModel):
    title: str
    content: str
    word_count: int
    version: int              # tracks revision cycles


class EditFeedback(BaseModel):
    approved: bool
    issues: list[str]         # specific problems found
    suggestions: list[str]    # concrete fixes


# ─────────────────────────────────────────
# Master state — shared across ALL agents
# ─────────────────────────────────────────

class BlogState(BaseModel):

    # ── Input ──────────────────────────────
    topic: str
    audience: str = "general"
    tone: str = "professional"

    # ── Research phase ─────────────────────
    research_results: list[ResearchResult] = Field(default_factory=list)
    research_iterations: int = 0

    # ── Planning phase ─────────────────────
    outline: Optional[BlogOutline] = None

    # ── Writing phase ──────────────────────
    draft: Optional[BlogDraft] = None

    # ── Editing phase ──────────────────────
    edit_feedback: list[EditFeedback] = Field(default_factory=list)
    revision_count: int = 0

    # ── Control signals ────────────────────
    current_agent: str = "researcher"
    error: Optional[str] = None
    final_blog: Optional[str] = None

    # ── Production guardrails ──────────────
    max_research_iterations: int = 3   # prevent infinite search loops
    max_revision_cycles: int = 2       # prevent infinite edit loops