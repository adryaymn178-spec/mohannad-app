"""
=============================================================================
Project: mohannad-app
File: backend/api.py
Description: Complete REST API Engine for Full-Stack Messaging Application
Features:
  - User Registration & Authentication (تسجيل مستخدم جديد وتسجيل الدخول)
  - Direct & Group Messaging (إرسال واستقبال الرسائل والمحادثات)
  - Contacts Management (جهات الاتصال والبحث والحظر)
  - Chat Groups Management (إدارة المجموعات والأعضاء)
  - Owner / Admin Dashboard (لوحة تحكم المالك والإحصائيات والتحكم)
  - Multi-Device Session Management (إدارة الجلسات والأجهزة النشطة)
=============================================================================
"""

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import secrets
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

try:
    from fastapi import (
        APIRouter,
        Depends,
        FastAPI,
        Header,
        HTTPException,
        Query,
        Request,
        status,
    )
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from pydantic import BaseModel, EmailStr, Field
except ImportError:
    raise ImportError(
        "FastAPI and Pydantic are required to run backend/api.py. "
        "Run: pip install fastapi uvicorn pydantic"
    )

# -----------------------------------------------------------------------------
# تكامل الوحدات البرمجية مع auth.py و database.py مع وجود بدائل تشغيلية ذاتية
# -----------------------------------------------------------------------------
try:
    from backend import auth as app_auth
    from backend import database as app_db
except ImportError:
    try:
        import auth as app_auth
        import database as app_db
    except ImportError:
        app_auth = None
        app_db = None

security = HTTPBearer(auto_error=False)

# -----------------------------------------------------------------------------
# نماذج Pydantic للتحقق من المدخلات والبيانات (Data Schemas)
# -----------------------------------------------------------------------------

# --- نماذج المصادقة (Auth Schemas) ---
class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="اسم المستخدم الفريد")
    email: EmailStr = Field(..., description="البريد الإلكتروني الرسمي")
    password: str = Field(..., min_length=6, max_length=128, description="كلمة المرور")
    full_name: Optional[str] = Field(None, max_length=100, description="الاسم الكامل")
    avatar_url: Optional[str] = Field(None, description="رابط الصورة الشخصية")
    bio: Optional[str] = Field(None, max_length=250, description="نبذة تعريفية")

class UserLoginRequest(BaseModel):
    username_or_email: str = Field(..., description="اسم المستخدم أو البريد الإلكتروني")
    password: str = Field(..., description="كلمة المرور")
    device_name: Optional[str] = Field("Web Client", description="اسم الجهاز أو المتصفح")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: str
    user: Dict[str, Any]

# --- نماذج الرسائل (Messaging Schemas) ---
class DirectMessageSendRequest(BaseModel):
    recipient_id: str = Field(..., description="معرف المستلم")
    content: str = Field(..., min_length=1, max_length=5000, description="نص الرسالة")
    message_type: str = Field("text", description="نوع الرسالة: text, image, file, voice")
    media_url: Optional[str] = Field(None, description="رابط الوسائط المرفقة إن وجد")

class GroupMessageSendRequest(BaseModel):
    group_id: str = Field(..., description="معرف المجموعة")
    content: str = Field(..., min_length=1, max_length=5000, description="نص الرسالة")
    message_type: str = Field("text", description="نوع الرسالة: text, image, file, voice")
    media_url: Optional[str] = Field(None, description="رابط الوسائط المرفقة إن وجد")

class MessageReadRequest(BaseModel):
    message_ids: List[str] = Field(..., description="قائمة معرفات الرسائل المقروءة")

# --- نماذج جهات الاتصال (Contacts Schemas) ---
class AddContactRequest(BaseModel):
    identifier: str = Field(..., description="اسم المستخدم أو البريد الإلكتروني المطلوب إضافته")
    nickname: Optional[str] = Field(None, max_length=50, description="اسم مستعار مخصص")

# --- نماذج المجموعات (Groups Schemas) ---
class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80, description="اسم المجموعة")
    description: Optional[str] = Field(None, max_length=300, description="وصف المجموعة")
    avatar_url: Optional[str] = Field(None, description="أيقونة المجموعة")
    member_ids: List[str] = Field(default_factory=list, description="معرفات الأعضاء الأوليين")

class UpdateGroupRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=300)
    avatar_url: Optional[str] = None

class AddGroupMemberRequest(BaseModel):
    user_id: str = Field(..., description="معرف المستخدم المطلوب إضافته للمجموعة")
    role: str = Field("member", description="الرتبة: member أو admin")

