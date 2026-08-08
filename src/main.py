import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.graph import blog_graph
from src.state import BlogState

load_dotenv()


def run(
    topic: str,
    audience: str = "developers",
    tone: str = "technical but approachable",
    output_path: str = "output_draft.md",
) -> None:
    import uuid
    session_id = f"cli-{uuid.uuid4().hex[:10]}"

    initial_state = BlogState(
        topic=topic,
        audience=audience,
        tone=tone,
        session_id=session_id,
    )


    from src.llm import langfuse_handler

    print(f"\n🚀 Starting blog agent: {topic}\n{'─'*50}")


    config = {}
    if langfuse_handler:
        # Dynamic naming following best practices
        langfuse_handler.trace_name = f"blog-agent-cli-{topic.lower().replace(' ', '-')[:30]}"
        config["callbacks"] = [langfuse_handler]
        config["metadata"] = {
            "langfuse_session_id": session_id,
            "langfuse_tags": ["cli", f"topic-{topic.lower().replace(' ', '-')[:20]}"]
        }

    for step in blog_graph.stream(initial_state.model_dump(), config=config):


        node_name   = list(step.keys())[0]
        node_output = step[node_name]

        print(f"\n✅ [{node_name.upper()}]")

        if node_name == "researcher":
            latest = node_output.get("research_results", [None])[-1]
            if latest:
                print(f"   🔍 {len(latest.findings)} findings | "
                      f"Sufficient: {latest.sufficient} | "
                      f"Iter: {node_output.get('research_iterations')}")

        if node_name == "planner" and node_output.get("outline"):
            o = node_output["outline"]
            print(f"   📋 {o.title}")
            for i, s in enumerate(o.sections, 1):
                print(f"      {i}. {s}")

        if node_name == "writer" and node_output.get("draft"):
            d = node_output["draft"]
            print(f"   📄 v{d.version} | {d.word_count} words")

        if node_name == "editor":
            fb = node_output.get("edit_feedback", [None])[-1]
            if fb:
                status = "✅ Approved" if fb.approved else "🔄 Revision needed"
                print(f"   {status}")

        if node_output.get("final_blog"):
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(node_output["final_blog"])
            print(f"\n💾 Final blog saved → {output_path}")

        if node_output.get("error"):
            print(f"   ❌ {node_output['error']}")

    print(f"\n{'─'*50}\n✅ Done. Open {output_path}")

    try:
        from src.llm import flush_langfuse
        flush_langfuse()
    except Exception:
        pass



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Blog Agent workflow from the terminal.")
    parser.add_argument("topic", nargs="?", default="Building multi-agent systems with LangGraph")
    parser.add_argument("--audience", default="developers")
    parser.add_argument("--tone", default="technical but approachable")
    parser.add_argument("--output", default="output_draft.md")
    args = parser.parse_args()

    run(args.topic, audience=args.audience, tone=args.tone, output_path=args.output)
