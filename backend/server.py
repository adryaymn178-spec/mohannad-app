import asyncio
import http.server
import json
import logging
import mimetypes
import os
import sys
import threading
import urllib.parse
import websockets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api
import auth
import database
import ws_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mohannad_server")

HTTP_PORT = int(os.environ.get("HTTP_PORT", 8000))
WS_PORT = int(os.environ.get("WS_PORT", 8001))
HOST = "0.0.0.0"

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads"))

class BroadcasterBridge:
    def __init__(self, loop):
        self.loop = loop

    def notify_owners(self, message):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_server.ws_manager.broadcast_to_owners(message), self.loop)

    def send_to_user(self, user_id, message):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_server.ws_manager.send_to_user(user_id, message), self.loop)

    def broadcast_chat_event(self, chat_id, message):
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM chat_members WHERE chat_id = ?", (chat_id,))
        members = [r[0] for r in cursor.fetchall()]
        conn.close()
        for m in members:
            self.send_to_user(m, message)
from fastapi import FastAPI
app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api.router, prefix="/api")

class MohannadHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def parse_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            raw_data = self.rfile.read(content_length)
            try:
                return json.loads(raw_data.decode("utf-8"))
            except Exception:
                return {}
        return {}

    def send_json(self, status_code: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_static_file(self, file_path: str):
        if not os.path.isfile(file_path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File Not Found")
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        file_size = os.path.getsize(file_path)
        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if "text" in mime_type or "javascript" in mime_type or "json" in mime_type else mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()

        with open(file_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                self.wfile.write(chunk)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Static / Uploads routing
        if path.startswith("/uploads/"):
            filename = os.path.basename(path)
            target = os.path.join(UPLOAD_DIR, filename)
            return self.serve_static_file(target)

        # REST API routing
        if path.startswith("/api/"):
            client_ip = self.client_address[0]
            if not auth.check_rate_limit(client_ip):
                return self.send_json(429, {"error": "تجاوزت الحد المسموح من الطلبات، يرجى الانتظار قليلاً."})

            if path == "/api/health":
                return self.send_json(200, {"status": "ok", "app": "مهند", "version": "1.0.0"})

            # Authenticated routes
            user = api_controller.authenticate_request(dict(self.headers))
            if not user:
                return self.send_json(401, {"error": "غير مصرح لك، يرجى تسجيل الدخول."})

            if path == "/api/users/me":
                code, res = api_controller.handle_get_me(user)
                return self.send_json(code, res)

            elif path == "/api/users/search":
                q = query.get("q", [""])[0]
                code, res = api_controller.handle_search_users(user, q)
                return self.send_json(code, res)

            elif path == "/api/chats":
                code, res = api_controller.handle_get_chats(user)
                return self.send_json(code, res)

            elif path.startswith("/api/chats/") and path.endswith("/messages"):
                chat_id = path.split("/")[3]
                code, res = api_controller.handle_get_messages(user, chat_id)
                return self.send_json(code, res)

            elif path == "/api/statuses":
                code, res = api_controller.handle_get_statuses(user)
                return self.send_json(code, res)

            elif path == "/api/calls":
                code, res = api_controller.handle_get_calls(user)
                return self.send_json(code, res)

            elif path == "/api/devices":
                code, res = api_controller.handle_get_devices(user)
                return self.send_json(code, res)

            elif path == "/api/admin/stats":
                code, res = api_controller.handle_get_admin_stats(user)
                return self.send_json(code, res)

            elif path == "/api/admin/login-requests":
                code, res = api_controller.handle_get_login_requests(user)
                return self.send_json(code, res)

            elif path == "/api/admin/users":
                search = query.get("q", [""])[0]
                code, res = api_controller.handle_get_admin_users(user, search)
                return self.send_json(code, res)

            elif path == "/api/backup/export":
                code, res = api_controller.handle_export_backup(user)
                return self.send_json(code, res)

            return self.send_json(404, {"error": "المسار غير موجود"})

        # Serve Frontend Static Files
        clean_path = path.lstrip("/")
        if not clean_path or clean_path == "/":
            clean_path = "index.html"

        file_path = os.path.join(STATIC_DIR, clean_path)
        if os.path.isfile(file_path):
            return self.serve_static_file(file_path)
        else:
            # SPA Fallback
            index_path = os.path.join(STATIC_DIR, "index.html")
            return self.serve_static_file(index_path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        client_ip = self.client_address[0]
        data = self.parse_body()

        if not auth.check_rate_limit(client_ip):
            return self.send_json(429, {"error": "تجاوزت الحد المسموح من الطلبات، يرجى الانتظار قليلاً."})

        # Public Auth Endpoints
        if path == "/api/auth/register":
            code, res = api_controller.handle_register(data, client_ip)
            return self.send_json(code, res)

        elif path == "/api/auth/login":
            user_agent = self.headers.get("User-Agent", "")
            code, res = api_controller.handle_login(data, client_ip, user_agent)
            return self.send_json(code, res)

        # Authenticated endpoints
        user = api_controller.authenticate_request(dict(self.headers))
        if not user:
            return self.send_json(401, {"error": "غير مصرح لك، يرجى تسجيل الدخول."})

        if path == "/api/auth/change-password":
            code, res = api_controller.handle_change_password(user, data)
            return self.send_json(code, res)

        elif path.startswith("/api/admin/login-requests/") and path.endswith("/approve"):
            request_id = path.split("/")[4]
            code, res = api_controller.handle_approve_request(user, request_id)
            return self.send_json(code, res)

        elif path.startswith("/api/admin/login-requests/") and path.endswith("/reject"):
            request_id = path.split("/")[4]
            code, res = api_controller.handle_reject_request(user, request_id)
            return self.send_json(code, res)

        elif path.startswith("/api/admin/users/") and path.endswith("/status"):
            target_user_id = path.split("/")[4]
            code, res = api_controller.handle_set_user_status(user, target_user_id, data)
            return self.send_json(code, res)

        elif path == "/api/chats":
            code, res = api_controller.handle_create_chat(user, data)
            return self.send_json(code, res)

        elif path == "/api/messages":
            code, res = api_controller.handle_send_message(user, data)
            return self.send_json(code, res)

        elif path == "/api/upload":
            code, res = api_controller.handle_upload(user, data)
            return self.send_json(code, res)

        elif path == "/api/statuses":
            code, res = api_controller.handle_post_status(user, data)
            return self.send_json(code, res)

        elif path == "/api/calls":
            code, res = api_controller.handle_record_call(user, data)
            return self.send_json(code, res)

        elif path == "/api/reports":
            code, res = api_controller.handle_create_report(user, data)
            return self.send_json(code, res)

        elif path == "/api/blocked":
            code, res = api_controller.handle_block_user(user, data)
            return self.send_json(code, res)

        return self.send_json(404, {"error": "المسار غير موجود"})

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        data = self.parse_body()
        user = api_controller.authenticate_request(dict(self.headers))
        if not user:
            return self.send_json(401, {"error": "غير مصرح لك."})

        if path == "/api/users/me":
            code, res = api_controller.handle_update_me(user, data)
            return self.send_json(code, res)

        return self.send_json(404, {"error": "المسار غير موجود"})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        user = api_controller.authenticate_request(dict(self.headers))
        if not user:
            return self.send_json(401, {"error": "غير مصرح لك."})

        if path.startswith("/api/messages/"):
            message_id = path.split("/")[3]
            code, res = api_controller.handle_delete_message(user, message_id, for_everyone=True)
            return self.send_json(code, res)

        elif path.startswith("/api/devices/"):
            session_id = path.split("/")[3]
            code, res = api_controller.handle_logout_device(user, session_id)
            return self.send_json(code, res)

        elif path.startswith("/api/blocked/"):
            target_id = path.split("/")[3]
            code, res = api_controller.handle_unblock_user(user, target_id)
            return self.send_json(code, res)

        return self.send_json(404, {"error": "المسار غير موجود"})

    def log_message(self, format, *args):
        # Concise logging
        logger.info("%s - %s", self.client_address[0], format % args)

def start_http_server():
    server = http.server.ThreadingHTTPServer((HOST, HTTP_PORT), MohannadHTTPRequestHandler)
    logger.info(f"Mohannad HTTP REST API Server running on http://{HOST}:{HTTP_PORT}")
    server.serve_forever()

def start_ws_server(loop):
    asyncio.set_event_loop(loop)
    async def run():
        logger.info(f"Mohannad WebSocket Server running on ws://{HOST}:{WS_PORT}")
        async with websockets.serve(ws_server.handle_ws_client, HOST, WS_PORT):
            await asyncio.Future() # run forever
    loop.run_until_complete(run())

def main():
    database.init_db()

    ws_loop = asyncio.new_event_loop()
    bridge = BroadcasterBridge(ws_loop)
    api_controller.set_ws_broadcaster(bridge)

    ws_thread = threading.Thread(target=start_ws_server, args=(ws_loop,), daemon=True)
    ws_thread.start()

    start_http_server()

if __name__ == "__main__":
    main()
