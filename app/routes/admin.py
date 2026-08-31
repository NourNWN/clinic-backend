from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash

from app.auth import generate_token, require_auth, require_role
from app.extensions import db
from app.models import (
    AdminUser, Appointment, Category, Concern, Doctor, Offer, OfferItem, Service, ServiceVariant,
)

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

REQUIRED_CATEGORY_FIELDS = ["name_ar", "name_en"]
EDITABLE_CATEGORY_FIELDS = {"name_ar", "name_en"}

REQUIRED_CONCERN_FIELDS = ["name_ar", "name_en"]
EDITABLE_CONCERN_FIELDS = {"name_ar", "name_en", "description_ar", "description_en"}

REQUIRED_DOCTOR_FIELDS = ["name_ar", "name_en"]
EDITABLE_DOCTOR_FIELDS = {
    "name_ar", "name_en", "specialty_ar", "specialty_en",
    "bio_ar", "bio_en", "photo_url", "is_available",
}
DOCTOR_STRING_FIELDS = ("specialty_ar", "specialty_en", "bio_ar", "bio_en", "photo_url")

REQUIRED_OFFER_FIELDS = ["title_ar", "title_en", "start_date", "end_date", "items"]
EDITABLE_OFFER_FIELDS = {"title_ar", "title_en", "start_date", "end_date", "is_active"}
REQUIRED_OFFER_ITEM_FIELDS = ["service_variant_id", "offer_price_syp"]

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

CONCERN_NOT_FOUND_ERROR = {
    "error": {
        "code": "concern_not_found",
        "message_ar": "المشكلة غير موجودة",
        "message_en": "Concern not found",
    }
}

DOCTOR_NOT_FOUND_ERROR = {
    "error": {
        "code": "doctor_not_found",
        "message_ar": "الطبيبة غير موجودة",
        "message_en": "Doctor not found",
    }
}

