# src/agents/planner.py

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from src.state import BlogState, BlogOutline
from src.llm import llm
import json


PLANNER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a senior content strategist.
Create a structured blog outline from research findings.

Rules:
- Sections must flow logically
- Each section title must be specific, not generic
- Match depth to audience level

Respond ONLY with this JSON (no markdown):
{{
  "title": "<compelling blog title>",
  "target_audience": "<audience description>",
  "sections": ["<section 1>", "<section 2>", ...],
  "estimated_word_count": <number>
}}"""),

    ("human", """Topic: {topic}
Audience: {audience}
Tone: {tone}

Key findings (summarised):
{findings}

Create the outline."""),
])


def _summarise_findings(research_results) -> str:
    """
    Compress all research into a tight summary for the planner.
    [Production pattern: summarise before passing between agents —
    never pass raw accumulated data downstream, it compounds token cost]
    """
    all_findings = []
    for result in research_results:
        all_findings.extend(result.findings)

    # Deduplicate + take best 8 + trim each to 150 chars
    seen = set()
    unique = []
    for f in all_findings:
        key = f[:50]
        if key not in seen:
            seen.add(key)
            unique.append(f[:150])   # trim aggressively

    return json.dumps(unique[:8], indent=2)


def planner_node(state: BlogState) -> dict:
    findings_summary = _summarise_findings(state.research_results)

    chain = PLANNER_PROMPT | llm | JsonOutputParser()

    try:
        config = {}
        if state.session_id:
            config["metadata"] = {
                "langfuse_session_id": state.session_id,
                "langfuse_tags": ["planner"]
            }
        data = chain.invoke({
            "topic":    state.topic,
            "audience": state.audience,
            "tone":     state.tone,
            "findings": findings_summary,
        }, config=config)


        outline = BlogOutline(
            title=data["title"],
            target_audience=data["target_audience"],
            sections=data["sections"],
            estimated_word_count=data["estimated_word_count"],
        )

        print(f"   📋 '{outline.title}' | {len(outline.sections)} sections")

        return {
            "outline":       outline,
            "current_agent": "writer",
            "error":         None,
        }

    except Exception as e:
        return {"error": f"Planner failed: {e}"}