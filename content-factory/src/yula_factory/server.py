from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .audio import AudioScore, generate_original_audio
from .ledger import initialize_database, record_workflow_error
from .job import run_job
from .media_host import MEDIA_PREFIX, serve_signed_media
from .paths import inside_content_root
from .qa import inspect_folder
from .schedule import approve_plan, dispatch_due, plan_status, record_external_schedule, store_plan, submit_approved_now
from .secrets import config_value


class FactoryHandler(BaseHTTPRequestHandler):
    server_version = "YulaFactory/0.4"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = config_value("YULA_FACTORY_TOKEN")
        return bool(expected) and self.headers.get("Authorization") == f"Bearer {expected}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "yula-content-factory", "version": "0.4.0", "live_scheduler": os.environ.get("YULA_SCHEDULER_LIVE") == "1"})
        elif self.path.startswith(MEDIA_PREFIX):
            try:
                serve_signed_media(self)
            except PermissionError:
                self._json(403, {"error": "forbidden", "message": "Invalid or expired media URL"})
            except FileNotFoundError:
                self._json(404, {"error": "not_found", "message": "Media file is unavailable"})
        else:
            self._json(404, {"error": "not_found", "message": "Unknown endpoint"})

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path.startswith(MEDIA_PREFIX):
            try:
                serve_signed_media(self, head_only=True)
            except PermissionError:
                self.send_error(403)
            except FileNotFoundError:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/kie/callback":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValueError("Body must be between 1 and 1000000 bytes")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Callback body must be a JSON object")
                # Polling remains authoritative. This public, side-effect-free sink
                # exists only because Kie currently requires a reachable callback.
                self._json(200, {"status": "received"})
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": "validation_error", "message": str(exc)})
            return
        if not self._authorized():
            self._json(401, {"error": "unauthorized", "message": "A valid bearer token is required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Body must be between 1 and 1000000 bytes")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/v1/audio/generate":
                output = inside_content_root(Path(payload["output_path"]))
                score = AudioScore.from_dict(payload["score"])
                generate_original_audio(score, output, bool(payload.get("force", False)))
                self._json(201, {"status": "created", "output_path": str(output), "bytes": output.stat().st_size})
            elif self.path == "/v1/qa/folder":
                result = inspect_folder(Path(payload["folder_path"]))
                self._json(200, result)
            elif self.path == "/v1/errors/log":
                error_id = record_workflow_error(payload)
                self._json(201, {"status": "recorded", "error_id": error_id})
            elif self.path == "/v1/jobs/run":
                job_path = inside_content_root(Path(payload["job_path"]))
                self._json(200, run_job(job_path))
            elif self.path == "/v1/schedule/plan":
                plan_path = inside_content_root(Path(payload["plan_path"]))
                self._json(201, store_plan(plan_path, verify_files=bool(payload.get("verify_files", True))))
            elif self.path == "/v1/schedule/approve":
                self._json(200, approve_plan(int(payload["plan_id"]), str(payload["digest"])))
            elif self.path == "/v1/schedule/dispatch-due":
                self._json(200, dispatch_due(limit=int(payload.get("limit", 10)), live=bool(payload.get("live", False))))
            elif self.path == "/v1/schedule/submit-now":
                platforms = payload.get("platforms")
                if platforms is not None and not isinstance(platforms, list):
                    raise ValueError("platforms must be a list")
                self._json(200, submit_approved_now(int(payload["plan_id"]), platforms, live=bool(payload.get("live", False))))
            elif self.path == "/v1/schedule/record-external":
                self._json(200, record_external_schedule(int(payload["post_id"]), str(payload["external_id"])))
            elif self.path == "/v1/schedule/status":
                self._json(200, plan_status(int(payload["plan_id"])))
            else:
                self._json(404, {"error": "not_found", "message": "Unknown endpoint"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": "validation_error", "message": str(exc)})
        except FileExistsError as exc:
            self._json(409, {"error": "conflict", "message": str(exc)})
        except FileNotFoundError as exc:
            self._json(404, {"error": "not_found", "message": str(exc)})
        except Exception:
            self._json(500, {"error": "internal_error", "message": "The local worker failed; inspect its private log"})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def serve(host: str, port: int) -> None:
    if not config_value("YULA_FACTORY_TOKEN"):
        raise RuntimeError("Set YULA_FACTORY_TOKEN before starting the server")
    initialize_database()
    ThreadingHTTPServer((host, port), FactoryHandler).serve_forever()
