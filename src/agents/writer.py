# src/agents/writer.py

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from src.state import BlogState, BlogDraft, EditFeedback
from src.llm import llm
import json



SECTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert technical blog writer.
Write one section of a blog post. Be specific, practical, and engaging.

Rules:
- Write in {tone} tone
- Target audience: {audience}
- No filler phrases like "In this section we will..."
- Do NOT include the section title — just the content
- Length: {word_target} words approximately

Editor feedback to address (if revision):
{editor_feedback}"""),

    ("human", """Blog title: {title}

Full outline (for context):
{outline}

Research findings:
{findings}

Now write ONLY this section: "{section_title}"

Previous sections written (for continuity):
{previous_content}"""),
])


WRITER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert technical blog writer.
Write a complete, polished introduction for this blog post.

Rules:
- Hook the reader in the first sentence
- Clearly state what they will learn
- Tone: {tone}
- Audience: {audience}
- Length: 150-200 words"""),

    ("human", """Title: {title}
Topic: {topic}
Outline sections: {sections}"""),
])


def _format_feedback_for_writer(feedback_list: list) -> str:
    """Give the writer clear, actionable revision instructions."""
    if not feedback_list:
        return "No previous feedback."

    latest = feedback_list[-1]
    lines  = ["REVISION REQUIRED. Address these specific issues:\n"]

    for i, issue in enumerate(latest.issues, 1):
        lines.append(f"{i}. Issue: {issue}")

    lines.append("\nSuggested fixes:")
    for suggestion in latest.suggestions:
        lines.append(f"• {suggestion}")

    return "\n".join(lines)


def _get_findings_summary(state: BlogState) -> str:
    """Compress research into writer-friendly bullet points."""
    all_findings = []
    for r in state.research_results:
        all_findings.extend(r.findings)

    # Deduplicate + trim
    seen, unique = set(), []
    for f in all_findings:
        key = f[:50]
        if key not in seen:
            seen.add(key)
            unique.append(f[:200])

    return "\n".join(f"• {f}" for f in unique[:10])


def _words(text: str) -> int:
    return len(text.split())


def writer_node(state: BlogState) -> dict:
    outline   = state.outline
    findings  = _get_findings_summary(state)
    chain     = SECTION_PROMPT | llm | StrOutputParser()
    feedback  = _format_feedback_for_writer(state.edit_feedback)
    is_revision = state.revision_count > 0

    section_count     = len(outline.sections)
    words_per_section = outline.estimated_word_count // section_count

    sections_content = {}
    previous_content = ""

    if is_revision:
        print(f"   ✍️  Revising draft (cycle {state.revision_count})...")
    else:
        print(f"   ✍️  Writing {section_count} sections...")

    for i, section_title in enumerate(outline.sections):
        print(f"   📝 [{i+1}/{section_count}] {section_title}")

        try:
            content = chain.invoke({
                "tone":             state.tone,
                "audience":         state.audience,
                "word_target":      words_per_section,
                "title":            outline.title,
                "outline":          "\n".join(f"{j+1}. {s}"
                                    for j, s in enumerate(outline.sections)),
                "findings":         findings,
                "section_title":    section_title,
                "previous_content": previous_content[-800:] if previous_content
                                    else "This is the first section.",
                # Pass editor feedback into every section rewrite
                # [Production: writer needs full context of what was wrong
                # to avoid fixing one thing and breaking another]
                "editor_feedback":  feedback if is_revision else "First draft.",
            })

            sections_content[section_title] = content
            previous_content += f"\n\n## {section_title}\n{content}"

        except Exception as e:
            print(f"   ⚠️  Section '{section_title}' failed: {e}")
            sections_content[section_title] = f"[SECTION FAILED: {e}]"

    full_content = f"# {outline.title}\n\n"
    for section_title in outline.sections:
        full_content += f"## {section_title}\n\n"
        full_content += sections_content.get(section_title, "") + "\n\n"

    total_words = _words(full_content)
    version     = state.revision_count + 1
    print(f"   📊 {total_words} words | Version {version}")

    return {
        "draft":         BlogDraft(
                             title=outline.title,
                             content=full_content,
                             word_count=total_words,
                             version=version,
                         ),
        "current_agent": "editor",
        "error":         None,
    }