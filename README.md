# Clinic Backend — إعداد أولي (Flask + PostgreSQL)

## خطوات التشغيل لأول مرة

### 1. إنشاء بيئة افتراضية (Virtual Environment)
```bash
python3 -m venv venv
source venv/bin/activate        # على Windows: venv\Scripts\activate
```

### 2. تثبيت المكتبات
```bash
pip install -r requirements.txt
```

### 3. إعداد ملف البيئة
```bash
cp .env.example .env
```
افتحي `.env` وحطي بيانات PostgreSQL الحقيقية يلي أنشأتيها (اسم المستخدم، الباسورد، اسم القاعدة).

### 4. تشغيل السيرفر
```bash
python run.py
```

### 5. اختبار الاتصال بقاعدة البيانات
افتحي بالمتصفح أو بـ curl:
```bash
curl http://localhost:5000/api/health
```

**لو الاتصال ناجح**، رح يرجعلك شي شبيه:
```json
{
  "status": "ok",
  "flask": "running",
  "database": "connected",
  "postgres_version": "PostgreSQL 16.x ..."
}
```

**لو رجع خطأ (database: not connected)**، أكتر الأسباب شيوعاً:
- ملف `.env` لسا فيه بيانات وهمية (`your_password_here`) — تأكدي عدّلتيها
- سيرفر PostgreSQL مش شغّال — تأكدي منه (`brew services list` على Mac، أو Services على Windows)
- اسم المستخدم/الباسورد غلط، أو القاعدة `clinic_db` مش موجودة فعلياً

## الخطوة الجاية
بعد ما يشتغل الاتصال بنجاح، الخطوة التالية: تعريف أول جدول حقيقي (Category أو Service) داخل `app/models.py`، وتوليد أول migration بـ Flask-Migrate.
