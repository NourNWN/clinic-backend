from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash

from app.auth import generate_token, require_auth
from app.extensions import db
from app.models import AdminUser, Appointment, Category, Service, ServiceVariant

admin_bp = Blueprint("admin", __name__)

VALID_STATUSES = {"pending", "confirmed", "rescheduled", "cancelled", "completed", "no_show"}
VALID_REMINDER_CALL_STATUSES = {"not_called", "called_confirmed", "called_cancelled", "called_rescheduled"}
PATCHABLE_APPOINTMENT_FIELDS = {"status", "confirmed_datetime", "reminder_call_status", "followup_sent"}

REQUIRED_SERVICE_FIELDS = ["category_id", "name_ar", "name_en"]
EDITABLE_SERVICE_FIELDS = {
    "category_id", "name_ar", "name_en", "description_ar", "description_en",
    "duration_estimate", "is_available",
}
REQUIRED_VARIANT_FIELDS = ["brand_name_ar", "brand_name_en", "price_usd"]

INVALID_CREDENTIALS_ERROR = {
    "error": {
        "code": "invalid_credentials",
        "message_ar": "اسم المستخدم أو كلمة المرور غير صحيحة",
        "message_en": "Invalid username or password",
    }
}

APPOINTMENT_NOT_FOUND_ERROR = {
    "error": {
        "code": "appointment_not_found",
        "message_ar": "الموعد غير موجود",
        "message_en": "Appointment not found",
    }
}

NO_RECOGNIZED_FIELDS_ERROR = {
    "error": {
        "code": "validation_error",
        "message_ar": "لا يوجد أي حقل قابل للتعديل بالطلب",
        "message_en": "No recognized fields were provided",
    }
}

INVALID_STATUS_ERROR = {
    "error": {
        "code": "invalid_status",
        "message_ar": "قيمة الحالة غير صالحة",
        "message_en": "Invalid status value",
    }
}

INVALID_REMINDER_CALL_STATUS_ERROR = {
    "error": {
        "code": "invalid_reminder_call_status",
        "message_ar": "قيمة حالة الاتصال غير صالحة",
        "message_en": "Invalid reminder call status value",
    }
}

SERVICE_NOT_FOUND_ERROR = {
    "error": {
        "code": "service_not_found",
        "message_ar": "الخدمة غير موجودة",
        "message_en": "Service not found",
    }
}

CATEGORY_NOT_FOUND_ERROR = {
    "error": {
        "code": "category_not_found",
        "message_ar": "الفئة غير موجودة",
        "message_en": "Category not found",
    }
}


def _missing_fields_error(missing):
    return {
        "error": {
            "code": "validation_error",
            "message_ar": f"حقول ناقصة: {', '.join(missing)}",
            "message_en": f"Missing fields: {', '.join(missing)}",
        }
    }


def _invalid_field_error(field):
    return {
        "error": {
            "code": "validation_error",
            "message_ar": f"قيمة الحقل غير صالحة: {field}",
            "message_en": f"Invalid value for field: {field}",
        }
    }


def _invalid_variant_error(index, field):
    return {
        "error": {
            "code": "validation_error",
            "message_ar": f"قيمة غير صالحة بالماركة رقم {index + 1}: {field}",
            "message_en": f"Invalid value in variant #{index + 1}: {field}",
        }
    }


def _variant_not_found_error(variant_id):
    return {
        "error": {
            "code": "variant_not_found",
            "message_ar": f"الماركة رقم {variant_id} غير موجودة بهذه الخدمة",
            "message_en": f"Variant {variant_id} not found on this service",
        }
    }


def _serialize_service_variant(v):
    return {
        "id": v.id,
        "service_id": v.service_id,
        "brand_name_ar": v.brand_name_ar,
        "brand_name_en": v.brand_name_en,
        "price_usd": str(v.price_usd),
        "is_available": v.is_available,
        "added_at": v.added_at.isoformat() if v.added_at else None,
        "discontinued_at": v.discontinued_at.isoformat() if v.discontinued_at else None,
    }


