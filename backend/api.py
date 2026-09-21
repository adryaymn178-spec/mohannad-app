import os
import sys

# ضمان مسار الاستيراد الداخلي
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import auth
import database
import ws_server

# راوتر نظيف تماماً بدون أي prefix مكرر
router = APIRouter()

# نماذج البيانات (Pydantic Models)
class RegisterSchema(BaseModel):
    username: str
    email: EmailStr
    password: str

class LoginSchema(BaseModel):
    username: str
    password: str

class MessageSchema(BaseModel):
    id: Optional[str] = None
    senderId: Optional[str] = None
    recipientId: str
    content: str
    timestamp: Optional[str] = None

# دالة مساعدة لاستخراج المستخدم الحالي من التوكن
def get_current_user_from_header(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="التوكن غير موجود")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="نوع التوكن غير صالح")
        user = auth.verify_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="رمز المصادقة غير صالح أو منتهي الصلاحية")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="فشل التحقق من هوية المستخدم")

# ==================== 1. مسارات المصادقة ====================

@router.post("/auth/register")
def register(payload: RegisterSchema):
    username = payload.username.strip()
    email = payload.email.strip()
    password = payload.password.strip()

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="جميع الحقول مطلوبة")

    existing_user = database.get_user_by_username(username)
    if existing_user:
        raise HTTPException(status_code=400, detail="اسم المستخدم مسجل مسبقاً")

    # تشفير كلمة المرور وحفظ المستخدم
    hashed_password = auth.hash_password(password)
    user = database.create_user(username=username, email=email, password=hashed_password)

    # إنشاء توكن JWT للمستخدم المسجل
    token = auth.create_access_token(data={"username": username, "email": email})

    return {
        "success": True,
        "message": "تم إنشاء الحساب بنجاح",
        "token": token,
        "user": {
            "username": username,
            "email": email
        }
    }

@router.post("/auth/login")
def login(payload: LoginSchema):
    username = payload.username.strip()
    password = payload.password.strip()

    user = database.get_user_by_username(username)
    if not user or not auth.verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")

    token = auth.create_access_token(data={"username": user["username"], "email": user.get("email", "")})

    return {
        "success": True,
        "token": token,
        "user": {
            "username": user["username"],
            "email": user.get("email", "")
        }
    }

# ==================== 2. مسارات جهات الاتصال ====================

@router.get("/contacts")
def get_contacts(current_user: dict = Depends(get_current_user_from_header)):
    contacts = database.get_all_contacts(exclude_username=current_user["username"])
    return contacts

# ==================== 3. مسارات الرسائل ====================

@router.get("/messages/{contact_id}")
def get_messages(contact_id: str, current_user: dict = Depends(get_current_user_from_header)):
    history = database.get_chat_history(user1=current_user["username"], user2=contact_id)
    return history

@router.post("/messages")
async def send_message(payload: MessageSchema, current_user: dict = Depends(get_current_user_from_header)):
    sender_id = current_user["username"]
    msg_data = {
        "id": payload.id or f"msg_{os.urandom(4).hex()}",
        "senderId": sender_id,
        "recipientId": payload.recipientId,
        "content": payload.content,
        "timestamp": payload.timestamp or ""
    }

    # حفظ الرسالة في قاعدة البيانات
    database.save_message(msg_data)

    # إرسال الرسالة فوراً عبر WebSocket إن كان الطرف الآخر متصلاً
    await ws_server.manager.send_personal_message(
        {"type": "message", "data": msg_data},
        recipient_id=payload.recipientId
    )

    return {"success": True, "data": msg_data}

# كلاس مغلّف للتوافقية
class APIHandler:
    def __init__(self):
        self.router = router