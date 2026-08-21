from app import create_app
from app.extensions import db
from app.models import Category, Concern, Doctor, Service, ServiceVariant, AdminUser, ExchangeRate
from werkzeug.security import generate_password_hash
from datetime import date, timedelta
from app.models import Offer, OfferItem

app = create_app()

with app.app_context():
    # فئة تجريبية واحدة
    cat = Category(name_ar="حقن", name_en="Injections")
    db.session.add(cat)

    # مشكلة تجريبية واحدة
    concern = Concern(
        name_ar="تجاعيد",
        name_en="Wrinkles",
        description_ar="خطوط رفيعة بالوجه تظهر مع التقدم بالعمر",
        description_en="Fine lines that appear with age",
    )
    db.session.add(concern)

    # طبيبة تجريبية واحدة
    doctor = Doctor(
        name_ar="د. سارة أحمد",
        name_en="Dr. Sara Ahmad",
        specialty_ar="طب تجميل",
        specialty_en="Cosmetic Medicine",
    )
    db.session.add(doctor)

    db.session.commit()  # لازم نحفظ هون حتى ناخد الـ id تبعهم قبل الخطوة الجاية

    # خدمة تجريبية مرتبطة بالفئة والمشكلة والطبيبة
    service = Service(
        category_id=cat.id,
        name_ar="بوتوكس",
        name_en="Botox",
        description_ar="حقن لتنعيم التجاعيد",
        description_en="Injections to smooth wrinkles",
        duration_estimate=20,
    )
    service.concerns.append(concern)
    service.doctors.append(doctor)
    db.session.add(service)
    db.session.commit()

    # ماركتين تجريبيتين لنفس الخدمة
    variant1 = ServiceVariant(
        service_id=service.id, brand_name_ar="ألماني", brand_name_en="German",
        price_usd=200.00, is_available=True,
    )
    variant2 = ServiceVariant(
        service_id=service.id, brand_name_ar="كوري", brand_name_en="Korean",
        price_usd=120.00, is_available=True,
    )
    db.session.add_all([variant1, variant2])

    # حساب أدمن تجريبي
    admin = AdminUser(
        username="admin",
        password_hash=generate_password_hash("admin123"),
        full_name="مديرة العيادة",
        role="manager",
    )
    db.session.add(admin)

    # عرض ترويجي تجريبي — فعّال حالياً على الماركة الكورية بس
    offer = Offer(
        title_ar="عرض الصيف",
        title_en="Summer Offer",
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=10),
        is_active=True,
    )
    db.session.add(offer)
    db.session.commit()  # لازم نحفظ حتى ناخد offer.id

    offer.created_by = admin.id  # ربط العرض بمين أنشأه بعد ما تأكد وجود admin.id

    offer_item = OfferItem(
        offer_id=offer.id,
        service_variant_id=variant2.id,  # الماركة الكورية (السعر الأرخص)
        offer_price_syp=1400000.00,
    )
    db.session.add(offer_item)

    exchange_rate = ExchangeRate(rate=14500.00, updated_by=admin.id)
    db.session.add(exchange_rate)

    db.session.commit()
    print("✅ تمت إضافة البيانات التجريبية بنجاح")


