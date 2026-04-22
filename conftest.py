import sys
import pytest
import asyncio
import threading
import time
import uvicorn
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# ── Run real uvicorn server in background thread for tests ────────────────────

class UvicornTestServer:
    def __init__(self, host="127.0.0.1", port=8001):
        self.host = host
        self.port = port
        self._thread = None
        self._server = None

    def start(self):
        from app.main import app
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="error")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        # Wait for server to be ready
        for _ in range(30):
            try:
                import httpx
                httpx.get(f"http://{self.host}:{self.port}/")
                break
            except Exception:
                time.sleep(0.3)

    def stop(self):
        if self._server:
            self._server.should_exit = True


_server = UvicornTestServer()


def pytest_sessionstart(session):
    _server.start()


def pytest_sessionfinish(session, exitstatus):
    _server.stop()


# ── Client fixture pointing at real server ────────────────────────────────────

@pytest.fixture
async def client():
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=30) as c:
        yield c