# src/frontend.py

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
import sys
import argparse
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.editor import editor_node
from src.agents.planner import planner_node
from src.agents.researcher import researcher_node
from src.agents.writer import writer_node
from src.graph import (
    route_after_editor,
    route_after_planner,
    route_after_research,
    route_after_writer,
)
from src.state import BlogOutline, BlogState, EditFeedback

load_dotenv()

STATIC_DIR = ROOT / "static"
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

NODE_HANDLERS = {
    "researcher": researcher_node,
    "planner": planner_node,
    "writer": writer_node,
    "editor": editor_node,
}

ROUTERS = {
    "researcher": route_after_research,
    "planner": route_after_planner,
    "writer": route_after_writer,
    "editor": route_after_editor,
}


@dataclass
class RunSession:
    id: str
    state: BlogState
    status: str = "queued"
    next_agent: str = "researcher"
    default_next_agent: str | None = None
    checkpoint_agent: str | None = None
    pending_prompt: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    output_file: str | None = None
    error: str | None = None
    human_notes: list[str] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))

    def emit(self, kind: str, message: str, **payload: Any) -> None:
        event = {
            "id": len(self.events) + 1,
            "time": time.strftime("%H:%M:%S"),
            "kind": kind,
            "message": message,
            "payload": _jsonable(payload),
        }
        with self.condition:
            self.events.append(event)
            self.updated_at = time.time()
            self.condition.notify_all()


RUNS: dict[str, RunSession] = {}
RUNS_LOCK = threading.Lock()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _merge_state(state: BlogState, updates: dict[str, Any]) -> BlogState:
    data = state.model_dump()
    data.update(_jsonable(updates))
    return BlogState(**data)


def _route_after(agent: str, state: BlogState) -> str:
    route = ROUTERS[agent](state)
    return None if route == "end" else route


def _checkpoint_prompt(agent: str, state: BlogState, default_next: str | None) -> str:
    if agent == "researcher":
        latest = state.research_results[-1] if state.research_results else None
        if latest and latest.sufficient:
            return "Research looks sufficient. Continue to planning or ask for another search pass."
        return "Research finished this pass. Continue, request more research, or stop the run."
    if agent == "planner":
        return "Review or edit the outline before writing starts."
    if agent == "writer":
        return "Review the draft before editor review, request a human revision, or accept it as final."
    if agent == "editor" and state.final_blog:
        return "Editor approved the draft. Accept the final blog or send it back with notes."
    if agent == "editor" and default_next == "writer":
        return "Editor requested revisions. Continue to writer or add human notes first."
    return "Review this step before the workflow continues."


def _write_output(session: RunSession) -> None:
    content = session.state.final_blog or (session.state.draft.content if session.state.draft else "")
    if not content:
        return
    path = OUTPUT_DIR / f"{session.id}.md"
    path.write_text(content, encoding="utf-8")
    session.output_file = str(path.relative_to(ROOT))
    session.emit("artifact", f"Saved draft to {session.output_file}", output_file=session.output_file)


def _apply_human_feedback(session: RunSession, notes: str) -> None:
    clean_notes = notes.strip() or "Human requested another revision pass."
    feedback = EditFeedback(
        approved=False,
        issues=["Human review requested changes."],
        suggestions=[clean_notes],
    )
    data = session.state.model_dump()
    data["edit_feedback"] = _jsonable(session.state.edit_feedback + [feedback])
    data["revision_count"] = session.state.revision_count + 1
    data["current_agent"] = "writer"
    data["final_blog"] = None
    session.state = BlogState(**data)
    session.human_notes.append(clean_notes)
    session.emit("human", "Human revision notes added", notes=clean_notes)


def _run_worker(session: RunSession) -> None:
    session.status = "running"
    session.emit("system", "Run started", state=session.state)

    try:
        while session.next_agent:
            agent = session.next_agent
            session.status = "running"
            session.checkpoint_agent = None
            session.pending_prompt = None
            session.default_next_agent = None
            session.emit("agent_started", f"{agent.title()} started", agent=agent)

            updates = NODE_HANDLERS[agent](session.state)
            session.state = _merge_state(session.state, updates)
            session.emit("agent_finished", f"{agent.title()} finished", agent=agent, updates=updates, state=session.state)

            if session.state.error:
                session.error = session.state.error
                session.status = "failed"
                session.emit("error", session.state.error)
                return

            default_next = _route_after(agent, session.state)
            session.default_next_agent = default_next
            session.checkpoint_agent = agent
            session.pending_prompt = _checkpoint_prompt(agent, session.state, default_next)
            session.status = "waiting"
            session.emit(
                "checkpoint",
                session.pending_prompt,
                agent=agent,
                default_next_agent=default_next,
                state=session.state,
            )

            with session.condition:
                while session.status == "waiting":
                    session.condition.wait()

            if session.status in {"stopped", "failed", "completed"}:
                break

        if session.status not in {"stopped", "failed", "completed"}:
            session.status = "completed"
            _write_output(session)
            session.emit("completed", "Run completed", state=session.state)

    except Exception as exc:
        session.error = str(exc)
        session.status = "failed"
        session.emit("error", f"Run failed: {exc}")


def _session_summary(session: RunSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "status": session.status,
        "next_agent": session.next_agent,
        "default_next_agent": session.default_next_agent,
        "checkpoint_agent": session.checkpoint_agent,
        "pending_prompt": session.pending_prompt,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "output_file": session.output_file,
        "error": session.error,
        "human_notes": session.human_notes,
        "state": _jsonable(session.state),
    }