# --- نماذج لوحة تحكم المالك (Owner / Admin Schemas) ---
class AdminUserStatusRequest(BaseModel):
    is_active: bool = Field(..., description="تفعيل (True) أو حظر الحساب (False)")
    ban_reason: Optional[str] = Field(None, description="سبب الحظر")

class AdminUserRoleRequest(BaseModel):
    role: str = Field(..., description="الرتبة الجديدة: user, moderator, admin, owner")

class BroadcastMessageRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=100, description="عنوان الإشعار العام")
    content: str = Field(..., min_length=2, max_length=2000, description="نص الإشعار")

class AdminSystemSettingsRequest(BaseModel):
    maintenance_mode: Optional[bool] = None
    allow_registrations: Optional[bool] = None
    max_upload_size_mb: Optional[int] = None
    system_announcement: Optional[str] = None


# -----------------------------------------------------------------------------
# تهيئة قاعدة البيانات والتوافق الذاتي (Database Connector & Auto Schema)
# -----------------------------------------------------------------------------
DB_FILE = "mohannad_app.db"

def get_db_connection():
    """الحصول على اتصال نشط بقاعدة البيانات مع إمكانية الوصول كقواميس."""
    if app_db and hasattr(app_db, "get_connection"):
        return app_db.get_connection()
    if app_db and hasattr(app_db, "get_db"):
        return app_db.get_db()

    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_api_tables():
    """التحقق من إنشاء الجداول اللازمة للـ REST API في حال عدم إنشائها مسبقاً."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        avatar_url TEXT,
        bio TEXT,
        role TEXT NOT NULL DEFAULT 'user',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        token TEXT UNIQUE NOT NULL,
        device_name TEXT,
        ip_address TEXT,
        user_agent TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_active_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        sender_id TEXT NOT NULL,
        recipient_id TEXT,
        group_id TEXT,
        content TEXT NOT NULL,
        message_type TEXT NOT NULL DEFAULT 'text',
        media_url TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        read_at TEXT,
        created_at TEXT NOT NULL,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        deleted_for TEXT DEFAULT 'none',
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS contacts (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        contact_id TEXT NOT NULL,
        nickname TEXT,
        is_blocked INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, contact_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (contact_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS chat_groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        avatar_url TEXT,
        creator_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS group_members (
        id TEXT PRIMARY KEY,
        group_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        joined_at TEXT NOT NULL,
        UNIQUE(group_id, user_id),
        FOREIGN KEY (group_id) REFERENCES chat_groups(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        action TEXT NOT NULL,
        details TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    default_settings = [
        ("maintenance_mode", "false"),
        ("allow_registrations", "true"),
        ("max_upload_size_mb", "50"),
        ("system_announcement", "")
    ]
    for key, val in default_settings:
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()

try:
    init_api_tables()
except Exception:
    pass


# -----------------------------------------------------------------------------
# دوال التشفير والمصادقة (Security & Hashing Helpers)
# -----------------------------------------------------------------------------
def hash_password(password: str) -> str:
    if app_auth and hasattr(app_auth, "get_password_hash"):
        return app_auth.get_password_hash(password)
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${hashed}"

def verify_password(password: str, hashed_password: str) -> bool:
    if app_auth and hasattr(app_auth, "verify_password"):
        return app_auth.verify_password(password, hashed_password)
    try:
        salt, expected_hash = hashed_password.split("$", 1)
        test_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected_hash, test_hash)
    except Exception:
        return False

def generate_auth_token(user_id: str, role: str) -> str:
    if app_auth and hasattr(app_auth, "create_access_token"):
        return app_auth.create_access_token(data={"sub": user_id, "role": role})
    return f"{user_id}:{role}:{secrets.token_urlsafe(32)}"


# -----------------------------------------------------------------------------
# توابع التحقق من الهوية والصلاحيات (Auth Dependencies)
# -----------------------------------------------------------------------------
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """التحقق من صحة جلسة ورمز المصادقة للمستخدم الحالي."""
    token = None
    if credentials:
        token = credentials.credentials
    elif authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="رمز المصادقة مفقود (Missing Authorization Token)"
        )

    if app_auth and hasattr(app_auth, "get_current_user_from_token"):
        try:
            return app_auth.get_current_user_from_token(token)
        except Exception:
            pass

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id AS session_id, s.expires_at, s.is_active AS session_active,
               u.id, u.username, u.email, u.full_name, u.avatar_url, u.bio,
               u.role, u.is_active
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.is_active = 1
    """, (token,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="جلسة العمل منتهية أو الرمز غير صالح (Session expired or invalid)"
        )

    user_dict = dict(row)
    now_iso = datetime.now(timezone.utc).isoformat()

    if user_dict["expires_at"] < now_iso:
        cursor.execute("UPDATE sessions SET is_active = 0 WHERE id = ?", (user_dict["session_id"],))
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="انتهت صلاحية الجلسة، يرجى تسجيل الدخول مجدداً"
        )

    if not user_dict["is_active"]:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="تم تعطيل أو حظر هذا الحساب من قبل الإدارة"
        )

    cursor.execute("UPDATE sessions SET last_active_at = ? WHERE id = ?", (now_iso, user_dict["session_id"]))
    conn.commit()
    conn.close()

    return user_dict

