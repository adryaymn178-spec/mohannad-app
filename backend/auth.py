import hashlib
import hmac
import os
import secrets
import time
from typing import Optional, Dict, Any

SECRET_KEY = os.environ.get("JWT_SECRET", secrets.token_hex(32))

# In-memory Rate Limiter: {ip_or_user: [timestamp, ...]}
RATE_LIMIT_BUCKET = {}
MAX_REQUESTS_PER_MINUTE = 60

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hashes password using PBKDF2-HMAC-SHA256 with a unique salt."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100_000
    )
    return key.hex(), salt

def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Safely verifies a password against a hash."""
    computed_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(computed_hash, expected_hash)

def generate_session_token(user_id: str, role: str) -> str:
    """Generates a cryptographically secure signed session token."""
    timestamp = str(int(time.time()))
    payload = f"{user_id}:{role}:{timestamp}:{secrets.token_hex(8)}"
    signature = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def verify_session_token(token: str, max_age_seconds: int = 86400 * 30) -> Optional[Dict[str, Any]]:
    """Verifies the signature and expiration of a session token."""
    try:
        parts = token.split(":")
        if len(parts) != 5:
            return None
        user_id, role, timestamp_str, nonce, signature = parts
        payload = f"{user_id}:{role}:{timestamp_str}:{nonce}"
        expected_signature = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        created_time = int(timestamp_str)
        if time.time() - created_time > max_age_seconds:
            return None
        return {"user_id": user_id, "role": role, "created_at": created_time}
    except Exception:
        return None

def check_rate_limit(client_ip: str, limit: int = MAX_REQUESTS_PER_MINUTE) -> bool:
    """Checks rate limiting per client IP."""
    now = time.time()
    if client_ip not in RATE_LIMIT_BUCKET:
        RATE_LIMIT_BUCKET[client_ip] = []
    
    # Filter out entries older than 60s
    RATE_LIMIT_BUCKET[client_ip] = [t for t in RATE_LIMIT_BUCKET[client_ip] if now - t < 60]
    if len(RATE_LIMIT_BUCKET[client_ip]) >= limit:
        return False
    RATE_LIMIT_BUCKET[client_ip].append(now)
    return True