def _create_run(payload: dict[str, Any]) -> RunSession:
    run_id = uuid.uuid4().hex[:10]
    state = BlogState(
        topic=payload.get("topic", "").strip(),
        audience=payload.get("audience", "developers").strip() or "developers",
        tone=payload.get("tone", "technical but approachable").strip() or "technical but approachable",
        max_research_iterations=int(payload.get("max_research_iterations") or 3),
        max_revision_cycles=int(payload.get("max_revision_cycles") or 2),
    )
    session = RunSession(id=run_id, state=state)
    with RUNS_LOCK:
        RUNS[run_id] = session
    threading.Thread(target=_run_worker, args=(session,), daemon=True).start()
    return session


def _continue_run(session: RunSession, payload: dict[str, Any]) -> None:
    action = payload.get("action", "continue")
    notes = payload.get("notes", "")

    with session.condition:
        if session.status != "waiting":
            raise ValueError("Run is not waiting for human input.")

        if action == "stop":
            session.status = "stopped"
            session.next_agent = None
            session.emit("human", "Run stopped by human")

        elif action == "accept_final":
            data = session.state.model_dump()
            if session.state.draft and not session.state.final_blog:
                data["final_blog"] = session.state.draft.content
            data["current_agent"] = "done"
            session.state = BlogState(**data)
            session.status = "completed"
            session.next_agent = None
            _write_output(session)
            session.emit("human", "Draft accepted as final", state=session.state)

        elif action == "research_more":
            if session.state.research_iterations >= session.state.max_research_iterations:
                session.next_agent = "planner"
                session.emit("human", "Research limit reached; continuing to planner")
            else:
                session.next_agent = "researcher"
                session.emit("human", "Requested another research pass", notes=notes)
            session.status = "running"

        elif action == "revise":
            _apply_human_feedback(session, notes)
            session.next_agent = "writer"
            session.status = "running"

        elif action == "continue":
            outline = payload.get("outline")
            if outline and session.checkpoint_agent == "planner":
                data = session.state.model_dump()
                data["outline"] = BlogOutline(**outline).model_dump()
                session.state = BlogState(**data)
                session.emit("human", "Outline updated by human", outline=outline)
            session.next_agent = session.default_next_agent
            session.status = "running" if session.next_agent else "completed"
            if session.status == "completed":
                _write_output(session)
                session.emit("completed", "Run completed", state=session.state)
        else:
            raise ValueError(f"Unknown action: {action}")

        session.condition.notify_all()


class FrontendHandler(BaseHTTPRequestHandler):
    server_version = "BlogAgentFrontend/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(_jsonable(data)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _get_session(self, run_id: str) -> RunSession:
        with RUNS_LOCK:
            session = RUNS.get(run_id)
        if session is None:
            raise KeyError(run_id)
        return session

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path.removeprefix("/static/"))
        if path == "/api/runs":
            with RUNS_LOCK:
                runs = [_session_summary(run) for run in RUNS.values()]
            return self._send_json({"runs": runs})
        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[3]
            return self._stream_events(run_id, parse_qs(parsed.query))
        if path.startswith("/api/runs/"):
            run_id = path.split("/")[3]
            try:
                return self._send_json(_session_summary(self._get_session(run_id)))
            except KeyError:
                return self._send_json({"error": "Run not found"}, HTTPStatus.NOT_FOUND)

        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            payload = self._read_json()
            if path == "/api/runs":
                if not payload.get("topic", "").strip():
                    return self._send_json({"error": "Topic is required"}, HTTPStatus.BAD_REQUEST)
                session = _create_run(payload)
                return self._send_json(_session_summary(session), HTTPStatus.CREATED)

            if path.startswith("/api/runs/") and path.endswith("/control"):
                run_id = path.split("/")[3]
                session = self._get_session(run_id)
                _continue_run(session, payload)
                return self._send_json(_session_summary(session))

            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        except KeyError:
            self._send_json({"error": "Run not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_static(self, filename: str) -> None:
        path = (STATIC_DIR / filename).resolve()
        if STATIC_DIR not in path.parents and path != STATIC_DIR:
            return self._send_json({"error": "Invalid path"}, HTTPStatus.BAD_REQUEST)
        if not path.exists() or not path.is_file():
            return self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        content_type = "text/plain"
        if path.suffix == ".html":
            content_type = "text/html"
        elif path.suffix == ".css":
            content_type = "text/css"
        elif path.suffix == ".js":
            content_type = "application/javascript"

        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self, run_id: str, query: dict[str, list[str]]) -> None:
        try:
            session = self._get_session(run_id)
        except KeyError:
            return self._send_json({"error": "Run not found"}, HTTPStatus.NOT_FOUND)

        last_id = int(query.get("after", ["0"])[0] or 0)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        while True:
            with session.condition:
                events = [event for event in session.events if event["id"] > last_id]
                if not events and session.status not in {"completed", "failed", "stopped"}:
                    session.condition.wait(timeout=15)
                    events = [event for event in session.events if event["id"] > last_id]

            for event in events:
                last_id = event["id"]
                self.wfile.write(f"id: {last_id}\n".encode("utf-8"))
                self.wfile.write(b"event: run-event\n")
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()

            if session.status in {"completed", "failed", "stopped"} and not events:
                break

            self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()


def _available_port(host: str, preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"No free port found from {preferred_port} to {preferred_port + 49}")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    port = _available_port(host, port)
    server = ThreadingHTTPServer((host, port), FrontendHandler)
    print(f"Blog Agent UI running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the Blog Agent monitoring UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    serve(host=args.host, port=args.port)
