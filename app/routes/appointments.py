from datetime import date
from flask import Blueprint, jsonify, request
from app.extensions import db
from app.models import ServiceVariant, Doctor, Appointment, OfferItem, ExchangeRate

appointments_bp = Blueprint("appointments", __name__)


@appointments_bp.route("/api/appointments", methods=["POST"])
def create_appointment():
    data = request.get_json()

    # 1. Validate required fields
    required_fields = ["patient_name", "patient_phone", "service_variant_id", "doctor_id", "preferred_day"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return jsonify({
            "error": {
                "code": "validation_error",
                "message_ar": f"حقول ناقصة: {', '.join(missing)}",
                "message_en": f"Missing fields: {', '.join(missing)}",
            }
        }), 400

    # 2. Validate variant and doctor exist
    variant = ServiceVariant.query.get(data["service_variant_id"])
    if not variant or not variant.is_available:
        return jsonify({
            "error": {
                "code": "invalid_variant",
                "message_ar": "الماركة المختارة غير متوفرة",
                "message_en": "Selected variant is not available",
            }
        }), 400

    doctor = Doctor.query.get(data["doctor_id"])
    if not doctor:
        return jsonify({
            "error": {
                "code": "invalid_doctor",
                "message_ar": "الطبيبة غير موجودة",
                "message_en": "Doctor not found",
            }
        }), 400

    # 3. Get current exchange rate (needed regardless of offer, for record-keeping)
    latest_rate = ExchangeRate.query.order_by(ExchangeRate.updated_at.desc()).first()
    if not latest_rate:
        return jsonify({
            "error": {
                "code": "no_exchange_rate",
                "message_ar": "لم يتم تحديد سعر الصرف بعد",
                "message_en": "Exchange rate has not been set yet",
            }
        }), 503
    exchange_rate_used = latest_rate.rate

    # 4. Calculate final price — offer price or regular calculated price
    offer_item_id = data.get("offer_item_id")
    offer_item = None

    if offer_item_id:
        offer_item = OfferItem.query.get(offer_item_id)
        today = date.today()

        valid_offer = (
            offer_item
            and offer_item.service_variant_id == variant.id
            and offer_item.offer.is_active
            and offer_item.offer.start_date <= today <= offer_item.offer.end_date
        )
        if not valid_offer:
            return jsonify({
                "error": {
                    "code": "invalid_offer",
                    "message_ar": "العرض المحدد غير فعّال أو غير مطابق للماركة",
                    "message_en": "Selected offer is inactive or doesn't match the variant",
                }
            }), 400

        final_price_syp = offer_item.offer_price_syp
    else:
        final_price_syp = variant.price_usd * exchange_rate_used

    # 5. Create and save the appointment — freezing the price at booking time
    appointment = Appointment(
        patient_name=data["patient_name"],
        patient_phone=data["patient_phone"],
        service_variant_id=variant.id,
        doctor_id=doctor.id,
        preferred_day=data["preferred_day"],
        status="pending",
        offer_item_id=offer_item.id if offer_item else None,
        final_price_syp_at_booking=final_price_syp,
        exchange_rate_at_booking=exchange_rate_used,
    )
    db.session.add(appointment)
    db.session.commit()

    return jsonify({
        "id": appointment.id,
        "status": appointment.status,
        "message_ar": "تم استلام طلب الحجز، سيتم التواصل معك للتأكيد",
        "message_en": "Booking request received, we will contact you to confirm",
    }), 201