def get_current_owner(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """التحقق من أن المستخدم يمتلك صلاحية مالك التطبيق (Owner)."""
    if user.get("role") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غير مصرح: هذا الإجراء مخصص لمالك التطبيق فقط (Owner Access Required)"
        )
    return user

def get_current_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """التحقق من أن المستخدم يمتلك صلاحية مشرف أو مالك (Admin/Owner)."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غير مصرح: هذا الإجراء مخصص للمسؤولين فقط (Admin Access Required)"
        )
    return user

def log_audit_event(user_id: Optional[str], action: str, details: str, ip: str = "127.0.0.1"):
    """تدوين العمليات الحساسة في سجل الرقابة والأمان."""
    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO audit_logs (id, user_id, action, details, ip_address, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, action, details, ip, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# موجه المسارات البرمجية (Router Definition)
# -----------------------------------------------------------------------------
router = APIRouter(prefix="/api", tags=["mohannad-app API"])


# =============================================================================
# 1. تسجيل مستخدم جديد وتسجيل الدخول (AUTH)
# =============================================================================

@router.post("/auth/register", status_code=status.HTTP_201_CREATED, summary="تسجيل مستخدم جديد")
def register_user(req: UserRegisterRequest, request: Request):
    """
    تسجيل حساب مستخدم جديد.
    - إذا كان الحساب هو الأول في النظام، يتم منحه رتبة 'owner' تلقائياً.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT value FROM system_settings WHERE key = 'allow_registrations'")
    allow_reg = cursor.fetchone()
    if allow_reg and allow_reg["value"].lower() == "false":
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="التسجيل متوقف مؤقتاً بأمر إدارة التطبيق")

    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (req.username.strip(), req.email.strip().lower()))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="اسم المستخدم أو البريد الإلكتروني مسجل مسبقاً"
        )

    cursor.execute("SELECT COUNT(*) AS cnt FROM users")
    user_count = cursor.fetchone()["cnt"]
    role = "owner" if user_count == 0 else "user"

    user_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    pw_hash = hash_password(req.password)

    cursor.execute("""
        INSERT INTO users (id, username, email, password_hash, full_name, avatar_url, bio, role, is_active, created_at, last_login_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (
        user_id,
        req.username.strip(),
        req.email.strip().lower(),
        pw_hash,
        req.full_name.strip() if req.full_name else req.username.strip(),
        req.avatar_url,
        req.bio,
        role,
        now_iso,
        now_iso
    ))

    # إنشاء جلسة عمل تلقائية
    session_id = str(uuid.uuid4())
    token = generate_auth_token(user_id, role)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "Unknown Client")

    cursor.execute("""
        INSERT INTO sessions (id, user_id, token, device_name, ip_address, user_agent, is_active, created_at, expires_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
    """, (session_id, user_id, token, "Initial Registration", ip_address, user_agent, now_iso, expires_at, now_iso))

    conn.commit()
    conn.close()

    log_audit_event(user_id, "USER_REGISTER", f"User {req.username} registered with role {role}", ip_address)

    return {
        "status": "success",
        "message": "تم إنشاء الحساب بنجاح",
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 30 * 86400,
        "session_id": session_id,
        "user": {
            "id": user_id,
            "username": req.username.strip(),
            "email": req.email.strip().lower(),
            "full_name": req.full_name or req.username.strip(),
            "avatar_url": req.avatar_url,
            "role": role,
            "bio": req.bio
        }
    }

@router.post("/auth/login", response_model=TokenResponse, summary="تسجيل الدخول")
def login_user(req: UserLoginRequest, request: Request):
    """التحقق من البيانات وإصدار جلسة ورمز دخول."""
    conn = get_db_connection()
    cursor = conn.cursor()

    ident = req.username_or_email.strip()
    cursor.execute("""
        SELECT id, username, email, password_hash, full_name, avatar_url, bio, role, is_active
        FROM users
        WHERE username = ? OR email = ?
    """, (ident, ident.lower()))
    user = cursor.fetchone()

    if not user or not verify_password(req.password, user["password_hash"]):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة"
        )

    if not user["is_active"]:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب موقوف أو محظور من قبل إدارة التطبيق"
        )

    user_id = user["id"]
    role = user["role"]
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    session_id = str(uuid.uuid4())
    token = generate_auth_token(user_id, role)
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "Unknown")

    cursor.execute("""
        INSERT INTO sessions (id, user_id, token, device_name, ip_address, user_agent, is_active, created_at, expires_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
    """, (session_id, user_id, token, req.device_name, ip_address, user_agent, now_iso, expires_at, now_iso))

    cursor.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
    conn.commit()
    conn.close()

    log_audit_event(user_id, "USER_LOGIN", f"Login successful from device {req.device_name}", ip_address)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 30 * 86400,
        "session_id": session_id,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user["full_name"],
            "avatar_url": user["avatar_url"],
            "bio": user["bio"],
            "role": user["role"]
        }
    }

@router.get("/auth/me", summary="الملف الشخصي للمستخدم الحالي")
def get_current_user_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    """جلب بيانات الحساب الحالي."""
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "full_name": current_user["full_name"],
        "avatar_url": current_user["avatar_url"],
        "bio": current_user["bio"],
        "role": current_user["role"],
        "session_id": current_user["session_id"]
    }

@router.post("/auth/logout", summary="تسجيل الخروج وإبطال الجلسة الحالية")
def logout_user(current_user: Dict[str, Any] = Depends(get_current_user)):
    """إنهاء الجلسة الحالية بشكل فوري."""
    conn = get_db_connection()
    conn.execute("UPDATE sessions SET is_active = 0 WHERE id = ?", (current_user["session_id"],))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "تم تسجيل الخروج وإبطال الجلسة بنجاح"}


# =============================================================================
# 2. إرسال واستقبال الرسائل (MESSAGES)
# =============================================================================

@router.post("/messages/direct", status_code=status.HTTP_201_CREATED, summary="إرسال رسالة مباشرة")
def send_direct_message(req: DirectMessageSendRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """إرسال رسالة نصية أو مرفق وسائط لشخص محدد."""
    sender_id = current_user["id"]
    recipient_id = req.recipient_id.strip()

    if sender_id == recipient_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="لا يمكنك مراسلة نفسك")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, is_active FROM users WHERE id = ?", (recipient_id,))
    recipient = cursor.fetchone()
    if not recipient:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستلم غير موجود")

    # التحقق من حالة الحظر
    cursor.execute("""
        SELECT is_blocked FROM contacts
        WHERE (user_id = ? AND contact_id = ?) OR (user_id = ? AND contact_id = ?)
    """, (recipient_id, sender_id, sender_id, recipient_id))
    for b in cursor.fetchall():
        if b["is_blocked"] == 1:
            conn.close()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="تعذر الإرسال لوجود حظر بين الطرفين")

    msg_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO messages (id, sender_id, recipient_id, group_id, content, message_type, media_url, is_read, created_at)
        VALUES (?, ?, ?, NULL, ?, ?, ?, 0, ?)
    """, (msg_id, sender_id, recipient_id, req.content.strip(), req.message_type, req.media_url, now_iso))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message_id": msg_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "content": req.content.strip(),
        "message_type": req.message_type,
        "media_url": req.media_url,
        "created_at": now_iso,
        "is_read": False
    }

@router.post("/messages/group", status_code=status.HTTP_201_CREATED, summary="إرسال رسالة داخل مجموعة")
def send_group_message(req: GroupMessageSendRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """إرسال رسالة داخل مجموعة مع التحقق من عضوية المرسل."""
    sender_id = current_user["id"]
    group_id = req.group_id.strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, sender_id))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="أنت لست عضواً في هذه المجموعة")

    msg_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO messages (id, sender_id, recipient_id, group_id, content, message_type, media_url, is_read, created_at)
        VALUES (?, ?, NULL, ?, ?, ?, ?, 0, ?)
    """, (msg_id, sender_id, group_id, req.content.strip(), req.message_type, req.media_url, now_iso))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message_id": msg_id,
        "group_id": group_id,
        "sender_id": sender_id,
        "content": req.content.strip(),
        "message_type": req.message_type,
        "media_url": req.media_url,
        "created_at": now_iso
    }

@router.get("/messages/direct/{contact_id}", summary="استرجاع محادثة خاصة")
def get_direct_messages(
    contact_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """جلب سجل المحادثة المباشرة مع وضع الرسائل كمقروءة تلقائياً."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.sender_id, m.recipient_id, m.content, m.message_type, m.media_url,
               m.is_read, m.read_at, m.created_at,
               u.username AS sender_username, u.full_name AS sender_name, u.avatar_url AS sender_avatar
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE ((m.sender_id = ? AND m.recipient_id = ?) OR (m.sender_id = ? AND m.recipient_id = ?))
          AND m.is_deleted = 0
        ORDER BY m.created_at DESC
        LIMIT ? OFFSET ?
    """, (user_id, contact_id, contact_id, user_id, limit, offset))

    rows = cursor.fetchall()

    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        UPDATE messages
        SET is_read = 1, read_at = ?
        WHERE sender_id = ? AND recipient_id = ? AND is_read = 0
    """, (now_iso, contact_id, user_id))

    conn.commit()
    conn.close()

    messages = [dict(r) for r in reversed(rows)]
    return {"contact_id": contact_id, "count": len(messages), "messages": messages}

