"""Public booking endpoint: POST /api/appointments.

Every rejection here must come back as the JSON error envelope
(`{"error": {"code", "message_ar", "message_en"}}`) that the frontend's
ApiError reads. A malformed value reaching the driver instead produces an
HTML 500, which the frontend can only render as a generic failure.
"""
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import Appointment, ExchangeRate


@pytest.fixture()
def exchange_rate(app):
    rate = ExchangeRate(rate=14000)
    db.session.add(rate)
    db.session.commit()
    return rate


@pytest.fixture(autouse=True)
def _doctor_provides_the_service(service, doctor):
    """Booking requires a doctor who actually provides the treatment, so every
    test here starts from that state — otherwise the doctor/service guard
    rejects the request before the behaviour under test is reached."""
    service.doctors = [doctor]
    db.session.commit()


def _payload(variant, doctor, **overrides):
    body = {
        "patient_name": "سارة",
        "patient_phone": "+963900000000",
        "service_variant_id": variant.id,
        "doctor_id": doctor.id,
        "preferred_day": (date.today() + timedelta(days=3)).isoformat(),
    }
    body.update(overrides)
    return body


def _assert_validation_error(response):
    """A 400 carrying the bilingual envelope — never an HTML error page."""
    assert response.status_code == 400
    assert response.content_type.startswith("application/json")
    error = response.get_json()["error"]
    assert error["code"] == "validation_error"
    assert error["message_ar"] and error["message_en"]


class TestBookingSuccess:
    def test_valid_booking_is_created(self, client, variant, doctor, exchange_rate):
        r = client.post("/api/appointments", json=_payload(variant, doctor))

        assert r.status_code == 201
        body = r.get_json()
        assert body["status"] == "pending"
        assert body["message_ar"] and body["message_en"]

        booking = db.session.get(Appointment, body["id"])
        assert booking.preferred_day == date.today() + timedelta(days=3)
        assert booking.exchange_rate_at_booking == exchange_rate.rate
        assert booking.final_price_syp_at_booking == variant.price_usd * exchange_rate.rate

    def test_preferred_day_is_stored_as_a_date_not_a_string(
        self, client, variant, doctor, exchange_rate
    ):
        r = client.post("/api/appointments", json=_payload(variant, doctor))

        booking = db.session.get(Appointment, r.get_json()["id"])
        assert isinstance(booking.preferred_day, date)

    def test_booking_with_an_active_offer_freezes_the_offer_price(
        self, client, variant, doctor, exchange_rate, offer
    ):
        item = offer.items[0]

        r = client.post(
            "/api/appointments",
            json=_payload(variant, doctor, offer_item_id=item.id),
        )

        assert r.status_code == 201
        booking = db.session.get(Appointment, r.get_json()["id"])
        assert booking.offer_item_id == item.id
        assert booking.final_price_syp_at_booking == item.offer_price_syp


class TestMalformedValuesAreRejected:
    """Regression: each of these used to reach the database driver and come
    back as an unhandled 500 with an HTML body."""

    @pytest.mark.parametrize(
        "bad_day",
        ["not-a-date", "2026-02-31", "03/09/2026", "", 12345, None, [], {}],
        ids=["gibberish", "impossible-date", "wrong-format", "empty",
             "int", "null", "list", "dict"],
    )
    def test_unparseable_preferred_day(
        self, client, variant, doctor, exchange_rate, bad_day
    ):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, preferred_day=bad_day)
        )
        _assert_validation_error(r)

    @pytest.mark.parametrize("field", ["service_variant_id", "doctor_id"])
    @pytest.mark.parametrize(
        "bad_id", ["abc", "12", 1.5, [], {}], ids=["word", "numeric-string", "float", "list", "dict"]
    )
    def test_non_integer_ids(self, client, variant, doctor, exchange_rate, field, bad_id):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, **{field: bad_id})
        )
        _assert_validation_error(r)

    @pytest.mark.parametrize("field", ["service_variant_id", "doctor_id"])
    def test_boolean_is_not_a_valid_id(self, client, variant, doctor, exchange_rate, field):
        """`isinstance(True, int)` is True, so bools need rejecting explicitly."""
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, **{field: True})
        )
        _assert_validation_error(r)

    def test_non_integer_offer_item_id(self, client, variant, doctor, exchange_rate):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, offer_item_id="abc")
        )
        _assert_validation_error(r)

    def test_no_json_body(self, client, exchange_rate):
        r = client.post("/api/appointments")
        _assert_validation_error(r)

    def test_body_is_not_an_object(self, client, exchange_rate):
        r = client.post("/api/appointments", json=["not", "an", "object"])
        _assert_validation_error(r)

    def test_nothing_is_persisted_when_validation_fails(
        self, client, variant, doctor, exchange_rate
    ):
        client.post(
            "/api/appointments",
            json=_payload(variant, doctor, preferred_day="not-a-date"),
        )
        assert Appointment.query.count() == 0


