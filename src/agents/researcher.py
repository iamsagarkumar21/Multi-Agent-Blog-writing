# src/agents/researcher.py

from langchain_core.tools import tool
from tavily import TavilyClient
from src.state import BlogState, ResearchResult
from src.llm import llm_fast
import os, json
from dotenv import load_dotenv

load_dotenv()
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


@tool
def web_search(query: str) -> dict:
    """Search the web for information about a topic."""
    results = tavily.search(query, max_results=5)
    return {
        "findings": [r["content"][:300] for r in results["results"]],
        "sources":  [r["url"] for r in results["results"]],
    }


# Iteration-specific queries give diverse coverage across retries
# [Production: never repeat the same query — you'll get the same results]
QUERY_TEMPLATES = {
    1: "{topic} tutorial guide explained",
    2: "{topic} best practices production architecture",
    3: "{topic} examples case studies real world",
}

EVAL_PROMPT = """You have {count} search results for: "{topic}"

Findings (first 100 chars each):
{findings}

Do these findings provide enough relevant coverage to write a technical blog post?

Return ONLY valid JSON — no explanation, no markdown:
{{"sufficient": true}} or {{"sufficient": false}}"""


def _is_sufficient(findings: list[str], topic: str, current_iter: int) -> bool:
    """
    Ask a fast LLM to judge if findings are good enough.
    Falls back to heuristic if LLM output can't be parsed.
    [Production: isolate judgment logic — easier to test and swap independently]
    """
    prompt = EVAL_PROMPT.format(
        count=len(findings),
        topic=topic,
        findings=json.dumps([f[:100] for f in findings], indent=2),
    )

    try:
        raw = llm_fast.invoke(prompt).content.strip()
        print(f"   🔬 RAW EVAL: {repr(raw)}")

        # Strip markdown fences if present
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()

        return json.loads(raw).get("sufficient", False)

    except Exception:
        # Fail open — if we can't parse the eval, trust the data we have
        return current_iter >= 1


def researcher_node(state: BlogState) -> dict:
    current_iter = state.research_iterations + 1

    # Build focused query for this iteration
    template = QUERY_TEMPLATES.get(current_iter, "{topic}")
    query = template.format(topic=state.topic)

    # Step 1: Search — called directly, not via LLM tool routing
    try:
        result = web_search.invoke({"query": query})
        findings = result["findings"]
        sources  = result["sources"]
    except Exception as e:
        return {"error": f"Search failed: {e}"}

    # Step 2: Evaluate sufficiency
    sufficient = _is_sufficient(findings, state.topic, current_iter)

    # Step 3: Heuristic override — don't loop forever on good data
    # [Production: LLM judgment is probabilistic — always pair with deterministic guardrails]
    if not sufficient and current_iter >= 2 and len(findings) >= 4:
        print("   ⚠️  Heuristic accept: sufficient findings after multiple iterations")
        sufficient = True

    research = ResearchResult(
        query=query,
        findings=findings,
        sources=sources,
        sufficient=sufficient,
    )

    print(f"   🔍 {len(findings)} findings | Sufficient: {sufficient} | Iter: {current_iter}")

    return {
        "research_results":    state.research_results + [research],
        "research_iterations": current_iter,
        "current_agent":       "planner" if sufficient else "researcher",
    }

