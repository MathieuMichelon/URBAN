"""Minimal static file server for the browser frontend."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FrontendRequestHandler(SimpleHTTPRequestHandler):
    """Serve the frontend app plus shared top-level assets."""

    def __init__(self, *args, frontend_root: Path, project_root: Path, **kwargs) -> None:
        self.frontend_root = frontend_root
        self.project_root = project_root
        super().__init__(*args, directory=str(frontend_root), **kwargs)

    def translate_path(self, path: str) -> str:
        """Expose `/assets/...` from the project root while serving the frontend app."""
        normalized = path.split("?", 1)[0].split("#", 1)[0]
        if normalized in {"", "/"}:
            return str(self.frontend_root / "index.html")
        if normalized.startswith("/assets/"):
            relative = normalized.removeprefix("/assets/")
            return str(self.project_root / "assets" / relative)
        return super().translate_path(path)


def main() -> None:
    """Serve the frontend directory on a fixed port for local or LAN access."""
    frontend_root = Path(__file__).resolve().parent
    project_root = frontend_root.parent

    def handler(*args, **kwargs):
        return FrontendRequestHandler(*args, frontend_root=frontend_root, project_root=project_root, **kwargs)

    server = ThreadingHTTPServer(("0.0.0.0", 4173), handler)

    print("Frontend available at http://127.0.0.1:4173")
    print("LAN access enabled on port 4173. Open the page with this machine IP from another PC.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
