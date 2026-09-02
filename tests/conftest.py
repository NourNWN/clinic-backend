import os
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import create_app
from app.extensions import db
from app.models import (
    AdminUser, Category, Concern, Doctor, ExchangeRate, Offer, OfferItem,
    Service, ServiceVariant,
)


@pytest.fixture()
def app():
    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite://",
    )

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def manager_user(app):
    user = AdminUser(
        username="manager1",
        password_hash=generate_password_hash("manager-pass"),
        full_name="Manager One",
        role="manager",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def reception_user(app):
    user = AdminUser(
        username="reception1",
        password_hash=generate_password_hash("reception-pass"),
        full_name="Reception One",
        role="reception",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def manager_token(client, manager_user):
    r = client.post("/api/admin/login", json={"username": "manager1", "password": "manager-pass"})
    return r.get_json()["token"]


@pytest.fixture()
def reception_token(client, reception_user):
    r = client.post("/api/admin/login", json={"username": "reception1", "password": "reception-pass"})
    return r.get_json()["token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def category(app):
    c = Category(name_ar="حقن", name_en="Injections")
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def service(app, category):
    s = Service(
        category_id=category.id,
        name_ar="بوتوكس", name_en="Botox",
        description_ar="desc ar", description_en="desc en",
        duration_estimate=20,
        is_available=True,
    )
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture()
def variant(app, service):
    v = ServiceVariant(
        service_id=service.id,
        brand_name_ar="ألماني", brand_name_en="German",
        price_usd=100.00, is_available=True,
    )
    db.session.add(v)
    db.session.commit()
    return v


@pytest.fixture()
def doctor(app):
    d = Doctor(name_ar="د. سارة", name_en="Dr. Sara", is_available=True)
    db.session.add(d)
    db.session.commit()
    return d


@pytest.fixture()
def concern(app):
    c = Concern(name_ar="تجاعيد", name_en="Wrinkles",
                description_ar="d ar", description_en="d en")
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def appointment(app, variant, doctor):
    from app.models import Appointment
    a = Appointment(
        patient_name="Test Patient",
        patient_phone="+963900000000",
        service_variant_id=variant.id,
        doctor_id=doctor.id,
        preferred_day=date.today() + timedelta(days=1),
        status="pending",
        final_price_syp_at_booking=1000000,
        exchange_rate_at_booking=14500,
    )
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture()
def offer(app, variant, manager_user):
    o = Offer(
        title_ar="عرض", title_en="Offer",
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=10),
        is_active=True,
        created_by=manager_user.id,
    )
    db.session.add(o)
    db.session.flush()
    item = OfferItem(offer_id=o.id, service_variant_id=variant.id, offer_price_syp=900000)
    db.session.add(item)
    db.session.commit()
    return o
