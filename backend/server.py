import os
import sys

# ضمان وصول بايثون لكافة ملفات backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import api
import auth
import database
import ws_server

# إنشاء تطبيق FastAPI
app = FastAPI(title="mohannad-app")

# 1. إعداد CORS للسماح بالاتصال من Netlify وأي نطاق آخر
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. تهيئة قاعدة البيانات عند بدء التشغيل
@app.on_event("startup")
def startup_event():
    database.init_db()

# 3. تضمين مسارات الـ API (بـ /api وبدونها لضمان عدم حدوث 404 نهائياً)
app.include_router(api.router, prefix="/api", tags=["API With Prefix"])
app.include_router(api.router, tags=["API Direct"])

# 4. نقطة فحص عمل السيرفر (Health Check)
@app.get("/")
def root():
    return {"status": "ok", "app": "mohannad-app"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# 5. نقطة اتصال WebSocket للمحادثات الفورية
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    # محاولة قراءة التوكن من query params أو headers
    query_token = token or websocket.query_params.get("token")
    user = None
    if query_token:
        user = auth.verify_token(query_token)
    
    user_id = user["username"] if user else f"guest_{id(websocket)}"
    
    manager = ws_server.manager
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            await ws_server.handle_ws_message(manager, user_id, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        manager.disconnect(websocket, user_id)

# 6. دعم كلاس APIHandler في حال تم استدعاؤه قديماً
class APIHandler:
    def __init__(self):
        self.router = api.router

# 7. ربط ملفات Frontend في حال تشغيلها محلياً
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/client", StaticFiles(directory=frontend_dir, html=True), name="frontend")