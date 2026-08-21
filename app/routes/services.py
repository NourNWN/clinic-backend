from datetime import date
from flask import Blueprint, jsonify, request
from app.models import Category, Concern, Doctor, Service, ExchangeRate

services_bp = Blueprint("services", __name__)


@services_bp.route("/api/categories")
def get_categories():
    categories = Category.query.all()
    return jsonify([
        {"id": c.id, "name_ar": c.name_ar, "name_en": c.name_en}
        for c in categories
    ])


@services_bp.route("/api/concerns")
def get_concerns():
    concerns = Concern.query.all()
    return jsonify([
        {
            "id": c.id,
            "name_ar": c.name_ar,
            "name_en": c.name_en,
            "description_ar": c.description_ar,
            "description_en": c.description_en,
        }
        for c in concerns
    ])


@services_bp.route("/api/doctors")
def get_doctors():
    doctors = Doctor.query.all()
    return jsonify([
        {
            "id": d.id,
            "name_ar": d.name_ar,
            "name_en": d.name_en,
            "specialty_ar": d.specialty_ar,
            "specialty_en": d.specialty_en,
            "bio_ar": d.bio_ar,
            "bio_en": d.bio_en,
            "photo_url": d.photo_url,
        }
        for d in doctors
    ])


@services_bp.route("/api/services")
def get_services():
    category_id = request.args.get("category_id", type=int)
    concern_id = request.args.get("concern_id", type=int)

    query = Service.query
    if category_id:
        query = query.filter(Service.category_id == category_id)
    if concern_id:
        query = query.join(Service.concerns).filter(Concern.id == concern_id)

    services = query.all()

    result = []
    for s in services:
        available_variants = [v for v in s.variants if v.is_available]
        prices = [v.price_usd for v in available_variants]

        result.append({
            "id": s.id,
            "name_ar": s.name_ar,
            "name_en": s.name_en,
            "description_ar": s.description_ar,
            "description_en": s.description_en,
            "duration_estimate": s.duration_estimate,
            "category": {
                "id": s.category.id,
                "name_ar": s.category.name_ar,
                "name_en": s.category.name_en,
            },
            "concerns": [
                {"id": c.id, "name_ar": c.name_ar, "name_en": c.name_en}
                for c in s.concerns
            ],
            "variants_preview": {
                "min_price_usd": str(min(prices)) if prices else None,
                "max_price_usd": str(max(prices)) if prices else None,
                "count": len(available_variants),
            },
        })

    return jsonify(result)


@services_bp.route("/api/services/<int:service_id>")
def get_service_detail(service_id):
    service = Service.query.get(service_id)
    if not service:
        return jsonify({
            "error": {
                "code": "service_not_found",
                "message_ar": "الخدمة غير موجودة",
                "message_en": "Service not found",
            }
        }), 404

    today = date.today()

    variants_data = []
    for v in service.variants:
        if not v.is_available:
            continue

        # Check if this variant has an active offer right now
        active_offer = None
        for item in v.offer_items:
            offer = item.offer
            if offer.is_active and offer.start_date <= today <= offer.end_date:
                active_offer = {
                    "offer_item_id": item.id,
                    "offer_id": offer.id,
                    "title_ar": offer.title_ar,
                    "offer_price_syp": str(item.offer_price_syp),
                    "end_date": offer.end_date.isoformat(),
                }
                break  # one active offer is enough, stop searching

        variants_data.append({
            "id": v.id,
            "brand_name_ar": v.brand_name_ar,
            "brand_name_en": v.brand_name_en,
            "price_usd": str(v.price_usd),
            "is_available": v.is_available,
            "active_offer": active_offer,
        })

    return jsonify({
        "id": service.id,
        "name_ar": service.name_ar,
        "name_en": service.name_en,
        "description_ar": service.description_ar,
        "description_en": service.description_en,
        "duration_estimate": service.duration_estimate,
        "category": {
            "id": service.category.id,
            "name_ar": service.category.name_ar,
            "name_en": service.category.name_en,
        },
        "concerns": [
            {"id": c.id, "name_ar": c.name_ar, "name_en": c.name_en}
            for c in service.concerns
        ],
        "doctors": [
            {"id": d.id, "name_ar": d.name_ar, "name_en": d.name_en, "photo_url": d.photo_url}
            for d in service.doctors
        ],
        "variants": variants_data,
    })


@services_bp.route("/api/exchange-rate")
def get_exchange_rate():
    latest = ExchangeRate.query.order_by(ExchangeRate.updated_at.desc()).first()
    if not latest:
        return jsonify({
            "error": {
                "code": "no_exchange_rate",
                "message_ar": "لم يتم تحديد سعر الصرف بعد",
                "message_en": "Exchange rate has not been set yet",
            }
        }), 503

    return jsonify({
        "rate": str(latest.rate),
        "updated_at": latest.updated_at.isoformat(),
    })