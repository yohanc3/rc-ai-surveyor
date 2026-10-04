"""Dashboard, status, SSE, and audio endpoints."""

from __future__ import annotations

import json
import logging
import mimetypes
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .audio_store import AudioStore
from .events import EventBus, sse_comment, sse_frame
from .state import PipelineState

log = logging.getLogger("rc.server")

PROJECT_DIR = Path(__file__).resolve().parent.parent
# The React build is preferred when present; static/ is the dependency-free
# fallback so the dashboard still works before anyone runs npm.
VITE_DIST = PROJECT_DIR / "frontend" / "dist"
STATIC_DIR = PROJECT_DIR / "static"

# A dead client is only noticed when the next write fails, so this also bounds
# how long a disconnected subscriber can linger.
HEARTBEAT_SECONDS = 5.0


def dashboard_root() -> tuple[Path, str]:
    for root, name in ((VITE_DIST, "frontend/dist (React)"), (STATIC_DIR, "static (vanilla)")):
        if (root / "index.html").is_file():
            return root, name
    raise RuntimeError(
        "no dashboard files found. Run 'npm install && npm run build' in "
        "frontend/ while online, or restore static/index.html"
    )


def _make_skills_payload(state):
    def _skills_payload() -> dict:
        skills = getattr(state, "_skills", None)
        return skills.to_json() if skills else {"skills": [], "active_id": None}

    return _skills_payload


def make_handler(
    state: PipelineState, bus: EventBus, store: AudioStore, root: Path
) -> type[BaseHTTPRequestHandler]:
    _skills_payload = _make_skills_payload(state)

    class DashboardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "RCSurveyor/1.0"

        # ---------- plumbing ----------

        def _send(self, body: bytes, content_type: str, status: int = 200, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: object, status: int = 200) -> None:
            self._send(json.dumps(payload).encode("utf-8"), "application/json", status)

        # ---------- routing ----------

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]

            if path == "/api/status":
                self._send_json(state.snapshot())
            elif path == "/api/config":
                self._send_json(state.config_json())
            elif path == "/api/frame":
                self._send_frame()
            elif path == "/api/skills":
                self._send_json(_skills_payload())
            elif path == "/api/events":
                self._stream_events()
            elif path.startswith("/api/audio/"):
                self._send_audio(path[len("/api/audio/") :])
            elif path.startswith("/api/"):
                self._send_json({"error": "not found"}, 404)
            else:
                self._send_static("/index.html" if path == "/" else path)

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path != "/api/skill":
                self._send_json({"error": "not found"}, 404)
                return
            self._select_skill()

        def _select_skill(self) -> None:
            skills = getattr(state, "_skills", None)
            if skills is None:
                self._send_json({"error": "skills are not available"}, 503)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > 64 * 1024:
                self._send_json({"error": "a JSON body is required"}, 400)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json({"error": "body was not valid JSON"}, 400)
                return
            if not isinstance(payload, dict):
                self._send_json({"error": "body must be a JSON object"}, 400)
                return

            skill_id = payload.get("id")
            persona = payload.get("persona")
            if not isinstance(skill_id, str):
                self._send_json({"error": "id must be a string"}, 400)
                return
            if persona is not None and not isinstance(persona, str):
                self._send_json({"error": "persona must be a string"}, 400)
                return
            try:
                skills.select(skill_id, persona)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
                return

            payload = _skills_payload()
            # Tell every open dashboard, not just the one that clicked.
            bus.publish({"type": "skill_changed", **payload})
            log.info("skill_selected id=%s", skills.active().id)
            self._send_json(payload)

        # ---------- endpoints ----------

        def _send_frame(self) -> None:
            sequence, frame = state.latest_frame()
            if frame is None:
                self._send_json({"error": "no frame sampled yet"}, 503)
                return
            self._send(frame, "image/jpeg", extra={"X-Frame-Sequence": str(sequence)})

        def _send_audio(self, name: str) -> None:
            if not name.endswith(".mp3"):
                self._send_json({"error": "not found"}, 404)
                return
            path = store.path_for(name[: -len(".mp3")])
            if path is None:
                self._send_json({"error": "not found"}, 404)
                return
            self._send(path.read_bytes(), "audio/mpeg", extra={"Accept-Ranges": "none"})

        def _stream_events(self) -> None:
            """Server-Sent Events: backend to browser only."""
            subscriber = bus.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            try:
                # Replay current state so a reconnecting browser is immediately
                # consistent without waiting for the next analysis.
                snapshot = state.snapshot()
                self.wfile.write(sse_frame({"type": "hello", "status": snapshot}))
                if snapshot.get("latest_analysis"):
                    self.wfile.write(sse_frame(snapshot["latest_analysis"]))
                if snapshot.get("latest_audio"):
                    self.wfile.write(sse_frame(snapshot["latest_audio"]))
                self.wfile.flush()

                while True:
                    try:
                        event = subscriber.get(timeout=HEARTBEAT_SECONDS)
                    except queue.Empty:
                        self.wfile.write(sse_comment())
                        self.wfile.flush()
                        continue
                    self.wfile.write(sse_frame(event))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # browser went away
            finally:
                bus.unsubscribe(subscriber)

        def _send_static(self, path: str) -> None:
            candidate = (root / path.lstrip("/")).resolve()
            if root not in candidate.parents or not candidate.is_file():
                self._send_json({"error": "not found"}, 404)
                return
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or "javascript" in content_type:
                content_type += "; charset=utf-8"
            self._send(candidate.read_bytes(), content_type)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return DashboardHandler


def start_dashboard(
    port: int, state: PipelineState, bus: EventBus, store: AudioStore
) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    root, label = dashboard_root()
    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", port), make_handler(state, bus, store, root)
        )
    except OSError as error:
        raise RuntimeError(f"could not start dashboard on port {port}: {error}") from error
    server.daemon_threads = True

    thread = threading.Thread(target=server.serve_forever, name="dashboard", daemon=True)
    thread.start()
    return server, thread, label
