import os
from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

os.environ.setdefault("SECRET_KEY", "test-secret-key")


# ---------------------------------------------------------------------------
# Test database
#
# The suite runs on PostgreSQL, against a database of its own, because
# production does. It used to run on in-memory SQLite, which silently accepts
# things PostgreSQL rejects — VARCHAR lengths are not enforced and date
# coercion is far looser — so a whole class of bug passed as a green test and
# only failed in production. There is deliberately no SQLite fallback: a
# suite that quietly runs on the wrong engine is the problem being fixed.
#
# ALL of this has to happen BEFORE `from app import create_app` below.
# `config.Config` reads DATABASE_URL when its module is imported, and
# Flask-SQLAlchemy builds its engines inside `db.init_app(app)` — so by the
# time an app object exists, its engine is already bound. Overriding
# SQLALCHEMY_DATABASE_URI on the app afterwards changes the config value and
# nothing else: the engine still points wherever DATABASE_URL pointed at
# import time. Redirecting the environment variable up front is what actually
# moves the connection, and `_assert_engine_is_the_test_database` below fails
# loudly if it ever stops being true.
# ---------------------------------------------------------------------------

def _resolve_test_database_url():
    """The URL for the throwaway test database.

    `TEST_DATABASE_URL` wins if set; otherwise it is derived from
    `DATABASE_URL` by suffixing the database name, so a normal dev checkout
    needs no extra configuration.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)

    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.exit(
            "Neither TEST_DATABASE_URL nor DATABASE_URL is set — the suite "
            "needs a PostgreSQL server to run against.",
            returncode=1,
        )

    base_url = make_url(base)
    if not base_url.database:
        pytest.exit("DATABASE_URL names no database.", returncode=1)

    return base_url.set(database=f"{base_url.database}_test")


def _create_database_if_missing(url):
    """Create the test database, connecting to the `postgres` maintenance DB.

    CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    """
    admin_engine = sa.create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if exists:
                return
            conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    except sa.exc.OperationalError as exc:
        pytest.exit(
            f"Cannot reach PostgreSQL at {url.host}:{url.port} to prepare the "
            f"test database '{url.database}'. Start PostgreSQL, or point "
            f"TEST_DATABASE_URL at a reachable server.\n{exc}",
            returncode=1,
        )
    except sa.exc.ProgrammingError as exc:
        # Creating databases is a role-level privilege the application user
        # usually shouldn't have, so say exactly what to run instead of
        # surfacing a bare permission error.
        pytest.exit(
            f"The database '{url.database}' does not exist and "
            f"'{url.username}' may not create it. Create it once as a "
            f"superuser:\n\n"
            f'    CREATE DATABASE "{url.database}" OWNER {url.username};\n\n'
            f"(or grant the role CREATEDB, or point TEST_DATABASE_URL at a "
            f"database that already exists)\n{exc}",
            returncode=1,
        )
    finally:
        admin_engine.dispose()


# .env holds DATABASE_URL; load it here because this all runs at import time,
# before app.config would have done it.
load_dotenv()

_DEV_DATABASE_URL = os.environ.get("DATABASE_URL")
TEST_DATABASE_URL = _resolve_test_database_url()

# The suite truncates every table it can see, so being pointed at the
# development database would destroy real data. Checked before anything
# connects.
if _DEV_DATABASE_URL and make_url(_DEV_DATABASE_URL).database == TEST_DATABASE_URL.database:
    raise RuntimeError(
        f"Refusing to run: the test database ('{TEST_DATABASE_URL.database}') "
        f"is the same as DATABASE_URL's. The suite truncates every table."
    )

_create_database_if_missing(TEST_DATABASE_URL)

# Redirect the environment itself, before `app`/`config` are imported — see
# the note above. This is what actually binds the engine to the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (  # noqa: E402
    AdminUser, Category, Concern, Doctor, ExchangeRate, Offer, OfferItem,
    Service, ServiceVariant,
)


def _assert_engine_is_the_test_database():
    """Last line of defence before any destructive statement.

    The import-time redirection above is easy to break — a stray import of
    `app` earlier in the chain, a change to how Config reads its settings —
    and the failure mode is silent and destructive: drop_all() and TRUNCATE
    would run against whatever the engine is really bound to. So the actual
    engine is checked rather than the config value, which can disagree with it.
    """
    bound = db.engine.url.database
    if bound != TEST_DATABASE_URL.database:
        pytest.exit(
            f"Refusing to touch database '{bound}': the suite expects to be "
            f"connected to '{TEST_DATABASE_URL.database}'. The engine is bound "
            f"somewhere other than the test database — no tables were changed.",
            returncode=1,
        )


@pytest.fixture(scope="session")
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)

    with flask_app.app_context():
        _assert_engine_is_the_test_database()
        # Schema is built once for the whole session; per-test isolation comes
        # from truncation below, which is far cheaper than create_all/drop_all
        # on a real server.
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def _clean_database(app):
    """Every test starts against empty tables.

    Truncating up front (rather than after) means a test that dies mid-way
    can't leave rows behind for the next one. RESTART IDENTITY keeps ids
    predictable from test to test, as a fresh database would.
    """
    db.session.rollback()
    db.session.remove()

    _assert_engine_is_the_test_database()
    table_names = ", ".join(f'"{t.name}"' for t in db.metadata.sorted_tables)
    with db.engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))

    yield

    db.session.remove()


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
