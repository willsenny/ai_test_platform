"""
离线 API 夹具服务（Phase I 端到端验证用）。

当项目未配置 api_base_url 且需求含 API 场景时，process_doc 会启动一个
本地 HTTP 服务，让 api_server MCP 能真实发起请求（无需外部依赖）。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_FIXTURES = {
    "/api/login": (200, {"code": 0, "message": "ok", "token": "demo-token"}),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self._handle()

    def do_POST(self):  # noqa: N802
        self._handle()

    def do_PUT(self):  # noqa: N802
        self._handle()

    def do_DELETE(self):  # noqa: N802
        self._handle()

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        status, payload = _FIXTURES.get(path, (404, {"code": 404, "message": "not found"}))

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: A003 - silence
        return


def start_mock_api(host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, str]:
    """启动后台 HTTP 夹具服务，返回 (server, base_url)。"""
    server = ThreadingHTTPServer((host, 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{server.server_address[1]}"
    return server, base_url
