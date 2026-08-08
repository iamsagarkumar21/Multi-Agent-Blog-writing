# src/agents/editor.py

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from src.state import BlogState, BlogDraft, EditFeedback
from src.llm import llm
import json


EDITOR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a senior technical blog editor.
Review the draft critically and provide structured feedback.

Evaluate on these dimensions:
1. Accuracy      — are technical claims correct and specific?
2. Completeness  — does it cover the outline sections fully?
3. Clarity       — is it clear for the target audience?
4. Flow          — does it read naturally section to section?
5. Practicality  — does it give actionable insights, not just theory?

Respond ONLY with this JSON (no markdown):
{{
  "approved": true/false,
  "score": <1-10>,
  "issues": ["specific issue 1", "specific issue 2"],
  "suggestions": ["concrete fix 1", "concrete fix 2"]
}}

Approve (true) only if score >= 7 AND no critical accuracy issues.
Be specific in issues — "Section 3 lacks code examples" not "needs more detail"."""),

    ("human", """Topic: {topic}
Audience: {audience}
Tone: {tone}

Outline that was planned:
{outline}

Draft to review (revision {revision_count}):
{draft_content}

Previous feedback given (check if issues were fixed):
{previous_feedback}"""),
])


def _format_previous_feedback(feedback_list: list[EditFeedback]) -> str:
    """Format all previous feedback cycles for the editor to reference."""
    if not feedback_list:
        return "No previous feedback — this is the first review."

    formatted = []
    for i, fb in enumerate(feedback_list, 1):
        formatted.append(
            f"Review {i}:\n"
            f"  Issues: {json.dumps(fb.issues)}\n"
            f"  Suggestions: {json.dumps(fb.suggestions)}"
        )
    return "\n\n".join(formatted)


def editor_node(state: BlogState) -> dict:
    """
    Reviews the current draft.
    If approved → sets final_blog and signals completion.
    If rejected → appends feedback and signals writer to revise.
    [Production: editor sees ALL previous feedback — prevents the writer
    from fixing issue A while reintroducing issue B from a prior cycle]
    """
    draft    = state.draft
    outline  = state.outline
    chain    = EDITOR_PROMPT | llm | JsonOutputParser()

    try:
        config = {}
        if state.session_id:
            config["metadata"] = {
                "langfuse_session_id": state.session_id,
                "langfuse_tags": ["editor", f"revision-{state.revision_count + 1}"]
            }
        data = chain.invoke({
            "topic":             state.topic,
            "audience":          state.audience,
            "tone":              state.tone,
            "outline":           "\n".join(f"{i+1}. {s}"
                                 for i, s in enumerate(outline.sections)),
            "revision_count":    state.revision_count + 1,
            "draft_content":     draft.content[:3000],
            # [Production: cap draft passed to editor at 3000 chars —
            # editor needs to judge quality, not re-read every word]
            "previous_feedback": _format_previous_feedback(state.edit_feedback),
        }, config=config)


        feedback = EditFeedback(
            approved=data["approved"],
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
        )

        score = data.get("score", 0)
        print(f"   📊 Score: {score}/10 | Approved: {feedback.approved}")

        if feedback.issues:
            print(f"   🔍 Issues found:")
            for issue in feedback.issues:
                print(f"      • {issue}")

        # Build updated feedback list
        updated_feedback = state.edit_feedback + [feedback]

        if feedback.approved:
            print(f"   ✅ Draft approved on revision {state.revision_count + 1}")
            return {
                "edit_feedback": updated_feedback,
                "final_blog":    draft.content,
                "current_agent": "done",
                "error":         None,
            }
        else:
            print(f"   🔄 Sending back for revision {state.revision_count + 1}")
            return {
                "edit_feedback":  updated_feedback,
                "revision_count": state.revision_count + 1,
                "current_agent":  "writer",
                "error":          None,
            }

    except Exception as e:
        # If editor crashes, approve what we have rather than losing the draft
        # [Production: fail open on review — a draft is better than nothing]
        print(f"   ⚠️  Editor failed ({e}) — approving current draft")
        return {
            "final_blog":    state.draft.content,
            "current_agent": "done",
            "error":         None,
        }