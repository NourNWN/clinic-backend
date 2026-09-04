"""Public (unauthenticated) catalogue rules: what the site may show."""
from datetime import date, timedelta

from app.extensions import db
from app.models import Offer, OfferItem, ServiceVariant


def _variant(service, **kwargs):
    v = ServiceVariant(
        service_id=service.id,
        brand_name_ar="ماركة", brand_name_en="Brand",
        price_usd=100.00,
        **kwargs,
    )
    db.session.add(v)
    db.session.commit()
    return v


class TestPublicServiceVisibility:
    def test_service_with_available_variant_is_listed(self, client, service, variant):
        r = client.get("/api/services")
        assert r.status_code == 200
        assert [s["id"] for s in r.get_json()] == [service.id]

    def test_service_hidden_when_all_variants_unavailable(self, client, service, variant):
        variant.is_available = False
        db.session.commit()

        r = client.get("/api/services")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_detail_404s_when_all_variants_unavailable(self, client, service, variant):
        variant.is_available = False
        db.session.commit()

        r = client.get(f"/api/services/{service.id}")
        assert r.status_code == 404
        assert r.get_json()["error"]["code"] == "service_not_found"

    def test_detail_404_is_identical_to_unknown_id(self, client, service, variant):
        """A service that exists but has no bookable brand must be
        indistinguishable from one that was never there."""
        variant.is_available = False
        db.session.commit()

        hidden = client.get(f"/api/services/{service.id}")
        missing = client.get("/api/services/999999")
        assert hidden.status_code == missing.status_code == 404
        assert hidden.get_json() == missing.get_json()

    def test_service_reappears_when_a_variant_is_re_enabled(self, client, service, variant):
        variant.is_available = False
        db.session.commit()
        assert client.get("/api/services").get_json() == []

        variant.is_available = True
        db.session.commit()

        listing = client.get("/api/services").get_json()
        assert [s["id"] for s in listing] == [service.id]
        assert client.get(f"/api/services/{service.id}").status_code == 200

    def test_one_available_variant_among_many_keeps_service_listed(self, client, service, variant):
        second = _variant(service, is_available=False)

        listing = client.get("/api/services").get_json()
        assert [s["id"] for s in listing] == [service.id]
        # Only the bookable brand counts toward the preview.
        assert listing[0]["variants_preview"]["count"] == 1

        detail = client.get(f"/api/services/{service.id}").get_json()
        assert [v["id"] for v in detail["variants"]] == [variant.id]
        assert second.id not in [v["id"] for v in detail["variants"]]

    def test_service_with_no_variants_at_all_is_hidden(self, client, service):
        r = client.get("/api/services")
        assert r.get_json() == []
        assert client.get(f"/api/services/{service.id}").status_code == 404

    def test_service_flag_still_hides_independently(self, client, service, variant):
        """An available brand doesn't override Service.is_available=False."""
        service.is_available = False
        db.session.commit()

        assert client.get("/api/services").get_json() == []
        assert client.get(f"/api/services/{service.id}").status_code == 404


