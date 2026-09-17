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
        raw = self.rfile.read(length) if length else b""
        try:
            request_body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            request_body = {}

        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        status, payload = self._respond(path, request_body)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _respond(path: str, body: dict) -> tuple[int, dict]:
        """登录接口业务规则（与 Story 一致），其余路径回退固定夹具。"""
        if path == "/api/login":
            phone = str(body.get("phone") or "").strip()
            code = str(body.get("code") or "").strip()
            if not phone:
                return 400, {"code": 400, "message": "手机号不能为空"}
            if not code:
                return 400, {"code": 400, "message": "验证码不能为空"}
            if len(phone) != 11 or not phone.isdigit():
                return 400, {"code": 400, "message": "手机号格式错误"}
            if code != "123456":
                return 400, {"code": 400, "message": "验证码错误"}
            return 200, {"code": 0, "message": "登录成功", "token": "demo-token"}
        return _FIXTURES.get(path, (404, {"code": 404, "message": "not found"}))

    def log_message(self, *args):  # noqa: A003 - silence
        return


def start_mock_api(host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, str]:
    """启动后台 HTTP 夹具服务，返回 (server, base_url)。"""
    server = ThreadingHTTPServer((host, 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{server.server_address[1]}"
    return server, base_url