OFFER_NOT_FOUND_ERROR = {
    "error": {
        "code": "offer_not_found",
        "message_ar": "العرض غير موجود",
        "message_en": "Offer not found",
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


def _duplicate_category_error(field):
    return {
        "error": {
            "code": "duplicate_category",
            "message_ar": f"يوجد فئة أخرى بنفس القيمة بالحقل: {field}",
            "message_en": f"Another category already uses this value for: {field}",
        }
    }


def _duplicate_concern_error(field):
    return {
        "error": {
            "code": "duplicate_concern",
            "message_ar": f"يوجد مشكلة أخرى بنفس القيمة بالحقل: {field}",
            "message_en": f"Another concern already uses this value for: {field}",
        }
    }


def _clean_name(value):
    """Trimmed name if `value` is a non-empty string, else None."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _find_duplicate_field(model, exclude_id=None, **fields):
    """Returns the name of the first field (from `fields`, a column name ->
    cleaned value mapping) that collides case-insensitively with another row
    of `model`, or None. A None value skips that field's check."""
    base_query = model.query
    if exclude_id is not None:
        base_query = base_query.filter(model.id != exclude_id)

    for field_name, value in fields.items():
        if value is None:
            continue
        column = getattr(model, field_name)
        if base_query.filter(db.func.lower(column) == value.lower()).first():
            return field_name
    return None


def _serialize_category(c):
    return {
        "id": c.id,
        "name_ar": c.name_ar,
        "name_en": c.name_en,
    }


def _serialize_concern(c):
    return {
        "id": c.id,
        "name_ar": c.name_ar,
        "name_en": c.name_en,
        "description_ar": c.description_ar,
        "description_en": c.description_en,
    }


def _invalid_service_ids_error(invalid_ids):
    return {
        "error": {
            "code": "invalid_service_ids",
            "message_ar": f"معرفات خدمات غير موجودة: {', '.join(map(str, invalid_ids))}",
            "message_en": f"Unknown service id(s): {', '.join(map(str, invalid_ids))}",
        }
    }


def _validate_service_ids(raw):
    """Validates a `service_ids` payload. Returns (services, error) where
    `error` is a response dict (and `services` is None) on failure, or
    the matching Service rows (and `error` is None) on success."""
    if not isinstance(raw, list) or not all(isinstance(i, int) for i in raw):
        return None, _invalid_field_error("service_ids")

    unique_ids = list(dict.fromkeys(raw))
    services = Service.query.filter(Service.id.in_(unique_ids)).all() if unique_ids else []

    found_ids = {s.id for s in services}
    missing = [i for i in unique_ids if i not in found_ids]
    if missing:
        return None, _invalid_service_ids_error(missing)

    return services, None


def _serialize_doctor(d):
    return {
        "id": d.id,
        "name_ar": d.name_ar,
        "name_en": d.name_en,
        "specialty_ar": d.specialty_ar,
        "specialty_en": d.specialty_en,
        "bio_ar": d.bio_ar,
        "bio_en": d.bio_en,
        "photo_url": d.photo_url,
        "is_available": d.is_available,
        "service_ids": [s.id for s in d.services],
        "services": [
            {"id": s.id, "name_ar": s.name_ar, "name_en": s.name_en} for s in d.services
        ],
    }


def _invalid_offer_item_error(index, field):
    return {
        "error": {
            "code": "validation_error",
            "message_ar": f"قيمة غير صالحة بعنصر العرض رقم {index + 1}: {field}",
            "message_en": f"Invalid value in offer item #{index + 1}: {field}",
        }
    }


def _offer_item_variant_not_found_error(index, variant_id):
    return {
        "error": {
            "code": "service_variant_not_found",
            "message_ar": f"الماركة رقم {variant_id} غير موجودة (عنصر العرض رقم {index + 1})",
            "message_en": f"Service variant {variant_id} not found (offer item #{index + 1})",
        }
    }


def _offer_item_not_found_error(item_id):
    return {
        "error": {
            "code": "offer_item_not_found",
            "message_ar": f"عنصر العرض رقم {item_id} غير موجود بهذا العرض",
            "message_en": f"Offer item {item_id} not found on this offer",
        }
    }


def _duplicate_offer_item_error(variant_id):
    return {
        "error": {
            "code": "duplicate_offer_item",
            "message_ar": f"لا يمكن تكرار الماركة رقم {variant_id} أكثر من مرة بنفس العرض",
            "message_en": f"Service variant {variant_id} cannot appear more than once in the same offer",
        }
    }


def _invalid_date_range_error():
    return {
        "error": {
            "code": "invalid_date_range",
            "message_ar": "يجب أن يكون تاريخ البداية قبل أو يساوي تاريخ النهاية",
            "message_en": "start_date must be on or before end_date",
        }
    }


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _validate_offer_item_payload(item, index, *, required):
    """Validate a single offer-item dict from the request body.
    Returns an error dict, or None if valid."""
    if not isinstance(item, dict):
        return _invalid_offer_item_error(index, "item")

    if required:
        missing = [f for f in REQUIRED_OFFER_ITEM_FIELDS if item.get(f) in (None, "")]
        if missing:
            return _missing_fields_error([f"items[{index}].{f}" for f in missing])

    if "service_variant_id" in item and not isinstance(item["service_variant_id"], int):
        return _invalid_offer_item_error(index, "service_variant_id")

    if "offer_price_syp" in item:
        try:
            price = float(item["offer_price_syp"])
        except (TypeError, ValueError):
            return _invalid_offer_item_error(index, "offer_price_syp")
        if price < 0:
            return _invalid_offer_item_error(index, "offer_price_syp")

    return None


def _serialize_offer_item(item):
    v = item.service_variant
    return {
        "id": item.id,
        "service_variant_id": item.service_variant_id,
        "offer_price_syp": str(item.offer_price_syp),
        "service_variant": {
            "id": v.id,
            "brand_name_ar": v.brand_name_ar,
            "brand_name_en": v.brand_name_en,
            "price_usd": str(v.price_usd),
            "service_id": v.service_id,
            "service_name_ar": v.service.name_ar,
            "service_name_en": v.service.name_en,
        },
    }


def _serialize_offer(o):
    return {
        "id": o.id,
        "title_ar": o.title_ar,
        "title_en": o.title_en,
        "start_date": o.start_date.isoformat(),
        "end_date": o.end_date.isoformat(),
        "is_active": o.is_active,
        "created_by": o.created_by,
        "items": [_serialize_offer_item(i) for i in o.items],
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


@admin_bp.route("/api/admin/categories")
@require_auth
def get_categories():
    categories = Category.query.order_by(Category.id.asc()).all()
    return jsonify([_serialize_category(c) for c in categories])


@admin_bp.route("/api/admin/categories", methods=["POST"])
@require_auth
def create_category():
    data = request.get_json(silent=True) or {}

    missing = [f for f in REQUIRED_CATEGORY_FIELDS if not data.get(f)]
    if missing:
        return jsonify(_missing_fields_error(missing)), 400

    name_ar = _clean_name(data["name_ar"])
    if name_ar is None:
        return jsonify(_invalid_field_error("name_ar")), 400

    name_en = _clean_name(data["name_en"])
    if name_en is None:
        return jsonify(_invalid_field_error("name_en")), 400

    dup_field = _find_duplicate_field(Category, name_ar=name_ar, name_en=name_en)
    if dup_field:
        return jsonify(_duplicate_category_error(dup_field)), 409

    category = Category(name_ar=name_ar, name_en=name_en)
    db.session.add(category)
    db.session.commit()

    return jsonify(_serialize_category(category)), 201


@admin_bp.route("/api/admin/categories/<int:category_id>", methods=["PUT"])
@require_auth
def update_category(category_id):
    category = Category.query.get(category_id)
    if not category:
        return jsonify(CATEGORY_NOT_FOUND_ERROR), 404

    data = request.get_json(silent=True) or {}
    fields_present = EDITABLE_CATEGORY_FIELDS & data.keys()
    if not fields_present:
        return jsonify(NO_RECOGNIZED_FIELDS_ERROR), 400

    new_names = {}
    if "name_ar" in fields_present:
        cleaned = _clean_name(data["name_ar"])
        if cleaned is None:
            return jsonify(_invalid_field_error("name_ar")), 400
        new_names["name_ar"] = cleaned

    if "name_en" in fields_present:
        cleaned = _clean_name(data["name_en"])
        if cleaned is None:
            return jsonify(_invalid_field_error("name_en")), 400
        new_names["name_en"] = cleaned

    dup_field = _find_duplicate_field(
        Category, exclude_id=category.id,
        name_ar=new_names.get("name_ar"), name_en=new_names.get("name_en"),
    )
    if dup_field:
        return jsonify(_duplicate_category_error(dup_field)), 409

    # Only the name fields are touched — id and all relationships
    # (e.g. Service.category_id) are left completely untouched.
    for field, value in new_names.items():
        setattr(category, field, value)

    db.session.commit()

    return jsonify(_serialize_category(category))


@admin_bp.route("/api/admin/concerns")
@require_auth
def get_concerns():
    concerns = Concern.query.order_by(Concern.id.asc()).all()
    return jsonify([_serialize_concern(c) for c in concerns])


@admin_bp.route("/api/admin/concerns", methods=["POST"])
@require_auth
def create_concern():
    data = request.get_json(silent=True) or {}

    missing = [f for f in REQUIRED_CONCERN_FIELDS if not data.get(f)]
    if missing:
        return jsonify(_missing_fields_error(missing)), 400

    name_ar = _clean_name(data["name_ar"])
    if name_ar is None:
        return jsonify(_invalid_field_error("name_ar")), 400

    name_en = _clean_name(data["name_en"])
    if name_en is None:
        return jsonify(_invalid_field_error("name_en")), 400

    for field in ("description_ar", "description_en"):
        if field in data and data[field] is not None and not isinstance(data[field], str):
            return jsonify(_invalid_field_error(field)), 400

    dup_field = _find_duplicate_field(Concern, name_ar=name_ar, name_en=name_en)
    if dup_field:
        return jsonify(_duplicate_concern_error(dup_field)), 409

    concern = Concern(
        name_ar=name_ar,
        name_en=name_en,
        description_ar=data.get("description_ar"),
        description_en=data.get("description_en"),
    )
    db.session.add(concern)
    db.session.commit()

    return jsonify(_serialize_concern(concern)), 201


@admin_bp.route("/api/admin/concerns/<int:concern_id>", methods=["PUT"])
@require_auth
def update_concern(concern_id):
    concern = Concern.query.get(concern_id)
    if not concern:
        return jsonify(CONCERN_NOT_FOUND_ERROR), 404

    data = request.get_json(silent=True) or {}
    fields_present = EDITABLE_CONCERN_FIELDS & data.keys()
    if not fields_present:
        return jsonify(NO_RECOGNIZED_FIELDS_ERROR), 400

    new_names = {}
    if "name_ar" in fields_present:
        cleaned = _clean_name(data["name_ar"])
        if cleaned is None:
            return jsonify(_invalid_field_error("name_ar")), 400
        new_names["name_ar"] = cleaned

    if "name_en" in fields_present:
        cleaned = _clean_name(data["name_en"])
        if cleaned is None:
            return jsonify(_invalid_field_error("name_en")), 400
        new_names["name_en"] = cleaned

    for field in ("description_ar", "description_en"):
        if field in fields_present and data[field] is not None and not isinstance(data[field], str):
            return jsonify(_invalid_field_error(field)), 400

    dup_field = _find_duplicate_field(
        Concern, exclude_id=concern.id,
        name_ar=new_names.get("name_ar"), name_en=new_names.get("name_en"),
    )
    if dup_field:
        return jsonify(_duplicate_concern_error(dup_field)), 409

    # id and all relationships (e.g. the service_concerns associations)
    # are left completely untouched — there is no delete route for concerns.
    for field in ("name_ar", "name_en", "description_ar", "description_en"):
        if field in fields_present:
            setattr(concern, field, new_names.get(field, data[field]))

    db.session.commit()

    return jsonify(_serialize_concern(concern))


@admin_bp.route("/api/admin/doctors")
@require_auth
def get_doctors():
    query = Doctor.query.options(joinedload(Doctor.services))

    is_available = request.args.get("is_available")
    if is_available is not None:
        query = query.filter(Doctor.is_available == (is_available.lower() == "true"))

    doctors = query.order_by(Doctor.id.asc()).all()

    return jsonify([_serialize_doctor(d) for d in doctors])


@admin_bp.route("/api/admin/doctors", methods=["POST"])
@require_auth
def create_doctor():
    data = request.get_json(silent=True) or {}

    missing = [f for f in REQUIRED_DOCTOR_FIELDS if not data.get(f)]
    if missing:
        return jsonify(_missing_fields_error(missing)), 400

    name_ar = _clean_name(data["name_ar"])
    if name_ar is None:
        return jsonify(_invalid_field_error("name_ar")), 400

    name_en = _clean_name(data["name_en"])
    if name_en is None:
        return jsonify(_invalid_field_error("name_en")), 400

    for field in DOCTOR_STRING_FIELDS:
        if field in data and data[field] is not None and not isinstance(data[field], str):
            return jsonify(_invalid_field_error(field)), 400

    if "is_available" in data and data["is_available"] is not None \
            and not isinstance(data["is_available"], bool):
        return jsonify(_invalid_field_error("is_available")), 400

    services = []
    if "service_ids" in data:
        services, error = _validate_service_ids(data["service_ids"])
        if error:
            return jsonify(error), 400

    doctor = Doctor(
        name_ar=name_ar,
        name_en=name_en,
        specialty_ar=data.get("specialty_ar"),
        specialty_en=data.get("specialty_en"),
        bio_ar=data.get("bio_ar"),
        bio_en=data.get("bio_en"),
        photo_url=data.get("photo_url"),
        is_available=data.get("is_available", True),
    )
    doctor.services = services
    db.session.add(doctor)
    db.session.commit()

    return jsonify(_serialize_doctor(doctor)), 201


@admin_bp.route("/api/admin/doctors/<int:doctor_id>", methods=["PUT"])
@require_auth
def update_doctor(doctor_id):
    doctor = Doctor.query.options(joinedload(Doctor.services)).get(doctor_id)
    if not doctor:
        return jsonify(DOCTOR_NOT_FOUND_ERROR), 404

    data = request.get_json(silent=True) or {}
    fields_present = EDITABLE_DOCTOR_FIELDS & data.keys()
    service_ids_present = "service_ids" in data

    if not fields_present and not service_ids_present:
        return jsonify(NO_RECOGNIZED_FIELDS_ERROR), 400

    for field in ("name_ar", "name_en"):
        if field in fields_present and _clean_name(data[field]) is None:
            return jsonify(_invalid_field_error(field)), 400

    for field in DOCTOR_STRING_FIELDS:
        if field in fields_present and data[field] is not None and not isinstance(data[field], str):
            return jsonify(_invalid_field_error(field)), 400

    if "is_available" in fields_present and not isinstance(data["is_available"], bool):
        return jsonify(_invalid_field_error("is_available")), 400

    services = None
    if service_ids_present:
        services, error = _validate_service_ids(data["service_ids"])
        if error:
            return jsonify(error), 400

    for field in fields_present:
        if field in ("name_ar", "name_en"):
            setattr(doctor, field, _clean_name(data[field]))
        else:
            setattr(doctor, field, data[field])

    if services is not None:
        # Replaces the full doctor_services association set in one call —
        # e.g. {"service_ids": [1, 2, 5]} links exactly those services and
        # unlinks any others. Appointment history is untouched either way,
        # since appointments reference service_variant_id/doctor_id directly.
        doctor.services = services

    db.session.commit()

    return jsonify(_serialize_doctor(doctor))


@admin_bp.route("/api/admin/doctors/<int:doctor_id>", methods=["DELETE"])
@require_auth
def delete_doctor(doctor_id):
    doctor = Doctor.query.get(doctor_id)
    if not doctor:
        return jsonify(DOCTOR_NOT_FOUND_ERROR), 404

    # Soft-disable only — a hard delete would violate the NOT NULL
    # Appointment.doctor_id FK for any doctor with appointment history,
    # and would silently drop their doctor_services associations.
    if doctor.is_available:
        doctor.is_available = False
        db.session.commit()

    return jsonify(_serialize_doctor(doctor))


def _offer_query():
    return Offer.query.options(
        joinedload(Offer.items).joinedload(OfferItem.service_variant).joinedload(ServiceVariant.service)
    )


@admin_bp.route("/api/admin/offers")
@require_role("manager")
def get_offers():
    query = _offer_query()

    is_active = request.args.get("is_active")
    if is_active is not None:
        query = query.filter(Offer.is_active == (is_active.lower() == "true"))

    offers = query.order_by(Offer.id.asc()).all()

    return jsonify([_serialize_offer(o) for o in offers])


@admin_bp.route("/api/admin/offers", methods=["POST"])
@require_role("manager")
def create_offer():
    data = request.get_json(silent=True) or {}

    missing = [f for f in REQUIRED_OFFER_FIELDS if data.get(f) in (None, "")]
    if missing:
        return jsonify(_missing_fields_error(missing)), 400

    title_ar = _clean_name(data["title_ar"])
    if title_ar is None:
        return jsonify(_invalid_field_error("title_ar")), 400

    title_en = _clean_name(data["title_en"])
    if title_en is None:
        return jsonify(_invalid_field_error("title_en")), 400

    start_date = _parse_date(data["start_date"])
    if start_date is None:
        return jsonify(_invalid_field_error("start_date")), 400

    end_date = _parse_date(data["end_date"])
    if end_date is None:
        return jsonify(_invalid_field_error("end_date")), 400

    if start_date > end_date:
        return jsonify(_invalid_date_range_error()), 400

    if "is_active" in data and data["is_active"] is not None \
            and not isinstance(data["is_active"], bool):
        return jsonify(_invalid_field_error("is_active")), 400

    items_data = data["items"]
    if not isinstance(items_data, list) or not items_data:
        return jsonify(_invalid_field_error("items")), 400

    seen_variant_ids = set()
    for i, item in enumerate(items_data):
        error = _validate_offer_item_payload(item, i, required=True)
        if error:
            return jsonify(error), 400
        variant_id = item["service_variant_id"]
        if variant_id in seen_variant_ids:
            return jsonify(_duplicate_offer_item_error(variant_id)), 400
        seen_variant_ids.add(variant_id)

    found_variant_ids = {
        v.id for v in ServiceVariant.query.filter(ServiceVariant.id.in_(seen_variant_ids)).all()
    }
    missing_variant_ids = seen_variant_ids - found_variant_ids
    if missing_variant_ids:
        for i, item in enumerate(items_data):
            if item["service_variant_id"] in missing_variant_ids:
                return jsonify(_offer_item_variant_not_found_error(i, item["service_variant_id"])), 400

    offer = Offer(
        title_ar=title_ar,
        title_en=title_en,
        start_date=start_date,
        end_date=end_date,
        is_active=data.get("is_active", True),
        created_by=g.current_user["id"],
    )
    db.session.add(offer)
    db.session.flush()  # assigns offer.id, still inside the same transaction

    for item in items_data:
        db.session.add(OfferItem(
            offer_id=offer.id,
            service_variant_id=item["service_variant_id"],
            offer_price_syp=float(item["offer_price_syp"]),
        ))

    db.session.commit()

    offer = _offer_query().get(offer.id)
    return jsonify(_serialize_offer(offer)), 201


@admin_bp.route("/api/admin/offers/<int:offer_id>", methods=["PUT"])
@require_role("manager")
def update_offer(offer_id):
    offer = _offer_query().get(offer_id)
    if not offer:
        return jsonify(OFFER_NOT_FOUND_ERROR), 404

    data = request.get_json(silent=True) or {}
    fields_present = EDITABLE_OFFER_FIELDS & data.keys()
    items_data = data.get("items")

    if not fields_present and items_data is None:
        return jsonify(NO_RECOGNIZED_FIELDS_ERROR), 400

    new_title_ar = None
    if "title_ar" in fields_present:
        new_title_ar = _clean_name(data["title_ar"])
        if new_title_ar is None:
            return jsonify(_invalid_field_error("title_ar")), 400

    new_title_en = None
    if "title_en" in fields_present:
        new_title_en = _clean_name(data["title_en"])
        if new_title_en is None:
            return jsonify(_invalid_field_error("title_en")), 400

    new_start_date = offer.start_date
    if "start_date" in fields_present:
        new_start_date = _parse_date(data["start_date"])
        if new_start_date is None:
            return jsonify(_invalid_field_error("start_date")), 400

    new_end_date = offer.end_date
    if "end_date" in fields_present:
        new_end_date = _parse_date(data["end_date"])
        if new_end_date is None:
            return jsonify(_invalid_field_error("end_date")), 400

    if ("start_date" in fields_present or "end_date" in fields_present) \
            and new_start_date > new_end_date:
        return jsonify(_invalid_date_range_error()), 400

    if "is_active" in fields_present and not isinstance(data["is_active"], bool):
        return jsonify(_invalid_field_error("is_active")), 400

    existing_items = {i.id: i for i in offer.items}
    seen_variant_ids = set()
    variant_ids_to_check = set()

    if items_data is not None:
        if not isinstance(items_data, list):
            return jsonify(_invalid_field_error("items")), 400

        for i, item in enumerate(items_data):
            if not isinstance(item, dict):
                return jsonify(_invalid_offer_item_error(i, "item")), 400

            item_id = item.get("id")
            if item_id is not None:
                if item_id not in existing_items:
                    return jsonify(_offer_item_not_found_error(item_id)), 404
                error = _validate_offer_item_payload(item, i, required=False)
            else:
                error = _validate_offer_item_payload(item, i, required=True)
            if error:
                return jsonify(error), 400

            variant_id = item.get("service_variant_id")
            if variant_id is not None:
                if variant_id in seen_variant_ids:
                    return jsonify(_duplicate_offer_item_error(variant_id)), 400
                seen_variant_ids.add(variant_id)
                variant_ids_to_check.add(variant_id)

        if variant_ids_to_check:
            found = {
                v.id for v in ServiceVariant.query.filter(ServiceVariant.id.in_(variant_ids_to_check)).all()
            }
            missing_ids = variant_ids_to_check - found
            if missing_ids:
                for i, item in enumerate(items_data):
                    variant_id = item.get("service_variant_id")
                    if variant_id in missing_ids:
                        return jsonify(_offer_item_variant_not_found_error(i, variant_id)), 400

    if new_title_ar is not None:
        offer.title_ar = new_title_ar
    if new_title_en is not None:
        offer.title_en = new_title_en
    if "start_date" in fields_present:
        offer.start_date = new_start_date
    if "end_date" in fields_present:
        offer.end_date = new_end_date
    if "is_active" in fields_present:
        offer.is_active = data["is_active"]

    # Existing items are only ever updated in place (matched by id) or
    # appended to — an item is never removed here, since Appointment.
    # offer_item_id may historically point at one.
    if items_data is not None:
        for item in items_data:
            item_id = item.get("id")
            if item_id is not None:
                existing_item = existing_items[item_id]
                if "service_variant_id" in item:
                    existing_item.service_variant_id = item["service_variant_id"]
                if "offer_price_syp" in item:
                    existing_item.offer_price_syp = float(item["offer_price_syp"])
            else:
                db.session.add(OfferItem(
                    offer_id=offer.id,
                    service_variant_id=item["service_variant_id"],
                    offer_price_syp=float(item["offer_price_syp"]),
                ))

    db.session.commit()

    offer = _offer_query().get(offer.id)
    return jsonify(_serialize_offer(offer))


@admin_bp.route("/api/admin/offers/<int:offer_id>", methods=["DELETE"])
@require_role("manager")
def delete_offer(offer_id):
    offer = Offer.query.get(offer_id)
    if not offer:
        return jsonify(OFFER_NOT_FOUND_ERROR), 404

    # Soft-disable only — matches the existing is_active semantics already
    # used elsewhere (see services.py's active-offer check) and preserves
    # offer_items that historical Appointment rows may reference.
    if offer.is_active:
        offer.is_active = False
        db.session.commit()

    return jsonify(_serialize_offer(_offer_query().get(offer.id)))
