"""Public (unauthenticated) service listing/detail visibility rules."""
from app.extensions import db
from app.models import ServiceVariant


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