class TestPatientFieldLimits:
    """`patient_name` and `patient_phone` are varchar(150)/varchar(20).

    An over-long or non-string value used to travel all the way to the driver
    and fail there as a psycopg2 DataError — an HTML 500 instead of the JSON
    envelope. SQLite ignores both constraints, so these cases pass silently on
    the test database and only break against PostgreSQL; that is exactly the
    gap these tests exist to close.
    """

    def test_over_long_name_is_rejected(self, client, variant, doctor, exchange_rate):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, patient_name="x" * 151)
        )
        _assert_validation_error(r)
        assert Appointment.query.count() == 0

    def test_over_long_phone_is_rejected(self, client, variant, doctor, exchange_rate):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, patient_phone="9" * 21)
        )
        _assert_validation_error(r)
        assert Appointment.query.count() == 0

    def test_name_at_the_limit_is_accepted(self, client, variant, doctor, exchange_rate):
        """The boundary itself must still fit — 150 is a legal name."""
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, patient_name="x" * 150)
        )
        assert r.status_code == 201

    @pytest.mark.parametrize(
        "bad", [12345, 1.5, True, [], {}],
        ids=["int", "float", "bool", "list", "dict"],
    )
    @pytest.mark.parametrize("field", ["patient_name", "patient_phone"])
    def test_non_string_values_are_rejected(
        self, client, variant, doctor, exchange_rate, field, bad
    ):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, **{field: bad})
        )
        _assert_validation_error(r)

    @pytest.mark.parametrize("field", ["patient_name", "patient_phone"])
    def test_whitespace_only_is_rejected(
        self, client, variant, doctor, exchange_rate, field
    ):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, **{field: "   "})
        )
        _assert_validation_error(r)

    def test_surrounding_whitespace_is_trimmed(self, client, variant, doctor, exchange_rate):
        r = client.post(
            "/api/appointments",
            json=_payload(variant, doctor, patient_name="  سارة  ", patient_phone=" +963900000000 "),
        )
        assert r.status_code == 201
        stored = Appointment.query.one()
        assert stored.patient_name == "سارة"
        assert stored.patient_phone == "+963900000000"


class TestPreferredDayIsNotInThePast:
    """The booking form sets `min={today}`, so this rule lived only in the
    browser. Anything not going through that form could file a booking into
    the past, where it sorts to the top of the admin list."""

    def test_yesterday_is_rejected(self, client, variant, doctor, exchange_rate):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, preferred_day=yesterday)
        )
        assert r.status_code == 400
        assert r.is_json
        error = r.get_json()["error"]
        assert error["code"] == "preferred_day_in_past"
        assert error["message_ar"] and error["message_en"]
        assert Appointment.query.count() == 0

    def test_long_past_is_rejected(self, client, variant, doctor, exchange_rate):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, preferred_day="2020-01-01")
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "preferred_day_in_past"

    def test_today_is_still_allowed(self, client, variant, doctor, exchange_rate):
        """A same-day request is a normal walk-in, not a past booking."""
        r = client.post(
            "/api/appointments",
            json=_payload(variant, doctor, preferred_day=date.today().isoformat()),
        )
        assert r.status_code == 201

    def test_future_is_still_allowed(self, client, variant, doctor, exchange_rate):
        r = client.post("/api/appointments", json=_payload(variant, doctor))
        assert r.status_code == 201