@router.get("/messages/group/{group_id}", summary="استرجاع رسائل المجموعة")
def get_group_messages(
    group_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """جلب رسائل المجموعة للأعضاء فقط."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="أنت لست عضواً في هذه المجموعة")

    cursor.execute("""
        SELECT m.id, m.sender_id, m.group_id, m.content, m.message_type, m.media_url,
               m.created_at,
               u.username AS sender_username, u.full_name AS sender_name, u.avatar_url AS sender_avatar
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.group_id = ? AND m.is_deleted = 0
        ORDER BY m.created_at DESC
        LIMIT ? OFFSET ?
    """, (group_id, limit, offset))

    rows = cursor.fetchall()
    conn.close()

    messages = [dict(r) for r in reversed(rows)]
    return {"group_id": group_id, "count": len(messages), "messages": messages}

@router.get("/messages/conversations", summary="قائمة كافة المحادثات")
def get_user_conversations(current_user: Dict[str, Any] = Depends(get_current_user)):
    """استرجاع قائمة المحادثات المباشرة والمجموعات مع آخر رسالة والرسائل غير المقروءة."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            CASE WHEN m.sender_id = ? THEN m.recipient_id ELSE m.sender_id END AS peer_id,
            u.username, u.full_name, u.avatar_url,
            m.id AS last_message_id, m.content AS last_message_content,
            m.message_type AS last_message_type, m.created_at AS last_message_time,
            m.sender_id AS last_message_sender,
            (SELECT COUNT(*) FROM messages unread 
             WHERE unread.sender_id = peer_id AND unread.recipient_id = ? AND unread.is_read = 0) AS unread_count
        FROM messages m
        JOIN users u ON u.id = (CASE WHEN m.sender_id = ? THEN m.recipient_id ELSE m.sender_id END)
        WHERE (m.sender_id = ? OR m.recipient_id = ?) AND m.group_id IS NULL AND m.is_deleted = 0
        GROUP BY peer_id
        ORDER BY last_message_time DESC
    """, (user_id, user_id, user_id, user_id, user_id))
    direct_convs = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT g.id AS group_id, g.name AS group_name, g.avatar_url AS group_avatar,
               m.id AS last_message_id, m.content AS last_message_content,
               m.message_type AS last_message_type, m.created_at AS last_message_time,
               u.username AS last_sender_username
        FROM chat_groups g
        JOIN group_members gm ON gm.group_id = g.id
        LEFT JOIN messages m ON m.id = (
            SELECT id FROM messages WHERE group_id = g.id AND is_deleted = 0 ORDER BY created_at DESC LIMIT 1
        )
        LEFT JOIN users u ON m.sender_id = u.id
        WHERE gm.user_id = ?
        ORDER BY last_message_time DESC
    """, (user_id,))
    group_convs = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "direct_conversations": direct_convs,
        "group_conversations": group_convs
    }

