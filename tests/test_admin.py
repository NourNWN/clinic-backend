import time
from datetime import date, timedelta

import jwt
import pytest
from flask import current_app

from app.auth import _authenticate

from app.extensions import db
from app.models import (
    Appointment, Concern, Doctor, Offer, OfferItem, Service, ServiceVariant,
    service_concerns,
)


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_valid_login_returns_token_and_user(self, client, manager_user):
        r = client.post("/api/admin/login", json={"username": "manager1", "password": "manager-pass"})
        assert r.status_code == 200
        body = r.get_json()
        assert "token" in body
        assert body["user"] == {"id": manager_user.id, "full_name": "Manager One", "role": "manager"}

    def test_wrong_password(self, client, manager_user):
        r = client.post("/api/admin/login", json={"username": "manager1", "password": "wrong"})
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "invalid_credentials"

    def test_unknown_username(self, client):
        r = client.post("/api/admin/login", json={"username": "ghost", "password": "x"})
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "invalid_credentials"

    def test_missing_fields(self, client):
        r = client.post("/api/admin/login", json={"username": "manager1"})
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "invalid_credentials"

    def test_empty_body(self, client):
        r = client.post("/api/admin/login", json={})
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "invalid_credentials"

    def test_no_body_returns_json_not_html(self, client):
        """Regression test: previously used request.get_json() without
        silent=True, so a missing/malformed body raised an unhandled
        werkzeug 415/400 HTML error instead of the API's JSON error shape."""
        r = client.post("/api/admin/login")
        assert r.status_code in (400, 401)
        assert r.is_json
        assert r.get_json()["error"]["code"] == "invalid_credentials"

    def test_malformed_json_body_returns_json_not_html(self, client):
        r = client.post("/api/admin/login", data="{not valid json", content_type="application/json")
        assert r.is_json
        assert r.get_json()["error"]["code"] == "invalid_credentials"

    def test_wrong_content_type_returns_json_not_html(self, client):
        r = client.post("/api/admin/login", data="username=x&password=y", content_type="text/plain")
        assert r.is_json
        assert r.get_json()["error"]["code"] == "invalid_credentials"


# ---------------------------------------------------------------------------
# Authentication / authorization guard behavior (shared across endpoints)
# ---------------------------------------------------------------------------

