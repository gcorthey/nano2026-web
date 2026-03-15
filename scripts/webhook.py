from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import subprocess
from pathlib import Path

SECRET = os.getenv("WEBHOOK_SECRET", "nano2026webhook").encode()
DEPLOY_SCRIPT = os.getenv(
    "DEPLOY_SCRIPT",
    str(Path(__file__).resolve().with_name("deploy.sh")),
)
HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.getenv("WEBHOOK_PORT", "9000"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        token = self.headers.get("X-Gitlab-Token", "")
        if token != SECRET.decode():
            self.send_response(403)
            self.end_headers()
            return
        subprocess.Popen([DEPLOY_SCRIPT])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


HTTPServer((HOST, PORT), Handler).serve_forever()
