# استخدام أحدث إصدار رسمي خفيف من بايثون
FROM python:3.12-slim

# ضبط بيئة العمل
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

# تثبيت متطلبات النظام الضرورية
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# تثبيت مكتبات بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    pydantic \
    websockets \
    python-multipart \
    passlib[bcrypt] \
    pyjwt

# نسخ ملفات المشروع بالكامل
COPY . .

# إنشاء مجلد البيانات لقاعدة بيانات SQLite وضمان الصلاحيات
RUN mkdir -p /app/data && chmod 777 /app/data

# المنفذ الافتراضي للـ REST API و WebSocket والواجهة
EXPOSE 8000

# تشغيل الخادم
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]