class TestAuthGuard:
    PROTECTED_GET = "/api/admin/services"
    MANAGER_ONLY_GET = "/api/admin/offers"

    def test_missing_header_401(self, client):
        r = client.get(self.PROTECTED_GET)
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "unauthorized"

    def test_missing_bearer_prefix_401(self, client, manager_token):
        r = client.get(self.PROTECTED_GET, headers={"Authorization": manager_token})
        assert r.status_code == 401

    def test_garbage_token_401(self, client):
        r = client.get(self.PROTECTED_GET, headers={"Authorization": "Bearer not-a-real-jwt"})
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "unauthorized"

    def test_truncated_token_401(self, client, manager_token):
        r = client.get(self.PROTECTED_GET, headers={"Authorization": f"Bearer {manager_token[:-5]}"})
        assert r.status_code == 401

    def test_wrong_signature_401(self, client, app, manager_user):
        bad_token = jwt.encode(
            {"sub": str(manager_user.id), "role": "manager"}, "wrong-secret", algorithm="HS256"
        )
        r = client.get(self.PROTECTED_GET, headers={"Authorization": f"Bearer {bad_token}"})
        assert r.status_code == 401

    def test_expired_token_401(self, client, app, manager_user):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        expired = jwt.encode(
            {"sub": str(manager_user.id), "role": "manager", "iat": now - dt.timedelta(hours=9),
             "exp": now - dt.timedelta(hours=1)},
            app.config["SECRET_KEY"], algorithm="HS256",
        )
        r = client.get(self.PROTECTED_GET, headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401

    def test_none_algorithm_attack_rejected(self, client, manager_user):
        import base64, json as _json
        header = base64.urlsafe_b64encode(_json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            _json.dumps({"sub": str(manager_user.id), "role": "manager"}).encode()
        ).rstrip(b"=").decode()
        forged = f"{header}.{payload}."
        r = client.get(self.PROTECTED_GET, headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401

    def test_issued_token_carries_sub_as_a_string(self, client, manager_user, manager_token):
        """Regression: `sub` used to be encoded as the raw integer user id.
        PyJWT enforces RFC 7519's string-`sub` rule on decode from 2.10 on
        (InvalidSubjectError), so the app issued tokens at login that it then
        rejected with 401 on every protected route -- but only when running
        against PyJWT >= 2.10, which is why the pinned dev env never saw it."""
        claims = jwt.decode(
            manager_token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
        assert claims["sub"] == str(manager_user.id)
        assert isinstance(claims["sub"], str)

    def test_authenticated_route_sees_integer_user_id(self, client, manager_user, manager_token):
        """`sub` travels as a string, but g.current_user["id"] must stay an
        int -- it is written straight into integer FKs (created_by/updated_by)."""
        with client.application.test_request_context(
            headers={"Authorization": f"Bearer {manager_token}"}
        ):
            user, error = _authenticate()
        assert error is None
        assert user == {"id": manager_user.id, "role": "manager"}
        assert isinstance(user["id"], int)

    def test_valid_token_reception_allowed_on_require_auth_route(self, client, reception_token):
        r = client.get(self.PROTECTED_GET, headers=auth_headers(reception_token))
        assert r.status_code == 200

    def test_valid_token_manager_allowed_on_manager_route(self, client, manager_token):
        r = client.get(self.MANAGER_ONLY_GET, headers=auth_headers(manager_token))
        assert r.status_code == 200

    def test_reception_forbidden_on_manager_route(self, client, reception_token):
        r = client.get(self.MANAGER_ONLY_GET, headers=auth_headers(reception_token))
        assert r.status_code == 403
        assert r.get_json()["error"]["code"] == "forbidden"

    def test_no_token_on_manager_route_is_401_not_403(self, client):
        r = client.get(self.MANAGER_ONLY_GET)
        assert r.status_code == 401

    def test_exchange_rate_requires_manager(self, client, reception_token):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(reception_token), json={"rate": 15000})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

class TestAppointments:
    def test_list_appointments(self, client, reception_token, appointment):
        r = client.get("/api/admin/appointments", headers=auth_headers(reception_token))
        assert r.status_code == 200
        body = r.get_json()
        assert len(body) == 1
        item = body[0]
        assert item["id"] == appointment.id
        assert item["final_price_syp_at_booking"] == "1000000.00"
        assert item["service_variant"]["brand_name_ar"] == "ألماني"
        assert item["doctor"]["name_ar"] == "د. سارة"

    def test_filter_by_status(self, client, reception_token, appointment):
        r = client.get("/api/admin/appointments?status=confirmed", headers=auth_headers(reception_token))
        assert r.get_json() == []
        r2 = client.get("/api/admin/appointments?status=pending", headers=auth_headers(reception_token))
        assert len(r2.get_json()) == 1

    def test_filter_by_day(self, client, reception_token, appointment):
        r = client.get(
            f"/api/admin/appointments?day={appointment.preferred_day.isoformat()}",
            headers=auth_headers(reception_token),
        )
        assert len(r.get_json()) == 1
        r2 = client.get("/api/admin/appointments?day=2000-01-01", headers=auth_headers(reception_token))
        assert r2.get_json() == []

    def test_filter_needs_followup(self, client, reception_token, app, variant, doctor):
        from datetime import datetime
        completed = Appointment(
            patient_name="Old Patient", patient_phone="+963900000001",
            service_variant_id=variant.id, doctor_id=doctor.id,
            preferred_day=date.today() - timedelta(days=10),
            status="completed",
            completed_at=datetime.utcnow() - timedelta(days=7),
            followup_sent=False,
            final_price_syp_at_booking=1000000, exchange_rate_at_booking=14500,
        )
        db.session.add(completed)
        db.session.commit()

        r = client.get("/api/admin/appointments?needs_followup=true", headers=auth_headers(reception_token))
        body = r.get_json()
        assert len(body) == 1
        assert body[0]["id"] == completed.id

    def test_list_rows_carry_every_field_the_admin_screen_filters_on(
        self, client, reception_token, appointment
    ):
        """The appointments screen re-filters each tab client-side after a
        PATCH, reading `reminder_call_status` and `followup_sent` straight off
        the list rows. A row that omits either can only be filtered by
        accident, so the list serializer has to carry both."""
        r = client.get("/api/admin/appointments", headers=auth_headers(reception_token))
        item = r.get_json()[0]

        assert item["reminder_call_status"] == "not_called"
        assert item["followup_sent"] is False

    def test_list_followup_sent_reflects_a_sent_followup(
        self, client, reception_token, appointment
    ):
        appointment.followup_sent = True
        db.session.commit()

        r = client.get("/api/admin/appointments", headers=auth_headers(reception_token))
        assert r.get_json()[0]["followup_sent"] is True

    def test_needs_followup_rows_are_all_unsent(self, client, reception_token, app, variant, doctor):
        """Every row the follow-up filter returns must report followup_sent
        false explicitly — the screen's `!a.followup_sent` check has to be
        reading a real boolean, not an absent key."""
        from datetime import datetime
        completed = Appointment(
            patient_name="Old Patient", patient_phone="+963900000001",
            service_variant_id=variant.id, doctor_id=doctor.id,
            preferred_day=date.today() - timedelta(days=10),
            status="completed",
            completed_at=datetime.utcnow() - timedelta(days=7),
            followup_sent=False,
            final_price_syp_at_booking=1000000, exchange_rate_at_booking=14500,
        )
        db.session.add(completed)
        db.session.commit()

        r = client.get("/api/admin/appointments?needs_followup=true", headers=auth_headers(reception_token))
        assert [row["followup_sent"] for row in r.get_json()] == [False]

    def test_patch_response_still_carries_the_full_detail_shape(
        self, client, reception_token, appointment
    ):
        """followup_sent moved onto the base serializer; the PATCH response
        must still expose it alongside the detail-only timestamps."""
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            json={"status": "confirmed"},
            headers=auth_headers(reception_token),
        )
        body = r.get_json()
        for field in ("followup_sent", "followup_sent_at", "confirmed_datetime", "completed_at"):
            assert field in body, f"{field} missing from PATCH response"

    def test_update_status_to_completed_sets_completed_at(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"status": "completed"},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["status"] == "completed"
        assert body["completed_at"] is not None

    def test_update_preferred_day(self, client, reception_token, appointment):
        new_day = (appointment.preferred_day + timedelta(days=5)).isoformat()
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"preferred_day": new_day},
        )
        assert r.status_code == 200
        assert r.get_json()["preferred_day"] == new_day

    def test_update_preferred_day_invalid_format(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"preferred_day": "not-a-date"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_update_invalid_status(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"status": "bogus"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_status"

    def test_update_invalid_reminder_call_status(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"reminder_call_status": "bogus"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_reminder_call_status"

    def test_update_no_recognized_fields(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"unrelated_field": "x"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_update_not_found(self, client, reception_token):
        r = client.patch(
            "/api/admin/appointments/999999",
            headers=auth_headers(reception_token),
            json={"status": "confirmed"},
        )
        assert r.status_code == 404
        assert r.get_json()["error"]["code"] == "appointment_not_found"

    def test_update_confirmed_datetime_and_clear(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"confirmed_datetime": "2026-01-01T10:00:00Z"},
        )
        assert r.status_code == 200
        assert r.get_json()["confirmed_datetime"] is not None

        r2 = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"confirmed_datetime": None},
        )
        assert r2.get_json()["confirmed_datetime"] is None

    def test_followup_sent_sets_timestamp(self, client, reception_token, appointment):
        r = client.patch(
            f"/api/admin/appointments/{appointment.id}",
            headers=auth_headers(reception_token),
            json={"followup_sent": True},
        )
        body = r.get_json()
        assert body["followup_sent"] is True
        assert body["followup_sent_at"] is not None

    def test_requires_auth(self, client, appointment):
        r = client.get("/api/admin/appointments")
        assert r.status_code == 401
        r2 = client.patch(f"/api/admin/appointments/{appointment.id}", json={"status": "confirmed"})
        assert r2.status_code == 401


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

class TestServices:
    def test_list(self, client, reception_token, service, variant):
        r = client.get("/api/admin/services", headers=auth_headers(reception_token))
        assert r.status_code == 200
        body = r.get_json()
        assert len(body) == 1
        assert body[0]["category"]["name_en"] == "Injections"
        assert body[0]["variants"][0]["price_usd"] == "100.00"

    def test_filter_by_category(self, client, reception_token, service, category):
        r = client.get(f"/api/admin/services?category_id={category.id}", headers=auth_headers(reception_token))
        assert len(r.get_json()) == 1
        r2 = client.get("/api/admin/services?category_id=999999", headers=auth_headers(reception_token))
        assert r2.get_json() == []

    def test_filter_by_availability(self, client, reception_token, service):
        r = client.get("/api/admin/services?is_available=false", headers=auth_headers(reception_token))
        assert r.get_json() == []
        r2 = client.get("/api/admin/services?is_available=true", headers=auth_headers(reception_token))
        assert len(r2.get_json()) == 1

    def test_create_service_minimal(self, client, reception_token, category):
        r = client.post(
            "/api/admin/services",
            headers=auth_headers(reception_token),
            json={"category_id": category.id, "name_ar": "خدمة", "name_en": "Service"},
        )
        assert r.status_code == 201
        body = r.get_json()
        assert body["is_available"] is True
        assert body["variants"] == []

    def test_create_service_with_variants(self, client, reception_token, category):
        r = client.post(
            "/api/admin/services",
            headers=auth_headers(reception_token),
            json={
                "category_id": category.id, "name_ar": "خدمة", "name_en": "Service",
                "variants": [{"brand_name_ar": "أ", "brand_name_en": "A", "price_usd": 50}],
            },
        )
        assert r.status_code == 201
        assert len(r.get_json()["variants"]) == 1

    def test_create_missing_fields(self, client, reception_token):
        r = client.post("/api/admin/services", headers=auth_headers(reception_token), json={"name_ar": "x"})
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_create_category_not_found(self, client, reception_token):
        r = client.post(
            "/api/admin/services",
            headers=auth_headers(reception_token),
            json={"category_id": 999999, "name_ar": "x", "name_en": "y"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "category_not_found"

    def test_create_invalid_variant_price(self, client, reception_token, category):
        r = client.post(
            "/api/admin/services",
            headers=auth_headers(reception_token),
            json={
                "category_id": category.id, "name_ar": "x", "name_en": "y",
                "variants": [{"brand_name_ar": "a", "brand_name_en": "b", "price_usd": -5}],
            },
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_update_service_fields(self, client, reception_token, service):
        r = client.put(
            f"/api/admin/services/{service.id}",
            headers=auth_headers(reception_token),
            json={"name_en": "Botox Updated", "is_available": False},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["name_en"] == "Botox Updated"
        assert body["is_available"] is False

    def test_update_add_new_variant_and_edit_existing(self, client, reception_token, service, variant):
        r = client.put(
            f"/api/admin/services/{service.id}",
            headers=auth_headers(reception_token),
            json={"variants": [
                {"id": variant.id, "price_usd": 150},
                {"brand_name_ar": "جديد", "brand_name_en": "New", "price_usd": 30},
            ]},
        )
        assert r.status_code == 200
        variants = r.get_json()["variants"]
        assert len(variants) == 2
        updated = next(v for v in variants if v["id"] == variant.id)
        assert updated["price_usd"] == "150.00"

    def test_update_unknown_variant_id_404(self, client, reception_token, service):
        r = client.put(
            f"/api/admin/services/{service.id}",
            headers=auth_headers(reception_token),
            json={"variants": [{"id": 999999, "price_usd": 10}]},
        )
        assert r.status_code == 404
        assert r.get_json()["error"]["code"] == "variant_not_found"

    def test_update_no_fields(self, client, reception_token, service):
        r = client.put(f"/api/admin/services/{service.id}", headers=auth_headers(reception_token), json={})
        assert r.status_code == 400

    def test_update_not_found(self, client, reception_token):
        r = client.put(
            "/api/admin/services/999999", headers=auth_headers(reception_token),
            json={"name_ar": "x"},
        )
        assert r.status_code == 404
        assert r.get_json()["error"]["code"] == "service_not_found"

    def test_update_invalid_category(self, client, reception_token, service):
        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"category_id": 999999},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "category_not_found"

    def test_delete_soft_disables(self, client, reception_token, service):
        r = client.delete(f"/api/admin/services/{service.id}", headers=auth_headers(reception_token))
        assert r.status_code == 200
        assert r.get_json()["is_available"] is False
        assert Service.query.get(service.id) is not None

    def test_delete_idempotent(self, client, reception_token, service):
        client.delete(f"/api/admin/services/{service.id}", headers=auth_headers(reception_token))
        r2 = client.delete(f"/api/admin/services/{service.id}", headers=auth_headers(reception_token))
        assert r2.status_code == 200
        assert r2.get_json()["is_available"] is False

    def test_delete_not_found(self, client, reception_token):
        r = client.delete("/api/admin/services/999999", headers=auth_headers(reception_token))
        assert r.status_code == 404


class TestServiceRelationships:
    """concern_ids / doctor_ids on service create + update."""

    def test_create_with_both_relationships(self, client, reception_token, category, concern, doctor):
        r = client.post(
            "/api/admin/services", headers=auth_headers(reception_token),
            json={
                "category_id": category.id, "name_ar": "خدمة", "name_en": "Service",
                "concern_ids": [concern.id], "doctor_ids": [doctor.id],
            },
        )
        assert r.status_code == 201
        body = r.get_json()
        assert [c["id"] for c in body["concerns"]] == [concern.id]
        assert [d["id"] for d in body["doctors"]] == [doctor.id]
        assert body["concerns"][0]["name_en"] == concern.name_en
        assert body["doctors"][0]["name_ar"] == doctor.name_ar

    def test_create_without_relationships_leaves_them_empty(self, client, reception_token, category):
        r = client.post(
            "/api/admin/services", headers=auth_headers(reception_token),
            json={"category_id": category.id, "name_ar": "خدمة", "name_en": "Service"},
        )
        assert r.status_code == 201
        assert r.get_json()["concerns"] == []
        assert r.get_json()["doctors"] == []

    def test_create_with_invalid_concern_id(self, client, reception_token, category):
        r = client.post(
            "/api/admin/services", headers=auth_headers(reception_token),
            json={
                "category_id": category.id, "name_ar": "خدمة", "name_en": "Service",
                "concern_ids": [999999],
            },
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_concern_id"
        # The whole request is rejected — no service row is left behind.
        assert Service.query.filter_by(name_en="Service").first() is None

    def test_create_with_invalid_doctor_id(self, client, reception_token, category):
        r = client.post(
            "/api/admin/services", headers=auth_headers(reception_token),
            json={
                "category_id": category.id, "name_ar": "خدمة", "name_en": "Service",
                "doctor_ids": [999999],
            },
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_doctor_id"
        assert Service.query.filter_by(name_en="Service").first() is None

    def test_update_concerns_only_leaves_doctors_untouched(
        self, client, reception_token, service, concern, doctor
    ):
        service.concerns = [concern]
        service.doctors = [doctor]
        db.session.commit()

        other = Concern(name_ar="أخرى", name_en="Other")
        db.session.add(other)
        db.session.commit()

        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": [other.id]},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert [c["id"] for c in body["concerns"]] == [other.id]
        # doctor_ids was absent from the body, so the link survives.
        assert [d["id"] for d in body["doctors"]] == [doctor.id]

    def test_update_replaces_rather_than_merges(self, client, reception_token, service, concern):
        second = Concern(name_ar="ثانية", name_en="Second")
        third = Concern(name_ar="ثالثة", name_en="Third")
        db.session.add_all([second, third])
        db.session.commit()
        service.concerns = [concern, second, third]
        db.session.commit()

        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": [second.id]},
        )
        assert r.status_code == 200
        assert [c["id"] for c in r.get_json()["concerns"]] == [second.id]

        # Gone from the junction table, not merely omitted from the response.
        rows = db.session.execute(
            service_concerns.select().where(service_concerns.c.service_id == service.id)
        ).all()
        assert [row.concern_id for row in rows] == [second.id]

    def test_update_with_empty_list_unlinks_everything(
        self, client, reception_token, service, concern
    ):
        service.concerns = [concern]
        db.session.commit()

        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": []},
        )
        assert r.status_code == 200
        assert r.get_json()["concerns"] == []

    def test_update_invalid_concern_id_changes_nothing(
        self, client, reception_token, service, concern
    ):
        service.concerns = [concern]
        db.session.commit()

        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"name_en": "Should Not Persist", "concern_ids": [99999]},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_concern_id"

        db.session.expire_all()
        refreshed = Service.query.get(service.id)
        # Neither the scalar field nor the relationship was touched.
        assert refreshed.name_en != "Should Not Persist"
        assert [c.id for c in refreshed.concerns] == [concern.id]

    def test_update_invalid_doctor_id_changes_nothing(
        self, client, reception_token, service, doctor
    ):
        service.doctors = [doctor]
        db.session.commit()

        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"name_en": "Should Not Persist", "doctor_ids": [99999]},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_doctor_id"

        db.session.expire_all()
        refreshed = Service.query.get(service.id)
        assert refreshed.name_en != "Should Not Persist"
        assert [d.id for d in refreshed.doctors] == [doctor.id]

    def test_relationship_ids_only_is_a_valid_update(self, client, reception_token, service, concern):
        """concern_ids alone must satisfy the has-recognized-fields check."""
        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": [concern.id]},
        )
        assert r.status_code == 200

    def test_non_list_concern_ids_is_a_validation_error(self, client, reception_token, service):
        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": "1,2"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_duplicate_ids_are_deduplicated(self, client, reception_token, service, concern):
        r = client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": [concern.id, concern.id]},
        )
        assert r.status_code == 200
        assert [c["id"] for c in r.get_json()["concerns"]] == [concern.id]

    def test_listing_reflects_saved_relationships(
        self, client, reception_token, service, concern, doctor
    ):
        client.put(
            f"/api/admin/services/{service.id}", headers=auth_headers(reception_token),
            json={"concern_ids": [concern.id], "doctor_ids": [doctor.id]},
        )
        r = client.get("/api/admin/services", headers=auth_headers(reception_token))
        assert r.status_code == 200
        entry = next(s for s in r.get_json() if s["id"] == service.id)
        assert [c["id"] for c in entry["concerns"]] == [concern.id]
        assert [d["id"] for d in entry["doctors"]] == [doctor.id]


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class TestCategories:
    def test_list(self, client, reception_token, category):
        r = client.get("/api/admin/categories", headers=auth_headers(reception_token))
        assert r.status_code == 200
        assert len(r.get_json()) == 1

    def test_create(self, client, reception_token):
        r = client.post(
            "/api/admin/categories", headers=auth_headers(reception_token),
            json={"name_ar": "جديد", "name_en": "New"},
        )
        assert r.status_code == 201
        assert r.get_json()["name_en"] == "New"

    def test_create_missing_fields(self, client, reception_token):
        r = client.post("/api/admin/categories", headers=auth_headers(reception_token), json={"name_ar": "x"})
        assert r.status_code == 400

    def test_create_duplicate_case_insensitive(self, client, reception_token, category):
        r = client.post(
            "/api/admin/categories", headers=auth_headers(reception_token),
            json={"name_ar": "حقن2", "name_en": "injections"},
        )
        assert r.status_code == 409
        assert r.get_json()["error"]["code"] == "duplicate_category"

    def test_create_whitespace_name_invalid(self, client, reception_token):
        r = client.post(
            "/api/admin/categories", headers=auth_headers(reception_token),
            json={"name_ar": "   ", "name_en": "x"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_update(self, client, reception_token, category):
        r = client.put(
            f"/api/admin/categories/{category.id}", headers=auth_headers(reception_token),
            json={"name_en": "Injections Updated"},
        )
        assert r.status_code == 200
        assert r.get_json()["name_en"] == "Injections Updated"

    def test_update_duplicate_excludes_self(self, client, reception_token, category):
        r = client.put(
            f"/api/admin/categories/{category.id}", headers=auth_headers(reception_token),
            json={"name_ar": category.name_ar},
        )
        assert r.status_code == 200

    def test_update_not_found(self, client, reception_token):
        r = client.put(
            "/api/admin/categories/999999", headers=auth_headers(reception_token),
            json={"name_ar": "x"},
        )
        assert r.status_code == 404

    def test_update_no_fields(self, client, reception_token, category):
        r = client.put(f"/api/admin/categories/{category.id}", headers=auth_headers(reception_token), json={})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Concerns
# ---------------------------------------------------------------------------

class TestConcerns:
    def test_list(self, client, reception_token, concern):
        r = client.get("/api/admin/concerns", headers=auth_headers(reception_token))
        assert len(r.get_json()) == 1

    def test_create(self, client, reception_token):
        r = client.post(
            "/api/admin/concerns", headers=auth_headers(reception_token),
            json={"name_ar": "جديد", "name_en": "New", "description_en": "d"},
        )
        assert r.status_code == 201

    def test_create_duplicate(self, client, reception_token, concern):
        r = client.post(
            "/api/admin/concerns", headers=auth_headers(reception_token),
            json={"name_ar": "x", "name_en": concern.name_en},
        )
        assert r.status_code == 409
        assert r.get_json()["error"]["code"] == "duplicate_concern"

    def test_create_invalid_description_type(self, client, reception_token):
        r = client.post(
            "/api/admin/concerns", headers=auth_headers(reception_token),
            json={"name_ar": "x", "name_en": "y", "description_ar": 123},
        )
        assert r.status_code == 400

    def test_update(self, client, reception_token, concern):
        r = client.put(
            f"/api/admin/concerns/{concern.id}", headers=auth_headers(reception_token),
            json={"description_en": "updated"},
        )
        assert r.status_code == 200
        assert r.get_json()["description_en"] == "updated"

    def test_update_not_found(self, client, reception_token):
        r = client.put(
            "/api/admin/concerns/999999", headers=auth_headers(reception_token),
            json={"name_ar": "x"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------

class TestDoctors:
    def test_list(self, client, reception_token, doctor):
        r = client.get("/api/admin/doctors", headers=auth_headers(reception_token))
        assert len(r.get_json()) == 1
        assert r.get_json()[0]["service_ids"] == []

    def test_filter_by_availability(self, client, reception_token, doctor):
        r = client.get("/api/admin/doctors?is_available=false", headers=auth_headers(reception_token))
        assert r.get_json() == []

    def test_create_with_services(self, client, reception_token, service):
        r = client.post(
            "/api/admin/doctors", headers=auth_headers(reception_token),
            json={"name_ar": "د. جديد", "name_en": "Dr. New", "service_ids": [service.id]},
        )
        assert r.status_code == 201
        assert r.get_json()["service_ids"] == [service.id]

    def test_create_invalid_service_ids(self, client, reception_token):
        r = client.post(
            "/api/admin/doctors", headers=auth_headers(reception_token),
            json={"name_ar": "د. جديد", "name_en": "Dr. New", "service_ids": [999999]},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_service_ids"

    def test_create_missing_fields(self, client, reception_token):
        r = client.post("/api/admin/doctors", headers=auth_headers(reception_token), json={"name_ar": "x"})
        assert r.status_code == 400

    def test_update_replaces_service_ids(self, client, reception_token, doctor, service):
        r = client.put(
            f"/api/admin/doctors/{doctor.id}", headers=auth_headers(reception_token),
            json={"service_ids": [service.id]},
        )
        assert r.status_code == 200
        assert r.get_json()["service_ids"] == [service.id]

        r2 = client.put(
            f"/api/admin/doctors/{doctor.id}", headers=auth_headers(reception_token),
            json={"service_ids": []},
        )
        assert r2.get_json()["service_ids"] == []

    def test_update_not_found(self, client, reception_token):
        r = client.put(
            "/api/admin/doctors/999999", headers=auth_headers(reception_token),
            json={"name_ar": "x"},
        )
        assert r.status_code == 404

    def test_delete_soft_disables(self, client, reception_token, doctor):
        r = client.delete(f"/api/admin/doctors/{doctor.id}", headers=auth_headers(reception_token))
        assert r.status_code == 200
        assert r.get_json()["is_available"] is False
        assert Doctor.query.get(doctor.id) is not None

    def test_delete_not_found(self, client, reception_token):
        r = client.delete("/api/admin/doctors/999999", headers=auth_headers(reception_token))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Offers (manager-only)
# ---------------------------------------------------------------------------

class TestOffers:
    def test_list_requires_manager(self, client, manager_token, offer):
        r = client.get("/api/admin/offers", headers=auth_headers(manager_token))
        assert r.status_code == 200
        assert len(r.get_json()) == 1
        assert r.get_json()[0]["items"][0]["offer_price_syp"] == "900000.00"

    def test_filter_active(self, client, manager_token, offer):
        r = client.get("/api/admin/offers?is_active=false", headers=auth_headers(manager_token))
        assert r.get_json() == []

    def test_create(self, client, manager_token, variant):
        r = client.post(
            "/api/admin/offers", headers=auth_headers(manager_token),
            json={
                "title_ar": "عرض جديد", "title_en": "New Offer",
                "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=5)),
                "items": [{"service_variant_id": variant.id, "offer_price_syp": 500000}],
            },
        )
        assert r.status_code == 201
        body = r.get_json()
        assert body["created_by"] is not None
        assert len(body["items"]) == 1

    def test_create_invalid_date_range(self, client, manager_token, variant):
        r = client.post(
            "/api/admin/offers", headers=auth_headers(manager_token),
            json={
                "title_ar": "x", "title_en": "y",
                "start_date": str(date.today() + timedelta(days=5)), "end_date": str(date.today()),
                "items": [{"service_variant_id": variant.id, "offer_price_syp": 500000}],
            },
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_date_range"

    def test_create_empty_items(self, client, manager_token):
        r = client.post(
            "/api/admin/offers", headers=auth_headers(manager_token),
            json={
                "title_ar": "x", "title_en": "y",
                "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=1)),
                "items": [],
            },
        )
        assert r.status_code == 400

    def test_create_duplicate_variant_in_items(self, client, manager_token, variant):
        r = client.post(
            "/api/admin/offers", headers=auth_headers(manager_token),
            json={
                "title_ar": "x", "title_en": "y",
                "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=1)),
                "items": [
                    {"service_variant_id": variant.id, "offer_price_syp": 1},
                    {"service_variant_id": variant.id, "offer_price_syp": 2},
                ],
            },
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "duplicate_offer_item"

    def test_create_unknown_variant(self, client, manager_token):
        r = client.post(
            "/api/admin/offers", headers=auth_headers(manager_token),
            json={
                "title_ar": "x", "title_en": "y",
                "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=1)),
                "items": [{"service_variant_id": 999999, "offer_price_syp": 1}],
            },
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "service_variant_not_found"

    def test_create_forbidden_for_reception(self, client, reception_token, variant):
        r = client.post(
            "/api/admin/offers", headers=auth_headers(reception_token),
            json={
                "title_ar": "x", "title_en": "y",
                "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=1)),
                "items": [{"service_variant_id": variant.id, "offer_price_syp": 1}],
            },
        )
        assert r.status_code == 403

    def test_update_add_item(self, client, manager_token, offer, variant):
        v2 = ServiceVariant(
            service_id=variant.service_id, brand_name_ar="ب", brand_name_en="B",
            price_usd=20, is_available=True,
        )
        db.session.add(v2)
        db.session.commit()

        r = client.put(
            f"/api/admin/offers/{offer.id}", headers=auth_headers(manager_token),
            json={"items": [{"service_variant_id": v2.id, "offer_price_syp": 10000}]},
        )
        assert r.status_code == 200
        assert len(r.get_json()["items"]) == 2

    def test_update_existing_item_by_id(self, client, manager_token, offer):
        item_id = offer.items[0].id
        r = client.put(
            f"/api/admin/offers/{offer.id}", headers=auth_headers(manager_token),
            json={"items": [{"id": item_id, "offer_price_syp": 123456}]},
        )
        assert r.status_code == 200
        item = next(i for i in r.get_json()["items"] if i["id"] == item_id)
        assert item["offer_price_syp"] == "123456.00"

    def test_update_unknown_item_id(self, client, manager_token, offer):
        r = client.put(
            f"/api/admin/offers/{offer.id}", headers=auth_headers(manager_token),
            json={"items": [{"id": 999999, "offer_price_syp": 1}]},
        )
        assert r.status_code == 404
        assert r.get_json()["error"]["code"] == "offer_item_not_found"

    def test_update_invalid_date_range(self, client, manager_token, offer):
        r = client.put(
            f"/api/admin/offers/{offer.id}", headers=auth_headers(manager_token),
            json={"start_date": str(offer.end_date + timedelta(days=1))},
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_date_range"

    def test_update_not_found(self, client, manager_token):
        r = client.put(
            "/api/admin/offers/999999", headers=auth_headers(manager_token),
            json={"is_active": False},
        )
        assert r.status_code == 404

    def test_delete_soft_disables(self, client, manager_token, offer):
        r = client.delete(f"/api/admin/offers/{offer.id}", headers=auth_headers(manager_token))
        assert r.status_code == 200
        assert r.get_json()["is_active"] is False
        assert Offer.query.get(offer.id) is not None
        assert len(OfferItem.query.filter_by(offer_id=offer.id).all()) == 1

    def test_delete_not_found(self, client, manager_token):
        r = client.delete("/api/admin/offers/999999", headers=auth_headers(manager_token))
        assert r.status_code == 404

    def test_delete_forbidden_for_reception(self, client, reception_token, offer):
        r = client.delete(f"/api/admin/offers/{offer.id}", headers=auth_headers(reception_token))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Exchange rate (manager-only)
# ---------------------------------------------------------------------------

class TestExchangeRate:
    def test_create_first_rate(self, client, manager_token, manager_user):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={"rate": 15000})
        assert r.status_code == 200
        body = r.get_json()
        assert body["rate"] == "15000.00"
        assert body["updated_by"] == manager_user.id

    def test_update_existing_rate_in_place(self, client, manager_token):
        r1 = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={"rate": 15000})
        first_id = r1.get_json()["id"]
        r2 = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={"rate": 16000})
        assert r2.get_json()["id"] == first_id
        assert r2.get_json()["rate"] == "16000.00"

        from app.models import ExchangeRate
        assert ExchangeRate.query.count() == 1

    def test_missing_rate(self, client, manager_token):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={})
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "validation_error"

    def test_negative_rate_rejected(self, client, manager_token):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={"rate": -5})
        assert r.status_code == 400

    def test_zero_rate_rejected(self, client, manager_token):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={"rate": 0})
        assert r.status_code == 400

    def test_non_numeric_rate_rejected(self, client, manager_token):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(manager_token), json={"rate": "abc"})
        assert r.status_code == 400

    def test_forbidden_for_reception(self, client, reception_token):
        r = client.put("/api/admin/exchange-rate", headers=auth_headers(reception_token), json={"rate": 15000})
        assert r.status_code == 403

    def test_requires_auth(self, client):
        r = client.put("/api/admin/exchange-rate", json={"rate": 15000})
        assert r.status_code == 401