class TestAdminUnaffected:
    def test_admin_listing_still_shows_service_with_no_available_variants(
        self, client, reception_token, service, variant
    ):
        variant.is_available = False
        db.session.commit()

        r = client.get(
            "/api/admin/services",
            headers={"Authorization": f"Bearer {reception_token}"},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert [s["id"] for s in body] == [service.id]
        # The admin still sees the unavailable brand, so it can be re-enabled.
        assert [v["is_available"] for v in body[0]["variants"]] == [False]

    def test_admin_listing_shows_service_with_no_variants(
        self, client, reception_token, service
    ):
        r = client.get(
            "/api/admin/services",
            headers={"Authorization": f"Bearer {reception_token}"},
        )
        assert [s["id"] for s in r.get_json()] == [service.id]


class TestPublicPhotos:
    """A photo reaches the public site on the service, on each bookable brand,
    and on the banner of whichever offer is live for that brand."""

    def test_list_and_detail_expose_the_service_photo(self, client, service, variant):
        service.photo_url = "https://cdn.example.com/service.jpg"
        db.session.commit()

        assert client.get("/api/services").get_json()[0]["photo_url"] == \
            "https://cdn.example.com/service.jpg"
        detail = client.get(f"/api/services/{service.id}").get_json()
        assert detail["photo_url"] == "https://cdn.example.com/service.jpg"

    def test_detail_exposes_each_brand_photo(self, client, service, variant):
        variant.photo_url = "/uploads/brand.png"
        db.session.commit()

        detail = client.get(f"/api/services/{service.id}").get_json()
        assert detail["variants"][0]["photo_url"] == "/uploads/brand.png"

    def test_an_active_offer_carries_its_own_banner(self, client, service, variant, offer):
        offer.photo_url = "/uploads/offer.png"
        db.session.commit()

        detail = client.get(f"/api/services/{service.id}").get_json()
        assert detail["variants"][0]["active_offer"]["photo_url"] == "/uploads/offer.png"

    def test_unset_photos_are_reported_as_null(self, client, service, variant, offer):
        detail = client.get(f"/api/services/{service.id}").get_json()
        assert detail["photo_url"] is None
        assert detail["variants"][0]["photo_url"] is None
        assert detail["variants"][0]["active_offer"]["photo_url"] is None
        assert client.get("/api/services").get_json()[0]["photo_url"] is None


def _offer(variant, *, start, end, is_active=True, title_en="Offer",
           photo_url=None, price=900000, item_active=True):
    o = Offer(
        title_ar="عرض", title_en=title_en,
        start_date=start, end_date=end,
        is_active=is_active, photo_url=photo_url,
    )
    db.session.add(o)
    db.session.flush()
    db.session.add(OfferItem(
        offer_id=o.id,
        service_variant_id=variant.id,
        offer_price_syp=price,
        is_active=item_active,
    ))
    db.session.commit()
    return o


class TestPublicOffersWindow:
    """Only an offer a patient can act on today belongs on the public site."""

    def test_a_running_offer_is_listed_with_its_brands(self, client, service, variant):
        _offer(
            variant,
            start=date.today() - timedelta(days=1),
            end=date.today() + timedelta(days=3),
            photo_url="/uploads/offer.png",
        )

        body = client.get("/api/offers").get_json()
        assert len(body) == 1
        assert body[0]["title_en"] == "Offer"
        assert body[0]["photo_url"] == "/uploads/offer.png"

        item = body[0]["items"][0]
        assert item["service_variant_id"] == variant.id
        assert item["brand_name_en"] == "German"
        assert item["offer_price_syp"] == "900000.00"
        # The usual price rides along so the site can strike it through.
        assert item["price_usd"] == "100.00"
        assert item["service"]["id"] == service.id
        # BookingModal posts this back to freeze the offer price.
        assert item["offer_item_id"] is not None

    def test_an_offer_starting_today_is_already_live(self, client, variant):
        _offer(variant, start=date.today(), end=date.today() + timedelta(days=1))
        assert len(client.get("/api/offers").get_json()) == 1

    def test_an_offer_ending_today_is_still_live(self, client, variant):
        _offer(variant, start=date.today() - timedelta(days=5), end=date.today())
        assert len(client.get("/api/offers").get_json()) == 1

    def test_a_scheduled_offer_is_not_listed_yet(self, client, variant):
        _offer(
            variant,
            start=date.today() + timedelta(days=1),
            end=date.today() + timedelta(days=8),
        )
        assert client.get("/api/offers").get_json() == []

    def test_an_expired_offer_is_gone(self, client, variant):
        _offer(
            variant,
            start=date.today() - timedelta(days=10),
            end=date.today() - timedelta(days=1),
        )
        assert client.get("/api/offers").get_json() == []

    def test_a_deactivated_offer_is_hidden_even_inside_its_dates(self, client, variant):
        _offer(
            variant,
            start=date.today() - timedelta(days=1),
            end=date.today() + timedelta(days=5),
            is_active=False,
        )
        assert client.get("/api/offers").get_json() == []

    def test_no_offers_at_all_is_an_empty_list(self, client, service, variant):
        r = client.get("/api/offers")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_offers_are_ordered_by_how_soon_they_end(self, client, variant):
        _offer(
            variant,
            start=date.today(),
            end=date.today() + timedelta(days=30),
            title_en="Later",
        )
        _offer(
            variant,
            start=date.today(),
            end=date.today() + timedelta(days=2),
            title_en="Sooner",
        )

        titles = [o["title_en"] for o in client.get("/api/offers").get_json()]
        assert titles == ["Sooner", "Later"]


class TestPublicOffersBookability:
    """An offer must never advertise something nobody can book, so the same
    visibility rules /api/services applies are applied to its brands."""

    def _live(self, variant, **kwargs):
        return _offer(
            variant,
            start=date.today() - timedelta(days=1),
            end=date.today() + timedelta(days=5),
            **kwargs,
        )

    def test_a_withdrawn_brand_is_dropped_from_the_offer(self, client, service, variant):
        # A second brand keeps the offer alive so this tests the item filter
        # rather than the empty-offer rule below.
        other = _variant(service)
        offer = self._live(variant, item_active=False)
        db.session.add(OfferItem(
            offer_id=offer.id, service_variant_id=other.id, offer_price_syp=500000,
        ))
        db.session.commit()

        body = client.get("/api/offers").get_json()
        assert len(body) == 1
        assert [i["service_variant_id"] for i in body[0]["items"]] == [other.id]

    def test_an_offer_with_every_brand_withdrawn_is_omitted(self, client, variant):
        self._live(variant, item_active=False)
        assert client.get("/api/offers").get_json() == []

    def test_an_unavailable_brand_is_dropped(self, client, variant):
        self._live(variant)
        variant.is_available = False
        db.session.commit()

        assert client.get("/api/offers").get_json() == []

    def test_a_hidden_service_takes_its_brands_out_of_the_offer(
        self, client, service, variant
    ):
        self._live(variant)
        service.is_available = False
        db.session.commit()

        assert client.get("/api/offers").get_json() == []
