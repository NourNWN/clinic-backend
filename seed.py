from app import create_app
from app.extensions import db
from app.models import (
    Category, Concern, Doctor, Service, ServiceVariant, AdminUser,
    ExchangeRate, Offer, OfferItem, Appointment,
    service_concerns, doctor_services,
)
from werkzeug.security import generate_password_hash
from datetime import date, timedelta

app = create_app()

with app.app_context():
    # امسحي البيانات القديمة بترتيب يحترم القيود (FK) حتى تقدري تشغلي السكربت أكتر من مرة
    Appointment.query.delete()
    OfferItem.query.delete()
    Offer.query.delete()
    db.session.execute(service_concerns.delete())
    db.session.execute(doctor_services.delete())
    ServiceVariant.query.delete()
    Service.query.delete()
    Concern.query.delete()
    Doctor.query.delete()
    Category.query.delete()
    ExchangeRate.query.delete()
    AdminUser.query.delete()
    db.session.commit()

    # ---------- الفئات ----------
    categories = {
        "injections": Category(name_ar="حقن", name_en="Injections"),
        "skincare": Category(name_ar="العناية بالبشرة", name_en="Skincare"),
        "laser": Category(name_ar="إزالة الشعر بالليزر", name_en="Laser Hair Removal"),
        "facials": Category(name_ar="علاجات الوجه", name_en="Facial Treatments"),
    }
    db.session.add_all(categories.values())

    # ---------- المشاكل (Concerns) ----------
    concerns = {
        "wrinkles": Concern(
            name_ar="تجاعيد", name_en="Wrinkles",
            description_ar="خطوط رفيعة بالوجه تظهر مع التقدم بالعمر",
            description_en="Fine lines that appear with age",
        ),
        "acne": Concern(
            name_ar="حب الشباب", name_en="Acne",
            description_ar="بثور والتهابات بالبشرة",
            description_en="Breakouts and skin inflammation",
        ),
        "pigmentation": Concern(
            name_ar="تصبغات", name_en="Pigmentation",
            description_ar="بقع داكنة غير متساوية بلون البشرة",
            description_en="Dark, uneven patches of skin tone",
        ),
        "unwanted_hair": Concern(
            name_ar="شعر زائد", name_en="Unwanted Hair",
            description_ar="شعر غير مرغوب فيه بمناطق مختلفة من الجسم",
            description_en="Unwanted hair growth on various body areas",
        ),
        "dull_skin": Concern(
            name_ar="بشرة باهتة", name_en="Dull Skin",
            description_ar="بشرة تفتقر للنضارة والحيوية",
            description_en="Skin lacking radiance and vitality",
        ),
        "volume_loss": Concern(
            name_ar="فقدان الحجم", name_en="Volume Loss",
            description_ar="فقدان امتلاء الوجه الطبيعي مع التقدم بالعمر",
            description_en="Loss of natural facial fullness with age",
        ),
    }
    db.session.add_all(concerns.values())

    # ---------- الطبيبات/الأطباء ----------
    doctors = {
        "sara": Doctor(
            name_ar="د. سارة أحمد", name_en="Dr. Sara Ahmad",
            specialty_ar="طب تجميل", specialty_en="Cosmetic Medicine",
            bio_ar="خبرة أكتر من 10 سنوات بحقن التجميل",
            bio_en="Over 10 years of experience in cosmetic injections",
        ),
        "layla": Doctor(
            name_ar="د. ليلى حسن", name_en="Dr. Layla Hassan",
            specialty_ar="أمراض جلدية", specialty_en="Dermatology",
            bio_ar="أخصائية أمراض جلدية وعناية بالبشرة",
            bio_en="Dermatology specialist focused on skincare treatments",
        ),
        "omar": Doctor(
            name_ar="د. عمر خليل", name_en="Dr. Omar Khalil",
            specialty_ar="أخصائي ليزر", specialty_en="Laser Specialist",
            bio_ar="متخصص بأحدث تقنيات الليزر لإزالة الشعر",
            bio_en="Specialist in the latest laser hair removal technology",
        ),
    }
    db.session.add_all(doctors.values())

    db.session.commit()  # لازم نحفظ هون حتى ناخد الـ id تبعهم قبل الخطوة الجاية

    # ---------- الخدمات وماركاتها ----------
    services_data = [
        {
            "key": "botox",
            "category": "injections",
            "name_ar": "بوتوكس", "name_en": "Botox",
            "description_ar": "حقن لتنعيم التجاعيد", "description_en": "Injections to smooth wrinkles",
            "duration_estimate": 20,
            "concerns": ["wrinkles"],
            "doctors": ["sara", "layla"],
            "variants": [
                {"brand_ar": "ألماني", "brand_en": "German", "price": 200.00, "available": True},
                {"brand_ar": "كوري", "brand_en": "Korean", "price": 120.00, "available": True},
                {"brand_ar": "فرنسي", "brand_en": "French", "price": 250.00, "available": False},
            ],
        },
        {
            "key": "fillers",
            "category": "injections",
            "name_ar": "حشوات الوجه", "name_en": "Dermal Fillers",
            "description_ar": "حقن لاستعادة امتلاء الوجه", "description_en": "Injections to restore facial volume",
            "duration_estimate": 30,
            "concerns": ["volume_loss"],
            "doctors": ["sara"],
            "variants": [
                {"brand_ar": "كوري", "brand_en": "Korean", "price": 150.00, "available": True},
                {"brand_ar": "أمريكي", "brand_en": "American", "price": 300.00, "available": True},
            ],
        },
        {
            "key": "peel",
            "category": "skincare",
            "name_ar": "تقشير كيميائي", "name_en": "Chemical Peel",
            "description_ar": "تقشير لتحسين ملمس البشرة وتصبغاتها", "description_en": "Peel to improve skin texture and pigmentation",
            "duration_estimate": 25,
            "concerns": ["acne", "pigmentation"],
            "doctors": ["layla"],
            "variants": [
                {"brand_ar": "أساسي", "brand_en": "Basic", "price": 80.00, "available": True},
                {"brand_ar": "متقدم", "brand_en": "Advanced", "price": 150.00, "available": True},
            ],
        },
        {
            "key": "hydrafacial",
            "category": "skincare",
            "name_ar": "هايدرافيشل", "name_en": "Hydrafacial",
            "description_ar": "تنظيف وترطيب عميق للبشرة", "description_en": "Deep cleansing and hydration for the skin",
            "duration_estimate": 40,
            "concerns": ["dull_skin"],
            "doctors": ["layla"],
            "variants": [
                {"brand_ar": "عادي", "brand_en": "Standard", "price": 100.00, "available": True},
                {"brand_ar": "ديلوكس", "brand_en": "Deluxe", "price": 180.00, "available": True},
            ],
        },
        {
            "key": "laser_full",
            "category": "laser",
            "name_ar": "ليزر كامل الجسم", "name_en": "Full Body Laser",
            "description_ar": "إزالة الشعر بالليزر لكامل الجسم", "description_en": "Full body laser hair removal",
            "duration_estimate": 60,
            "concerns": ["unwanted_hair"],
            "doctors": ["omar"],
            "variants": [
                {"brand_ar": "٦ جلسات", "brand_en": "6 Sessions", "price": 400.00, "available": True},
                {"brand_ar": "٣ جلسات", "brand_en": "3 Sessions", "price": 250.00, "available": True},
            ],
        },
        {
            "key": "laser_face",
            "category": "laser",
            "name_ar": "ليزر الوجه", "name_en": "Facial Laser",
            "description_ar": "إزالة الشعر بالليزر لمنطقة الوجه", "description_en": "Laser hair removal for the face",
            "duration_estimate": 15,
            "concerns": ["unwanted_hair"],
            "doctors": ["omar"],
            "variants": [
                {"brand_ar": "جلسة واحدة", "brand_en": "Single Session", "price": 60.00, "available": True},
            ],
        },
        {
            "key": "cleansing_facial",
            "category": "facials",
            "name_ar": "تنظيف بشرة عميق", "name_en": "Deep Cleansing Facial",
            "description_ar": "تنظيف عميق لمسام البشرة", "description_en": "Deep pore cleansing treatment",
            "duration_estimate": 45,
            "concerns": ["acne", "dull_skin"],
            "doctors": ["layla"],
            "variants": [
                {"brand_ar": "عادي", "brand_en": "Standard", "price": 70.00, "available": True},
            ],
        },
        {
            "key": "antiaging_facial",
            "category": "facials",
            "name_ar": "علاج الوجه المضاد للشيخوخة", "name_en": "Anti-Aging Facial",
            "description_ar": "علاج لتنعيم البشرة ومحاربة علامات التقدم بالعمر", "description_en": "Treatment to smooth skin and fight signs of aging",
            "duration_estimate": 50,
            "concerns": ["wrinkles"],
            "doctors": ["sara", "layla"],
            "variants": [
                {"brand_ar": "عادي", "brand_en": "Standard", "price": 130.00, "available": True},
            ],
        },
    ]

    services = {}
    variants = {}

    for data in services_data:
        service = Service(
            category_id=categories[data["category"]].id,
            name_ar=data["name_ar"], name_en=data["name_en"],
            description_ar=data["description_ar"], description_en=data["description_en"],
            duration_estimate=data["duration_estimate"],
        )
        service.concerns = [concerns[key] for key in data["concerns"]]
        service.doctors = [doctors[key] for key in data["doctors"]]
        db.session.add(service)
        db.session.commit()  # لازم نحفظ حتى ناخد service.id قبل إضافة الماركات

        services[data["key"]] = service
        for i, v in enumerate(data["variants"]):
            variant = ServiceVariant(
                service_id=service.id,
                brand_name_ar=v["brand_ar"], brand_name_en=v["brand_en"],
                price_usd=v["price"], is_available=v["available"],
            )
            db.session.add(variant)
            variants[f"{data['key']}_{i}"] = variant

    db.session.commit()

    # ---------- حسابات الأدمن ----------
    manager = AdminUser(
        username="admin",
        password_hash=generate_password_hash("admin123"),
        full_name="مديرة العيادة",
        role="manager",
    )
    reception = AdminUser(
        username="reception",
        password_hash=generate_password_hash("reception123"),
        full_name="موظفة الاستقبال",
        role="reception",
    )
    db.session.add_all([manager, reception])
    db.session.commit()

    # ---------- سعر الصرف ----------
    exchange_rate = ExchangeRate(rate=14500.00, updated_by=manager.id)
    db.session.add(exchange_rate)
    db.session.commit()

    # ---------- عروض ترويجية ----------
    summer_offer = Offer(
        title_ar="عرض الصيف", title_en="Summer Offer",
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=10),
        is_active=True,
        created_by=manager.id,
    )
    new_client_offer = Offer(
        title_ar="عرض العميل الجديد", title_en="New Client Offer",
        start_date=date.today() - timedelta(days=5),
        end_date=date.today() + timedelta(days=20),
        is_active=True,
        created_by=manager.id,
    )
    db.session.add_all([summer_offer, new_client_offer])
    db.session.commit()  # لازم نحفظ حتى ناخد offer.id

    db.session.add_all([
        OfferItem(offer_id=summer_offer.id, service_variant_id=variants["botox_1"].id, offer_price_syp=1400000.00),
        OfferItem(offer_id=new_client_offer.id, service_variant_id=variants["hydrafacial_0"].id, offer_price_syp=1250000.00),
    ])
    db.session.commit()

    # ---------- مواعيد تجريبية ----------
    rate = exchange_rate.rate
    db.session.add_all([
        Appointment(
            patient_name="رهف العلي", patient_phone="+963944111222",
            service_variant_id=variants["botox_1"].id, doctor_id=doctors["sara"].id,
            preferred_day=date.today() + timedelta(days=2),
            status="pending",
            final_price_syp_at_booking=variants["botox_1"].price_usd * rate,
            exchange_rate_at_booking=rate,
        ),
        Appointment(
            patient_name="محمد الحمصي", patient_phone="+963955333444",
            service_variant_id=variants["laser_full_1"].id, doctor_id=doctors["omar"].id,
            preferred_day=date.today() + timedelta(days=5),
            status="confirmed",
            final_price_syp_at_booking=variants["laser_full_1"].price_usd * rate,
            exchange_rate_at_booking=rate,
        ),
        Appointment(
            patient_name="لينا قاسم", patient_phone="+963966555666",
            service_variant_id=variants["hydrafacial_0"].id, doctor_id=doctors["layla"].id,
            preferred_day=date.today() - timedelta(days=3),
            status="completed",
            completed_at=date.today() - timedelta(days=3),
            final_price_syp_at_booking=variants["hydrafacial_0"].price_usd * rate,
            exchange_rate_at_booking=rate,
        ),
    ])

    db.session.commit()
    print("تمت إضافة البيانات التجريبية بنجاح")
    print(f"- {len(categories)} categories, {len(concerns)} concerns, {len(doctors)} doctors")
    print(f"- {len(services)} services, {len(variants)} variants")
    print("- 2 offers, 3 appointments, admin login: admin / admin123")
