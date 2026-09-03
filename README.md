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

## تشغيل الاختبارات (Tests)

```bash
pip install -r requirements-dev.txt
pytest
```

الاختبارات بتشتغل على **PostgreSQL** مثل الإنتاج، مو على SQLite. السبب: SQLite
ما بيطبّق حدود طول الأعمدة (`VARCHAR`) وبيتساهل بتحويل التواريخ، فكان في أخطاء
بتنجح بالاختبارات وبتفشل بالإنتاج.

### قاعدة بيانات الاختبار

بتنشأ قاعدة منفصلة اسمها `<اسم قاعدتك>_test` (مثلاً `clinic_db_test`)، ومنها
بتتولّد الجداول تلقائياً. ما بتحتاجي أي إعداد إضافي — إلا إذا المستخدم عندك ما
بيقدر ينشئ قواعد بيانات، عندها نفّذي مرة وحدة كـ superuser:

```sql
CREATE DATABASE clinic_db_test OWNER clinic_user;
```

أو حدّدي قاعدة جاهزة عن طريق متغير البيئة `TEST_DATABASE_URL`.

> **تنبيه:** الاختبارات بتفرّغ (TRUNCATE) كل الجداول قبل كل اختبار. في حمايتان
> بتمنعا وصولها لقاعدة التطوير: وحدة بتتأكد إنو اسم قاعدة الاختبار غير اسم
> القاعدة بـ `DATABASE_URL`، وتانية بتفحص القاعدة يلي متصل فيها المحرك فعلياً
> قبل أي أمر حذف. إذا صار أي خلل بالإعداد، الاختبارات بتوقف قبل ما تلمس شي.

## الخطوة الجاية
بعد ما يشتغل الاتصال بنجاح، الخطوة التالية: تعريف أول جدول حقيقي (Category أو Service) داخل `app/models.py`، وتوليد أول migration بـ Flask-Migrate.
