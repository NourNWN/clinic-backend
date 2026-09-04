from datetime import date
from flask import Blueprint, jsonify, request
from app.extensions import db
from app.models import ServiceVariant, Doctor, Appointment, OfferItem, ExchangeRate

appointments_bp = Blueprint("appointments", __name__)

REQUIRED_FIELDS = ["patient_name", "patient_phone", "service_variant_id", "doctor_id", "preferred_day"]

# Mirrors the column widths on Appointment. A longer value (or a non-string)
# only fails once it reaches the driver, as a psycopg2 DataError — an HTML 500
# rather than the JSON envelope this endpoint promises. SQLite ignores both
# limits, so the tests can't see that failure; PostgreSQL enforces them.
MAX_PATIENT_NAME = 150
MAX_PATIENT_PHONE = 20


def _invalid_field_error(field):
    return {
        "error": {
            "code": "validation_error",
            "message_ar": f"قيمة الحقل غير صالحة: {field}",
            "message_en": f"Invalid value for field: {field}",
        }
    }


def _past_date_error():
    return {
        "error": {
            "code": "preferred_day_in_past",
            "message_ar": "لا يمكن حجز موعد في تاريخ مضى",
            "message_en": "The preferred day cannot be in the past",
        }
    }


def _clean_text(value, max_length):
    """Trimmed string if `value` is a non-empty string that fits `max_length`,
    else None."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed or len(trimmed) > max_length:
        return None
    return trimmed


def _parse_date(value):
    """An ISO date string -> `date`, or None if it isn't one."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_id(value):
    """A row id -> int, or None if it isn't usable as one. Bools are rejected
    explicitly because `isinstance(True, int)` is True."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


@appointments_bp.route("/api/appointments", methods=["POST"])
def create_appointment():
    # silent=True so a missing or unparseable body becomes the bilingual
    # "missing fields" error below rather than Flask's own HTML 400. A body
    # that parses but isn't an object (a JSON array, say) is truthy, so it
    # needs the isinstance check too — .get() on a list would be a 500.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}

    # 1. Validate required fields
    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if missing:
        return jsonify({
            "error": {
                "code": "validation_error",
                "message_ar": f"حقول ناقصة: {', '.join(missing)}",
                "message_en": f"Missing fields: {', '.join(missing)}",
            }
        }), 400

    # 2. Check the shape of every value before it reaches a query or the
    #    session. An unparseable date or a non-numeric id would otherwise
    #    reach the driver and surface as an unhandled 500 (an HTML traceback,
    #    not the JSON error envelope every other path returns).
    preferred_day = _parse_date(data["preferred_day"])
    if preferred_day is None:
        return jsonify(_invalid_field_error("preferred_day")), 400

    # The booking form already blocks this with `min={today}`, so the rule
    # existed only in the browser — anything not going through that form could
    # file a booking into the past, where it sorts to the top of the admin
    # list. Today is still allowed: a same-day request is a normal walk-in.
    if preferred_day < date.today():
        return jsonify(_past_date_error()), 400

    patient_name = _clean_text(data["patient_name"], MAX_PATIENT_NAME)
    if patient_name is None:
        return jsonify(_invalid_field_error("patient_name")), 400

    patient_phone = _clean_text(data["patient_phone"], MAX_PATIENT_PHONE)
    if patient_phone is None:
        return jsonify(_invalid_field_error("patient_phone")), 400

    service_variant_id = _parse_id(data["service_variant_id"])
    if service_variant_id is None:
        return jsonify(_invalid_field_error("service_variant_id")), 400

    doctor_id = _parse_id(data["doctor_id"])
    if doctor_id is None:
        return jsonify(_invalid_field_error("doctor_id")), 400

    # 3. Validate the variant is bookable. Both flags matter: soft-deleting a
    #    service only clears Service.is_available and deliberately leaves each
    #    variant's own flag alone, so checking the variant by itself would let
    #    a withdrawn treatment keep taking bookings. Same error either way —
    #    the public site hides both cases identically.
    variant = ServiceVariant.query.get(service_variant_id)
    if not variant or not variant.is_available or not variant.service.is_available:
        return jsonify({
            "error": {
                "code": "invalid_variant",
                "message_ar": "الماركة المختارة غير متوفرة",
                "message_en": "Selected variant is not available",
            }
        }), 400

    doctor = Doctor.query.get(doctor_id)
    if not doctor:
        return jsonify({
            "error": {
                "code": "invalid_doctor",
                "message_ar": "الطبيبة غير موجودة",
                "message_en": "Doctor not found",
            }
        }), 400

    # A doctor taken off the roster is hidden from /api/doctors, but nothing
    # stopped a booking naming her id directly.
    if not doctor.is_available:
        return jsonify({
            "error": {
                "code": "doctor_not_available",
                "message_ar": "الطبيبة غير متاحة حالياً",
                "message_en": "Selected doctor is not currently available",
            }
        }), 400

    # doctor_services is what the public service page builds its practitioner
    # list from, so a booking pairing a doctor with a treatment she isn't
    # linked to can only come from outside that flow.
    if doctor not in variant.service.doctors:
        return jsonify({
            "error": {
                "code": "doctor_not_available_for_service",
                "message_ar": "الطبيبة المختارة لا تقدم هذه الخدمة",
                "message_en": "Selected doctor does not provide this service",
            }
        }), 400

    # 4. Get current exchange rate (needed regardless of offer, for record-keeping)
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

    # 5. Calculate final price — offer price or regular calculated price
    raw_offer_item_id = data.get("offer_item_id")
    offer_item = None

    if raw_offer_item_id:
        offer_item_id = _parse_id(raw_offer_item_id)
        if offer_item_id is None:
            return jsonify(_invalid_field_error("offer_item_id")), 400

        offer_item = OfferItem.query.get(offer_item_id)
        today = date.today()

        valid_offer = (
            offer_item
            # A brand removed from an offer keeps its row so past bookings
            # still resolve, but it must not price a new one.
            and offer_item.is_active
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

    # 6. Create and save the appointment — freezing the price at booking time
    appointment = Appointment(
        patient_name=patient_name,
        patient_phone=patient_phone,
        service_variant_id=variant.id,
        doctor_id=doctor.id,
        preferred_day=preferred_day,
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