class TestMissingAndUnknownReferences:
    @pytest.mark.parametrize(
        "field",
        ["patient_name", "patient_phone", "service_variant_id", "doctor_id", "preferred_day"],
    )
    def test_missing_required_field(self, client, variant, doctor, exchange_rate, field):
        body = _payload(variant, doctor)
        del body[field]

        r = client.post("/api/appointments", json=body)
        _assert_validation_error(r)
        assert field in r.get_json()["error"]["message_en"]

    def test_unknown_variant(self, client, variant, doctor, exchange_rate):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, service_variant_id=999999)
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_variant"

    def test_unavailable_variant(self, client, variant, doctor, exchange_rate):
        variant.is_available = False
        db.session.commit()

        r = client.post("/api/appointments", json=_payload(variant, doctor))
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_variant"

    def test_unknown_doctor(self, client, variant, doctor, exchange_rate):
        r = client.post("/api/appointments", json=_payload(variant, doctor, doctor_id=999999))
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_doctor"

    def test_offer_that_does_not_match_the_variant(
        self, client, variant, doctor, exchange_rate
    ):
        r = client.post(
            "/api/appointments", json=_payload(variant, doctor, offer_item_id=999999)
        )
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "invalid_offer"

    def test_no_exchange_rate_set(self, client, variant, doctor):
        """No `exchange_rate` fixture here — booking can't price the visit."""
        r = client.post("/api/appointments", json=_payload(variant, doctor))
        assert r.status_code == 503
        assert r.get_json()["error"]["code"] == "no_exchange_rate"


class TestAvailabilityGuards:
    """What the clinic has withdrawn must not keep taking bookings.

    The public site already hides all of these, so anything reaching the API
    in these states came from outside the booking form — a stale tab, a
    replayed request, or a script. Each was accepted before.
    """

    def _assert_rejected(self, response, code):
        assert response.status_code == 400
        assert response.content_type.startswith("application/json")
        error = response.get_json()["error"]
        assert error["code"] == code
        assert error["message_ar"] and error["message_en"]

    def test_variant_of_a_disabled_service_is_rejected(
        self, client, variant, doctor, service, exchange_rate
    ):
        """Soft-deleting a service only clears Service.is_available and leaves
        each variant's own flag alone, so a check on the variant by itself let
        a withdrawn treatment stay bookable."""
        service.is_available = False
        db.session.commit()

        r = client.post("/api/appointments", json=_payload(variant, doctor))
        self._assert_rejected(r, "invalid_variant")
        assert Appointment.query.count() == 0

    def test_unavailable_doctor_is_rejected(self, client, variant, doctor, exchange_rate):
        doctor.is_available = False
        db.session.commit()

        r = client.post("/api/appointments", json=_payload(variant, doctor))
        self._assert_rejected(r, "doctor_not_available")
        assert Appointment.query.count() == 0

    def test_doctor_not_linked_to_the_service_is_rejected(
        self, client, variant, doctor, service, exchange_rate
    ):
        """The public service page builds its practitioner list from
        doctor_services, so an unlinked pairing can't come from that flow."""
        service.doctors = []
        db.session.commit()

        r = client.post("/api/appointments", json=_payload(variant, doctor))
        self._assert_rejected(r, "doctor_not_available_for_service")
        assert Appointment.query.count() == 0

    def test_a_fully_available_booking_still_succeeds(
        self, client, variant, doctor, exchange_rate
    ):
        """The guards must not narrow the healthy path."""
        r = client.post("/api/appointments", json=_payload(variant, doctor))
        assert r.status_code == 201
        assert Appointment.query.count() == 1

    def test_disabled_variant_still_rejected(self, client, variant, doctor, exchange_rate):
        """The original check, retained alongside the new service-level one."""
        variant.is_available = False
        db.session.commit()

        r = client.post("/api/appointments", json=_payload(variant, doctor))
        self._assert_rejected(r, "invalid_variant")