@router.put("/messages/read", summary="تأكيد قراءة الرسائل")
def mark_messages_as_read(req: MessageReadRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """تعليم رسائل محددة بأنها قُرئت."""
    user_id = current_user["id"]
    if not req.message_ids:
        return {"updated_count": 0}

    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(req.message_ids))
    now_iso = datetime.now(timezone.utc).isoformat()

    cursor.execute(f"""
        UPDATE messages
        SET is_read = 1, read_at = ?
        WHERE recipient_id = ? AND id IN ({placeholders}) AND is_read = 0
    """, [now_iso, user_id] + req.message_ids)

    updated = cursor.rowcount
    conn.commit()
    conn.close()

    return {"status": "success", "updated_count": updated}

@router.delete("/messages/{message_id}", summary="حذف رسالة")
def delete_message(
    message_id: str,
    for_everyone: bool = Query(False, description="الحذف لدى الجميع في حال كنت أنت المرسل"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """حذف رسالة للطرفين أو للمستخدم نفسه."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT sender_id, recipient_id, group_id FROM messages WHERE id = ?", (message_id,))
    msg = cursor.fetchone()
    if not msg:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الرسالة غير موجودة")

    is_sender = (msg["sender_id"] == user_id)
    is_admin = (current_user.get("role") in ["owner", "admin"])

    if for_everyone:
        if not is_sender and not is_admin:
            conn.close()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا يمكنك حذف رسالة مرسلة من طرف آخر للجميع")
        cursor.execute("UPDATE messages SET is_deleted = 1, content = 'تم حذف هذه الرسالة' WHERE id = ?", (message_id,))
    else:
        cursor.execute("UPDATE messages SET deleted_for = ? WHERE id = ?", (user_id, message_id))

    conn.commit()
    conn.close()
    return {"status": "success", "message": "تم حذف الرسالة بنجاح"}


# =============================================================================
# 3. جهات الاتصال (CONTACTS)
# =============================================================================

@router.get("/contacts", summary="عرض جهات الاتصال")
def list_contacts(current_user: Dict[str, Any] = Depends(get_current_user)):
    """استرجاع قائمة الأصدقاء وجهات الاتصال."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.id AS contact_relation_id, c.nickname, c.is_blocked, c.created_at AS added_at,
               u.id AS user_id, u.username, u.email, u.full_name, u.avatar_url, u.bio, u.last_login_at
        FROM contacts c
        JOIN users u ON c.contact_id = u.id
        WHERE c.user_id = ?
        ORDER BY COALESCE(c.nickname, u.full_name, u.username) ASC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    return {"contacts": [dict(r) for r in rows]}

@router.post("/contacts/add", status_code=status.HTTP_201_CREATED, summary="إضافة جهة اتصال")
def add_contact(req: AddContactRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """إضافة مستخدم إلى جهات الاتصال عبر الاسم أو البريد."""
    user_id = current_user["id"]
    ident = req.identifier.strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, username FROM users WHERE (username = ? OR email = ? OR id = ?) AND is_active = 1", (ident, ident.lower(), ident))
    target = cursor.fetchone()

    if not target:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم المطلوب غير موجود")

    target_id = target["id"]
    if target_id == user_id:
        conn.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="لا يمكنك إضافة نفسك كجهة اتصال")

    cursor.execute("SELECT id FROM contacts WHERE user_id = ? AND contact_id = ?", (user_id, target_id))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="جهة الاتصال مضافة مسبقاً")

    relation_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO contacts (id, user_id, contact_id, nickname, is_blocked, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
    """, (relation_id, user_id, target_id, req.nickname, now_iso))

    conn.commit()
    conn.close()

    return {"status": "success", "message": f"تمت إضافة {target['username']} إلى جهات الاتصال بنجاح"}

@router.delete("/contacts/{contact_id}", summary="حذف جهة اتصال")
def remove_contact(contact_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """إزالة شخص من جهات الاتصال."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM contacts WHERE user_id = ? AND (contact_id = ? OR id = ?)", (user_id, contact_id, contact_id))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="جهة الاتصال غير موجودة في قائمتك")

    return {"status": "success", "message": "تم حذف جهة الاتصال بنجاح"}

