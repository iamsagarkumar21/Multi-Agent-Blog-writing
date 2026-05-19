# src/graph.py

from langgraph.graph import StateGraph, END
from src.state import BlogState
from src.agents.researcher import researcher_node
from src.agents.planner import planner_node
from src.agents.writer import writer_node
from src.agents.editor import editor_node


def route_after_research(state: BlogState) -> str:
    if state.error:
        return "end"
    if state.research_iterations >= state.max_research_iterations:
        return "planner"
    if state.research_results and state.research_results[-1].sufficient:
        return "planner"
    return "researcher"


def route_after_planner(state: BlogState) -> str:
    if state.error:
        return "end"
    if state.outline is None:
        return "end"
    return "writer"


def route_after_writer(state: BlogState) -> str:
    if state.error:
        return "end"
    if state.draft is None:
        return "end"
    return "editor"


def route_after_editor(state: BlogState) -> str:
    # Hard exit if final blog is set
    if state.final_blog:
        return "end"

    # Circuit breaker — never exceed max revision cycles
    # [Production: without this, writer↔editor can loop forever]
    if state.revision_count >= state.max_revision_cycles:
        print(f"   ⚠️  Max revisions reached — publishing current draft")
        return "end"

    # Send back to writer for another revision
    if state.current_agent == "writer":
        return "writer"

    return "end"


def build_graph():
    graph = StateGraph(BlogState)

    graph.add_node("researcher", researcher_node)
    graph.add_node("planner",    planner_node)
    graph.add_node("writer",     writer_node)
    graph.add_node("editor",     editor_node)

    graph.set_entry_point("researcher")

    graph.add_conditional_edges(
        "researcher",
        route_after_research,
        {"researcher": "researcher", "planner": "planner", "end": END}
    )

    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"writer": "writer", "end": END}
    )

    graph.add_conditional_edges(
        "writer",
        route_after_writer,
        {"editor": "editor", "end": END}
    )

    # The revision loop — editor can route back to writer
    graph.add_conditional_edges(
        "editor",
        route_after_editor,
        {"writer": "writer", "end": END}
    )

    return graph.compile()


blog_graph = build_graph()