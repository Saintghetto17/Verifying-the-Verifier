"""Read-only local server for run directories and dataset images."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import DEFAULT_DATA_ROOT, DEFAULT_RUNS_ROOT, PROJECT_ROOT

VIEWER_ROOT = PROJECT_ROOT / "viewer"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class Handler(BaseHTTPRequestHandler):
    runs_root: Path = DEFAULT_RUNS_ROOT
    data_root: Path = DEFAULT_DATA_ROOT

    def log_message(self, *_args) -> None:
        return

    def _json(self, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _runs(self) -> list[dict]:
        out = []
        for path in sorted(self.runs_root.glob("*/run.json"), reverse=True):
            run = _read(path) or {}
            out.append({k: run.get(k) for k in ("run_id", "display_name", "status", "created_at", "summary")})
        return out

    def _run_dir(self, run_id: str) -> Path | None:
        path = (self.runs_root / run_id).resolve()
        return path if _inside(path, self.runs_root) and (path / "run.json").is_file() else None

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/api/runs":
            return self._json(self._runs())
        if path.startswith("/api/runs/"):
            parts = [p for p in path.split("/") if p]
            run_dir = self._run_dir(parts[2]) if len(parts) >= 3 else None
            if run_dir is None:
                return self.send_error(HTTPStatus.NOT_FOUND)
            if len(parts) == 3:
                samples = [json.loads(l) for l in (run_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
                return self._json({"run": _read(run_dir / "run.json"), "samples": samples})
            if len(parts) == 5 and parts[3] == "samples":
                pair_dir = (run_dir / "samples" / parts[4]).resolve()
                if not _inside(pair_dir, run_dir) or not (pair_dir / "pair.json").is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                detail = {"pair": _read(pair_dir / "pair.json")}
                for side in ("orig", "fail"):
                    detail[side] = {"request": _read(pair_dir / side / "request.json"),
                                    "result": _read(pair_dir / side / "result.json")}
                return self._json(detail)
            return self.send_error(HTTPStatus.NOT_FOUND)
        if path.startswith("/data/"):
            candidate = (self.data_root / path[len("/data/"):]).resolve()
            if not _inside(candidate, self.data_root):
                return self.send_error(HTTPStatus.FORBIDDEN)
            return self._file(candidate)
        if path in ("/", "/index.html"):
            return self._file(VIEWER_ROOT / "index.html")
        if path in ("/app.js", "/styles.css"):
            return self._file(VIEWER_ROOT / path.lstrip("/"))
        self.send_error(HTTPStatus.NOT_FOUND)


def serve(port: int = 8080, runs_root: Path = DEFAULT_RUNS_ROOT, data_root: Path = DEFAULT_DATA_ROOT) -> None:
    Handler.runs_root = runs_root.resolve()
    Handler.data_root = data_root.resolve()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Viewer: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
