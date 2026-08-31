from app.extensions import db
from datetime import datetime


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name_ar = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Category {self.name_ar}>"

class Concern(db.Model):
    __tablename__ = "concerns"

    id = db.Column(db.Integer, primary_key=True)
    name_ar = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100), nullable=False)
    description_ar = db.Column(db.Text, nullable=True)
    description_en = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Concern {self.name_ar}>"

# ---------- جداول وسيطة (Many-to-Many) ----------

service_concerns = db.Table(
    "service_concerns",
    db.Column("service_id", db.Integer, db.ForeignKey("services.id"), primary_key=True),
    db.Column("concern_id", db.Integer, db.ForeignKey("concerns.id"), primary_key=True),
)

doctor_services = db.Table(
    "doctor_services",
    db.Column("doctor_id", db.Integer, db.ForeignKey("doctors.id"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services.id"), primary_key=True),
)


class Doctor(db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    name_ar = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100), nullable=False)
    specialty_ar = db.Column(db.String(100))
    specialty_en = db.Column(db.String(100))
    bio_ar = db.Column(db.Text)
    bio_en = db.Column(db.Text)
    photo_url = db.Column(db.String(255))

    services = db.relationship("Service", secondary=doctor_services, back_populates="doctors")

    def __repr__(self):
        return f"<Doctor {self.name_ar}>"


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    name_ar = db.Column(db.String(150), nullable=False)
    name_en = db.Column(db.String(150), nullable=False)
    description_ar = db.Column(db.Text)
    description_en = db.Column(db.Text)
    duration_estimate = db.Column(db.Integer)  # بالدقائق
    is_available = db.Column(db.Boolean, default=True, nullable=False)

    category = db.relationship("Category", backref="services")
    variants = db.relationship("ServiceVariant", backref="service")
    concerns = db.relationship("Concern", secondary=service_concerns, backref="services")
    doctors = db.relationship("Doctor", secondary=doctor_services, back_populates="services")

    def __repr__(self):
        return f"<Service {self.name_ar}>"


class ServiceVariant(db.Model):
    __tablename__ = "service_variants"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    brand_name_ar = db.Column(db.String(100), nullable=False)
    brand_name_en = db.Column(db.String(100), nullable=False)
    price_usd = db.Column(db.Numeric(10, 2), nullable=False)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    discontinued_at = db.Column(db.DateTime, nullable=True)

    offer_items = db.relationship("OfferItem", back_populates="service_variant")

    def __repr__(self):
        return f"<ServiceVariant {self.brand_name_ar}>"


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'manager' أو 'reception'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AdminUser {self.username}>"


class Offer(db.Model):
    __tablename__ = "offers"

    id = db.Column(db.Integer, primary_key=True)
    title_ar = db.Column(db.String(150), nullable=False)
    title_en = db.Column(db.String(150), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("admin_users.id"))

    items = db.relationship("OfferItem", backref="offer")

    def __repr__(self):
        return f"<Offer {self.title_ar}>"


class OfferItem(db.Model):
    __tablename__ = "offer_items"

    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offers.id"), nullable=False)
    service_variant_id = db.Column(db.Integer, db.ForeignKey("service_variants.id"), nullable=False)
    offer_price_syp = db.Column(db.Numeric(12, 2), nullable=False)

    service_variant = db.relationship("ServiceVariant", back_populates="offer_items")

    def __repr__(self):
        return f"<OfferItem offer={self.offer_id} variant={self.service_variant_id}>"


class ExchangeRate(db.Model):
    __tablename__ = "exchange_rates"

    id = db.Column(db.Integer, primary_key=True)
    rate = db.Column(db.Numeric(10, 2), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("admin_users.id"))

    def __repr__(self):
        return f"<ExchangeRate {self.rate}>"


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_name = db.Column(db.String(150), nullable=False)
    patient_phone = db.Column(db.String(20), nullable=False)
    service_variant_id = db.Column(db.Integer, db.ForeignKey("service_variants.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    preferred_day = db.Column(db.Date, nullable=False)

    # 'pending' / 'confirmed' / 'rescheduled' / 'cancelled' / 'completed' / 'no_show'
    status = db.Column(db.String(20), default="pending", nullable=False)
    confirmed_datetime = db.Column(db.DateTime, nullable=True)

    # 'not_called' / 'called_confirmed' / 'called_cancelled' / 'called_rescheduled'
    reminder_call_status = db.Column(db.String(20), default="not_called")
    reminder_call_at = db.Column(db.DateTime, nullable=True)

    completed_at = db.Column(db.DateTime, nullable=True)
    followup_sent = db.Column(db.Boolean, default=False)
    followup_sent_at = db.Column(db.DateTime, nullable=True)

    offer_item_id = db.Column(db.Integer, db.ForeignKey("offer_items.id"), nullable=True)
    final_price_syp_at_booking = db.Column(db.Numeric(12, 2), nullable=False)
    exchange_rate_at_booking = db.Column(db.Numeric(10, 2), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    service_variant = db.relationship("ServiceVariant")
    doctor = db.relationship("Doctor")
    offer_item = db.relationship("OfferItem")

    def __repr__(self):
        return f"<Appointment {self.patient_name} - {self.status}>"