def _serialize_service(s):
    return {
        "id": s.id,
        "category_id": s.category_id,
        "category": {
            "id": s.category.id,
            "name_ar": s.category.name_ar,
            "name_en": s.category.name_en,
        },
        "name_ar": s.name_ar,
        "name_en": s.name_en,
        "description_ar": s.description_ar,
        "description_en": s.description_en,
        "duration_estimate": s.duration_estimate,
        "is_available": s.is_available,
        "variants": [_serialize_service_variant(v) for v in s.variants],
    }


def _validate_variant_payload(variant, index, *, required):
    """Validate a single variant dict from the request body.
    Returns an error dict, or None if valid."""
    if not isinstance(variant, dict):
        return _invalid_variant_error(index, "variant")

    if required:
        missing = [f for f in REQUIRED_VARIANT_FIELDS if variant.get(f) in (None, "")]
        if missing:
            return _missing_fields_error([f"variants[{index}].{f}" for f in missing])

    if "brand_name_ar" in variant and not isinstance(variant["brand_name_ar"], str):
        return _invalid_variant_error(index, "brand_name_ar")
    if "brand_name_en" in variant and not isinstance(variant["brand_name_en"], str):
        return _invalid_variant_error(index, "brand_name_en")

    if "price_usd" in variant:
        try:
            price = float(variant["price_usd"])
        except (TypeError, ValueError):
            return _invalid_variant_error(index, "price_usd")
        if price < 0:
            return _invalid_variant_error(index, "price_usd")

    if "is_available" in variant and not isinstance(variant["is_available"], bool):
        return _invalid_variant_error(index, "is_available")

    return None


def _apply_variant_fields(variant_obj, data):
    if "brand_name_ar" in data:
        variant_obj.brand_name_ar = data["brand_name_ar"]
    if "brand_name_en" in data:
        variant_obj.brand_name_en = data["brand_name_en"]
    if "price_usd" in data:
        variant_obj.price_usd = float(data["price_usd"])
    if "is_available" in data:
        variant_obj.is_available = data["is_available"]


def _serialize_appointment(a):
    return {
        "id": a.id,
        "patient_name": a.patient_name,
        "patient_phone": a.patient_phone,
        "service_variant": {
            "id": a.service_variant.id,
            "brand_name_ar": a.service_variant.brand_name_ar,
            "service_name_ar": a.service_variant.service.name_ar,
        },
        "doctor": {
            "id": a.doctor.id,
            "name_ar": a.doctor.name_ar,
        },
        "preferred_day": a.preferred_day.isoformat(),
        "status": a.status,
        "reminder_call_status": a.reminder_call_status,
        "final_price_syp_at_booking": str(a.final_price_syp_at_booking),
        "created_at": a.created_at.isoformat(),
    }


def _serialize_appointment_detail(a):
    """Same as _serialize_appointment, plus the scheduling/follow-up
    timestamps that PATCH callers need to see after an update."""
    data = _serialize_appointment(a)
    data.update({
        "confirmed_datetime": a.confirmed_datetime.isoformat() if a.confirmed_datetime else None,
        "followup_sent": a.followup_sent,
        "followup_sent_at": a.followup_sent_at.isoformat() if a.followup_sent_at else None,
        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
    })
    return data


@admin_bp.route("/api/admin/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify(INVALID_CREDENTIALS_ERROR), 401

    user = AdminUser.query.filter_by(username=username).first()

    # Same generic error whether the username doesn't exist or the password
    # is wrong, so a caller can't use this endpoint to enumerate usernames.
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(INVALID_CREDENTIALS_ERROR), 401

    token = generate_token(user)

    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "role": user.role,
        },
    })


@admin_bp.route("/api/admin/appointments")
@require_auth
def get_appointments():
    query = Appointment.query.options(
        joinedload(Appointment.service_variant).joinedload(ServiceVariant.service),
        joinedload(Appointment.doctor),
    )

    day = request.args.get("day")
    if day:
        query = query.filter(Appointment.preferred_day == day)

    status = request.args.get("status")
    if status:
        query = query.filter(Appointment.status == status)

    reminder_call_status = request.args.get("reminder_call_status")
    if reminder_call_status:
        query = query.filter(Appointment.reminder_call_status == reminder_call_status)

    if request.args.get("needs_followup") == "true":
        seven_days_ago = date.today() - timedelta(days=7)
        query = query.filter(
            Appointment.status == "completed",
            db.func.date(Appointment.completed_at) == seven_days_ago,
            Appointment.followup_sent.is_(False),
        )

    appointments = query.order_by(
        Appointment.preferred_day.asc(), Appointment.created_at.asc()
    ).all()

    return jsonify([_serialize_appointment(a) for a in appointments])


