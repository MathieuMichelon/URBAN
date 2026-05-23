"""FastAPI entrypoint for the authoritative Urban Duel multiplayer backend."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import uvicorn

from net.gateway import ClientConnection, WebSocketGateway
from rooms.manager import RoomManager


def create_app(cards_path: str | Path | None = None) -> FastAPI:
    """Build a FastAPI app with a fresh room manager and WebSocket gateway."""
    project_root = Path(__file__).resolve().parents[1]
    resolved_cards_path = Path(cards_path) if cards_path is not None else project_root / "assets" / "data" / "urban2_personnages_base.json"
    frontend_root = project_root / "frontend"
    assets_root = project_root / "assets"

    room_manager = RoomManager(resolved_cards_path)
    gateway = WebSocketGateway(room_manager)

    app = FastAPI(title="Urban Duel Online", version="1.0.0")
    app.state.room_manager = room_manager
    app.state.gateway = gateway

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Small health endpoint for local development."""
        return {"status": "ok"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Accept one browser client and process JSON WebSocket messages."""
        await websocket.accept()
        connection = ClientConnection(websocket=websocket)

        try:
            while True:
                payload = await websocket.receive_json()
                await gateway.handle_raw_message(connection, payload)
        except WebSocketDisconnect:
            await gateway.handle_disconnect(connection)

    app.mount("/assets", StaticFiles(directory=assets_root), name="assets")
    app.mount("/", StaticFiles(directory=frontend_root, html=True), name="frontend")

    return app


app = create_app()


def main() -> None:
    """Run the FastAPI backend locally with one Python command."""
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