@router.put("/contacts/{contact_id}/block", summary="حظر أو إلغاء حظر جهة اتصال")
def toggle_block_contact(
    contact_id: str,
    block: bool = Query(True, description="True للحظر و False لإلغاء الحظر"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """حظر أو إلغاء حظر التواصل مع مستخدم معين."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM contacts WHERE user_id = ? AND (contact_id = ? OR id = ?)", (user_id, contact_id, contact_id))
    row = cursor.fetchone()

    now_iso = datetime.now(timezone.utc).isoformat()
    if row:
        cursor.execute("UPDATE contacts SET is_blocked = ? WHERE id = ?", (1 if block else 0, row["id"]))
    else:
        cursor.execute("""
            INSERT INTO contacts (id, user_id, contact_id, nickname, is_blocked, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
        """, (str(uuid.uuid4()), user_id, contact_id, 1 if block else 0, now_iso))

    conn.commit()
    conn.close()

    status_msg = "تم حظر" if block else "تم إلغاء حظر"
    return {"status": "success", "message": f"{status_msg} المستخدم بنجاح"}

@router.get("/contacts/search", summary="البحث عن مستخدمين جدد")
def search_users(
    q: str = Query(..., min_length=1, description="كلمة البحث"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """البحث في دليل المستخدمين لإضافتهم إلى جهات الاتصال."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    term = f"%{q.strip()}%"
    cursor.execute("""
        SELECT id, username, full_name, avatar_url, bio
        FROM users
        WHERE (username LIKE ? OR full_name LIKE ? OR email LIKE ?)
          AND id != ? AND is_active = 1
        LIMIT 20
    """, (term, term, term, user_id))

    rows = cursor.fetchall()
    conn.close()

    return {"results": [dict(r) for r in rows]}


# =============================================================================
# 4. إدارة المجموعات (GROUPS)
# =============================================================================

@router.post("/groups", status_code=status.HTTP_201_CREATED, summary="إنشاء مجموعة جديدة")
def create_group(req: CreateGroupRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """إنشاء مجموعة محادثة وإسناد صفة المشرف لمنشئها."""
    creator_id = current_user["id"]
    group_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO chat_groups (id, name, description, avatar_url, creator_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (group_id, req.name.strip(), req.description, req.avatar_url, creator_id, now_iso))

    cursor.execute("""
        INSERT INTO group_members (id, group_id, user_id, role, joined_at)
        VALUES (?, ?, ?, 'admin', ?)
    """, (str(uuid.uuid4()), group_id, creator_id, now_iso))

    for uid in set(req.member_ids):
        if uid and uid != creator_id:
            cursor.execute("SELECT id FROM users WHERE id = ? AND is_active = 1", (uid,))
            if cursor.fetchone():
                cursor.execute("""
                    INSERT OR IGNORE INTO group_members (id, group_id, user_id, role, joined_at)
                    VALUES (?, ?, ?, 'member', ?)
                """, (str(uuid.uuid4()), group_id, uid, now_iso))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": "تم إنشاء المجموعة بنجاح",
        "group": {
            "id": group_id,
            "name": req.name.strip(),
            "description": req.description,
            "avatar_url": req.avatar_url,
            "creator_id": creator_id,
            "created_at": now_iso
        }
    }

@router.get("/groups", summary="عرض مجموعات المستخدم")
def list_user_groups(current_user: Dict[str, Any] = Depends(get_current_user)):
    """قائمة بالمجموعات التي يشترك فيها المستخدم."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT g.id, g.name, g.description, g.avatar_url, g.creator_id, g.created_at,
               gm.role AS my_role, gm.joined_at,
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) AS members_count
        FROM chat_groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = ?
        ORDER BY g.created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    return {"groups": [dict(r) for r in rows]}

@router.get("/groups/{group_id}", summary="تفاصيل وأعضاء المجموعة")
def get_group_details(group_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """استرجاع معلومات المجموعة وقائمة الأعضاء ورتبهم."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    membership = cursor.fetchone()
    if not membership and current_user.get("role") not in ["owner", "admin"]:
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="لا تملك صلاحية الاطلاع على هذه المجموعة")

    cursor.execute("SELECT * FROM chat_groups WHERE id = ?", (group_id,))
    group = cursor.fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المجموعة غير موجودة")

    cursor.execute("""
        SELECT gm.id AS membership_id, gm.role, gm.joined_at,
               u.id AS user_id, u.username, u.full_name, u.avatar_url
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.group_id = ?
        ORDER BY CASE gm.role WHEN 'admin' THEN 1 ELSE 2 END, u.username ASC
    """, (group_id,))
    members = cursor.fetchall()
    conn.close()

    return {
        "group": dict(group),
        "my_role": membership["role"] if membership else "spectator",
        "members_count": len(members),
        "members": [dict(m) for m in members]
    }

@router.put("/groups/{group_id}", summary="تعديل بيانات المجموعة")
def update_group(group_id: str, req: UpdateGroupRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """تعديل اسم أو وصف المجموعة من قبل مشرفيها."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    m = cursor.fetchone()
    if (not m or m["role"] != "admin") and current_user.get("role") not in ["owner", "admin"]:
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="يجب أن تكون مشرفاً في المجموعة للتعديل")

    updates = []
    params = []
    if req.name:
        updates.append("name = ?")
        params.append(req.name.strip())
    if req.description is not None:
        updates.append("description = ?")
        params.append(req.description)
    if req.avatar_url is not None:
        updates.append("avatar_url = ?")
        params.append(req.avatar_url)

    if not updates:
        conn.close()
        return {"status": "success", "message": "لا توجد تعديلات"}

    params.append(group_id)
    cursor.execute(f"UPDATE chat_groups SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

    return {"status": "success", "message": "تم تحديث بيانات المجموعة بنجاح"}

@router.post("/groups/{group_id}/members", summary="إضافة عضو للمجموعة")
def add_group_member(group_id: str, req: AddGroupMemberRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """إضافة عضو جديد للمجموعة."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    m = cursor.fetchone()
    if (not m or m["role"] != "admin") and current_user.get("role") not in ["owner", "admin"]:
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="صلاحية مشرف مطلوبة لإضافة أعضاء")

    cursor.execute("SELECT id, username FROM users WHERE id = ? AND is_active = 1", (req.user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم المطلوب إضافته غير موجود")

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("""
            INSERT INTO group_members (id, group_id, user_id, role, joined_at)
            VALUES (?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), group_id, req.user_id, req.role, now_iso))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="هذا المستخدم عضو في المجموعة بالفعل")

    conn.close()
    return {"status": "success", "message": f"تمت إضافة {target_user['username']} إلى المجموعة بنجاح"}

@router.delete("/groups/{group_id}/members/{member_user_id}", summary="إزالة عضو من المجموعة")
def remove_group_member(group_id: str, member_user_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """حذف أو طرد عضو من المجموعة بواسطة المشرف."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    m = cursor.fetchone()
    if (not m or m["role"] != "admin") and current_user.get("role") not in ["owner", "admin"]:
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="صلاحية مشرف مطلوبة لحذف الأعضاء")

    cursor.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, member_user_id))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="العضو غير متواجد في هذه المجموعة")

    return {"status": "success", "message": "تمت إزالة العضو من المجموعة بنجاح"}

@router.post("/groups/{group_id}/leave", summary="مغادرة المجموعة")
def leave_group(group_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """مغادرة المستخدم للمجموعة."""
    user_id = current_user["id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    deleted = cursor.rowcount

    cursor.execute("SELECT COUNT(*) AS cnt FROM group_members WHERE group_id = ?", (group_id,))
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("DELETE FROM chat_groups WHERE id = ?", (group_id,))

    conn.commit()
    conn.close()

    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="أنت لست عضواً في هذه المجموعة")

    return {"status": "success", "message": "تمت مغادرة المجموعة بنجاح"}


# =============================================================================
# 5. لوحة تحكم المالك (OWNER & ADMIN DASHBOARD)
# =============================================================================

@router.get("/admin/dashboard/stats", summary="إحصائيات النظام الشاملة")
def get_admin_dashboard_stats(admin_user: Dict[str, Any] = Depends(get_current_admin)):
    """عرض إحصائيات التطبيق والمستخدمين والرسائل والجلسات النشطة."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total_users FROM users")
    total_users = cursor.fetchone()["total_users"]

    cursor.execute("SELECT COUNT(*) AS active_users FROM users WHERE is_active = 1")
    active_users = cursor.fetchone()["active_users"]

    cursor.execute("SELECT COUNT(*) AS banned_users FROM users WHERE is_active = 0")
    banned_users = cursor.fetchone()["banned_users"]

    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(DISTINCT user_id) AS active_today FROM sessions WHERE created_at LIKE ?", (f"{today_prefix}%",))
    active_today = cursor.fetchone()["active_today"]

    cursor.execute("SELECT COUNT(*) AS total_messages FROM messages")
    total_messages = cursor.fetchone()["total_messages"]

    cursor.execute("SELECT COUNT(*) AS messages_today FROM messages WHERE created_at LIKE ?", (f"{today_prefix}%",))
    messages_today = cursor.fetchone()["messages_today"]

    cursor.execute("SELECT COUNT(*) AS total_groups FROM chat_groups")
    total_groups = cursor.fetchone()["total_groups"]

    cursor.execute("SELECT COUNT(*) AS active_sessions FROM sessions WHERE is_active = 1")
    active_sessions = cursor.fetchone()["active_sessions"]

    cursor.execute("SELECT key, value FROM system_settings")
    settings = {r["key"]: r["value"] for r in cursor.fetchall()}

    conn.close()

    return {
        "status": "online",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "users": {
            "total": total_users,
            "active": active_users,
            "banned": banned_users,
            "active_today": active_today
        },
        "messages": {
            "total": total_messages,
            "today": messages_today
        },
        "groups": {
            "total": total_groups
        },
        "sessions": {
            "active_now": active_sessions
        },
        "system_settings": settings
    }

@router.get("/admin/users", summary="إدارة المستخدمين للمالك")
def list_all_users_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="بحث بالاسم أو البريد"),
    role_filter: Optional[str] = Query(None, description="تصفية حسب الرتبة"),
    admin_user: Dict[str, Any] = Depends(get_current_admin)
):
    """استعراض قائمة كافة المسجلين مع إمكانية البحث والفرز."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT id, username, email, full_name, avatar_url, role, is_active, created_at, last_login_at FROM users WHERE 1=1"
    params = []

