import sqlite3
import os
import uuid
from datetime import datetime, timezone
import auth

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "mohannad.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        phone_number TEXT UNIQUE NOT NULL,
        username TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        profile_image TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        account_status TEXT NOT NULL DEFAULT 'pending', -- pending, active, rejected, suspended, deleted
        role TEXT NOT NULL DEFAULT 'user',               -- user, owner, admin
        must_change_password INTEGER DEFAULT 0,
        privacy_last_seen TEXT DEFAULT 'everyone',       -- everyone, contacts, nobody
        privacy_profile_photo TEXT DEFAULT 'everyone',   -- everyone, contacts, nobody
        privacy_read_receipts INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        last_seen TEXT NOT NULL
    )
    ''')

    # 2. LoginRequests table (for registration approval)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS login_requests (
        request_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        username TEXT NOT NULL,
        name TEXT NOT NULL,
        device_info TEXT DEFAULT 'Mobile Client',
        app_version TEXT DEFAULT '1.0.0',
        status TEXT NOT NULL DEFAULT 'pending', -- pending, approved, rejected
        approved_by TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # 3. Chats table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        chat_id TEXT PRIMARY KEY,
        chat_type TEXT NOT NULL, -- 'direct' or 'group'
        name TEXT,
        image TEXT DEFAULT '',
        description TEXT DEFAULT '',
        owner_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')

    # 4. ChatMembers table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_members (
        chat_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT DEFAULT 'member', -- owner, admin, member
        is_pinned INTEGER DEFAULT 0,
        is_muted INTEGER DEFAULT 0,
        is_archived INTEGER DEFAULT 0,
        joined_at TEXT NOT NULL,
        PRIMARY KEY (chat_id, user_id),
        FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # 5. Messages table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        message_id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        message_type TEXT NOT NULL DEFAULT 'text', -- text, voice, image, video, file, call
        content TEXT DEFAULT '',
        file_url TEXT DEFAULT '',
        file_name TEXT DEFAULT '',
        file_size INTEGER DEFAULT 0,
        duration INTEGER DEFAULT 0,
        reply_to TEXT,
        is_pinned INTEGER DEFAULT 0,
        is_edited INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        delivered_at TEXT,
        read_at TEXT,
        deleted_for_all INTEGER DEFAULT 0,
        FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
        FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # 6. Calls table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS calls (
        call_id TEXT PRIMARY KEY,
        caller_id TEXT NOT NULL,
        receiver_id TEXT NOT NULL,
        chat_id TEXT,
        call_type TEXT NOT NULL, -- audio, video
        status TEXT NOT NULL,    -- missed, completed, declined, ongoing
        duration INTEGER DEFAULT 0,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        FOREIGN KEY (caller_id) REFERENCES users(user_id),
        FOREIGN KEY (receiver_id) REFERENCES users(user_id)
    )
    ''')

    # 7. Statuses (Stories) table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS statuses (
        status_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        content TEXT DEFAULT '',
        media_url TEXT DEFAULT '',
        status_type TEXT DEFAULT 'text', -- text, image, video
        bg_color TEXT DEFAULT '#1f2937',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # 8. StatusViews table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS status_views (
        status_id TEXT NOT NULL,
        viewer_id TEXT NOT NULL,
        viewed_at TEXT NOT NULL,
        PRIMARY KEY (status_id, viewer_id),
        FOREIGN KEY (status_id) REFERENCES statuses(status_id) ON DELETE CASCADE,
        FOREIGN KEY (viewer_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # 9. Reports table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        report_id TEXT PRIMARY KEY,
        reporter_id TEXT NOT NULL,
        reported_user_id TEXT NOT NULL,
        reason TEXT NOT NULL, -- spam, scam, impersonation, offensive, other
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'pending', -- pending, reviewed, dismissed, action_taken
        created_at TEXT NOT NULL,
        FOREIGN KEY (reporter_id) REFERENCES users(user_id),
        FOREIGN KEY (reported_user_id) REFERENCES users(user_id)
    )
    ''')

    # 10. LinkedDevices table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS linked_devices (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        device_name TEXT NOT NULL,
        device_type TEXT NOT NULL,
        ip_address TEXT DEFAULT '',
        user_agent TEXT DEFAULT '',
        last_active TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # 11. BlockedUsers table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS blocked_users (
        user_id TEXT NOT NULL,
        blocked_user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, blocked_user_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (blocked_user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # Create Indices
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_members_user ON chat_members(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_statuses_user ON statuses(user_id)")

    conn.commit()

    # Seed Initial Owner Account (Mohannad / 12345) as per specification
    seed_owner(cursor)
    conn.commit()
    conn.close()

def seed_owner(cursor):
    cursor.execute("SELECT user_id FROM users WHERE username = 'Mohannad'")
    existing = cursor.fetchone()
    if not existing:
        owner_id = str(uuid.uuid4())
        pwd_hash, salt = auth.hash_password("12345")
        now = now_iso()
        cursor.execute('''
        INSERT INTO users (
            user_id, phone_number, username, name, profile_image, bio,
            password_hash, salt, account_status, role, must_change_password,
            created_at, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            owner_id,
            "+966500000000",
            "Mohannad",
            "مهند (المالك)",
            "",
            "مالك ومؤسس تطبيق مهند",
            pwd_hash,
            salt,
            "active",
            "owner",
            1, # Must change password upon first login
            now,
            now
        ))
        print("Initialized Owner account 'Mohannad' successfully.")

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")