@admin_bp.route("/api/admin/appointments/<int:appointment_id>", methods=["PATCH"])
@require_auth
def update_appointment(appointment_id):
    appointment = Appointment.query.options(
        joinedload(Appointment.service_variant).joinedload(ServiceVariant.service),
        joinedload(Appointment.doctor),
    ).get(appointment_id)
    if not appointment:
        return jsonify(APPOINTMENT_NOT_FOUND_ERROR), 404

    data = request.get_json(silent=True) or {}
    fields_present = PATCHABLE_APPOINTMENT_FIELDS & data.keys()
    if not fields_present:
        return jsonify(NO_RECOGNIZED_FIELDS_ERROR), 400

    if "status" in fields_present and data["status"] not in VALID_STATUSES:
        return jsonify(INVALID_STATUS_ERROR), 400

    if "reminder_call_status" in fields_present and data["reminder_call_status"] not in VALID_REMINDER_CALL_STATUSES:
        return jsonify(INVALID_REMINDER_CALL_STATUS_ERROR), 400

    if "status" in fields_present:
        new_status = data["status"]
        if new_status == "completed" and appointment.completed_at is None:
            appointment.completed_at = datetime.utcnow()
        appointment.status = new_status

    if "confirmed_datetime" in fields_present:
        raw = data["confirmed_datetime"]
        appointment.confirmed_datetime = (
            datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
        )

    if "reminder_call_status" in fields_present:
        appointment.reminder_call_status = data["reminder_call_status"]

    if "followup_sent" in fields_present:
        followup_sent = bool(data["followup_sent"])
        appointment.followup_sent = followup_sent
        appointment.followup_sent_at = datetime.utcnow() if followup_sent else None

    db.session.commit()

    return jsonify(_serialize_appointment_detail(appointment))


@admin_bp.route("/api/admin/services")
@require_auth
def get_services():
    query = Service.query.options(
        joinedload(Service.category),
        joinedload(Service.variants),
    )

    category_id = request.args.get("category_id", type=int)
    if category_id:
        query = query.filter(Service.category_id == category_id)

    is_available = request.args.get("is_available")
    if is_available is not None:
        query = query.filter(Service.is_available == (is_available.lower() == "true"))

    services = query.order_by(Service.id.asc()).all()

    return jsonify([_serialize_service(s) for s in services])


@admin_bp.route("/api/admin/services", methods=["POST"])
@require_auth
def create_service():
    data = request.get_json(silent=True) or {}

    missing = [f for f in REQUIRED_SERVICE_FIELDS if data.get(f) in (None, "")]
    if missing:
        return jsonify(_missing_fields_error(missing)), 400

    if not isinstance(data["category_id"], int):
        return jsonify(_invalid_field_error("category_id")), 400
    if not isinstance(data["name_ar"], str) or not isinstance(data["name_en"], str):
        return jsonify(_invalid_field_error("name_ar / name_en")), 400
    if "duration_estimate" in data and data["duration_estimate"] is not None \
            and not isinstance(data["duration_estimate"], int):
        return jsonify(_invalid_field_error("duration_estimate")), 400
    if "is_available" in data and data["is_available"] is not None \
            and not isinstance(data["is_available"], bool):
        return jsonify(_invalid_field_error("is_available")), 400

    category = Category.query.get(data["category_id"])
    if not category:
        return jsonify(CATEGORY_NOT_FOUND_ERROR), 400

    variants_data = data.get("variants", [])
    if not isinstance(variants_data, list):
        return jsonify(_invalid_field_error("variants")), 400

    for i, v in enumerate(variants_data):
        error = _validate_variant_payload(v, i, required=True)
        if error:
            return jsonify(error), 400

    service = Service(
        category_id=data["category_id"],
        name_ar=data["name_ar"],
        name_en=data["name_en"],
        description_ar=data.get("description_ar"),
        description_en=data.get("description_en"),
        duration_estimate=data.get("duration_estimate"),
        is_available=data.get("is_available", True),
    )
    db.session.add(service)
    db.session.flush()  # assigns service.id, still inside the same transaction

    for v in variants_data:
        db.session.add(ServiceVariant(
            service_id=service.id,
            brand_name_ar=v["brand_name_ar"],
            brand_name_en=v["brand_name_en"],
            price_usd=float(v["price_usd"]),
            is_available=v.get("is_available", True),
        ))

    db.session.commit()

    return jsonify(_serialize_service(service)), 201


