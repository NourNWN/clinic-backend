from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash

from app.auth import generate_token, require_auth
from app.extensions import db
from app.models import AdminUser, Appointment, ServiceVariant

admin_bp = Blueprint("admin", __name__)

VALID_STATUSES = {"pending", "confirmed", "rescheduled", "cancelled", "completed", "no_show"}
VALID_REMINDER_CALL_STATUSES = {"not_called", "called_confirmed", "called_cancelled", "called_rescheduled"}
PATCHABLE_APPOINTMENT_FIELDS = {"status", "confirmed_datetime", "reminder_call_status", "followup_sent"}

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
