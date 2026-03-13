from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess
import hmac
import hashlib

SECRET = b"nano2026webhook"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        token = self.headers.get("X-Gitlab-Token", "")
        if token != SECRET.decode():
            self.send_response(403)
            self.end_headers()
            return
        subprocess.Popen(["/home/gcorthey/deploy.sh"])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 9000), Handler).serve_forever()
