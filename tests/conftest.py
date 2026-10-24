import functools
import http.server
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OQIDA_HOME", str(tmp_path / "home"))
    yield


@pytest.fixture(scope="session")
def media_server(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(d / "sample.mp4")], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/sample.mp4"
    srv.shutdown()