@admin_bp.route("/api/admin/services/<int:service_id>", methods=["PUT"])
@require_auth
def update_service(service_id):
    service = Service.query.options(
        joinedload(Service.category),
        joinedload(Service.variants),
    ).get(service_id)
    if not service:
        return jsonify(SERVICE_NOT_FOUND_ERROR), 404

    data = request.get_json(silent=True) or {}
    fields_present = EDITABLE_SERVICE_FIELDS & data.keys()
    variants_data = data.get("variants")

    if not fields_present and variants_data is None:
        return jsonify(NO_RECOGNIZED_FIELDS_ERROR), 400

    if "category_id" in fields_present:
        if not isinstance(data["category_id"], int):
            return jsonify(_invalid_field_error("category_id")), 400
        if not Category.query.get(data["category_id"]):
            return jsonify(CATEGORY_NOT_FOUND_ERROR), 400

    for field in ("name_ar", "name_en"):
        if field in fields_present and not isinstance(data[field], str):
            return jsonify(_invalid_field_error(field)), 400

    if "duration_estimate" in fields_present and data["duration_estimate"] is not None \
            and not isinstance(data["duration_estimate"], int):
        return jsonify(_invalid_field_error("duration_estimate")), 400

    if "is_available" in fields_present and not isinstance(data["is_available"], bool):
        return jsonify(_invalid_field_error("is_available")), 400

    if variants_data is not None:
        if not isinstance(variants_data, list):
            return jsonify(_invalid_field_error("variants")), 400

        existing_variants = {v.id: v for v in service.variants}
        for i, v in enumerate(variants_data):
            if not isinstance(v, dict):
                return jsonify(_invalid_variant_error(i, "variant")), 400
            variant_id = v.get("id")
            if variant_id is not None:
                if variant_id not in existing_variants:
                    return jsonify(_variant_not_found_error(variant_id)), 404
                error = _validate_variant_payload(v, i, required=False)
            else:
                error = _validate_variant_payload(v, i, required=True)
            if error:
                return jsonify(error), 400

    for field in ("name_ar", "name_en", "description_ar", "description_en",
                  "duration_estimate", "is_available", "category_id"):
        if field in fields_present:
            setattr(service, field, data[field])

    if variants_data is not None:
        existing_variants = {v.id: v for v in service.variants}
        for v in variants_data:
            variant_id = v.get("id")
            if variant_id is not None:
                _apply_variant_fields(existing_variants[variant_id], v)
            else:
                db.session.add(ServiceVariant(
                    service_id=service.id,
                    brand_name_ar=v["brand_name_ar"],
                    brand_name_en=v["brand_name_en"],
                    price_usd=float(v["price_usd"]),
                    is_available=v.get("is_available", True),
                ))

    db.session.commit()

    return jsonify(_serialize_service(service))


@admin_bp.route("/api/admin/services/<int:service_id>", methods=["DELETE"])
@require_auth
def delete_service(service_id):
    service = Service.query.get(service_id)
    if not service:
        return jsonify(SERVICE_NOT_FOUND_ERROR), 404

    # Soft-disable only — never physically remove the row, its variants,
    # or anything referencing it (offers, appointments, ...).
    if service.is_available:
        service.is_available = False
        db.session.commit()

    return jsonify(_serialize_service(service))
