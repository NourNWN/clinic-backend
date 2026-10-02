"""
Startup guards on configuration.

A deployment that boots with no SECRET_KEY, or with the placeholder that
used to ship as the fallback, signs admin tokens with a key an outsider
knows — so it must not boot at all.
"""

import pytest

import config as config_module


def _config(**overrides):
    base = {
        "SECRET_KEY": "a-real-random-value",
        "SQLALCHEMY_DATABASE_URI": "postgresql://user:pass@localhost/db",
    }
    base.update(overrides)
    return base


class TestValidate:
    def test_a_complete_configuration_passes(self):
        config_module.validate(_config())

    @pytest.mark.parametrize("missing", [None, ""])
    def test_missing_secret_key_is_rejected(self, missing):
        with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
            config_module.validate(_config(SECRET_KEY=missing))

    def test_the_old_placeholder_secret_key_is_rejected_by_name(self):
        with pytest.raises(RuntimeError, match="placeholder"):
            config_module.validate(
                _config(SECRET_KEY=config_module.INSECURE_SECRET_KEY)
            )

    def test_missing_database_url_is_rejected(self):
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            config_module.validate(_config(SQLALCHEMY_DATABASE_URI=None))


class TestCorsOrigins:
    def test_unset_falls_back_to_local_development(self):
        assert config_module._split_origins(None) == config_module.DEFAULT_CORS_ORIGINS
        assert config_module._split_origins("") == config_module.DEFAULT_CORS_ORIGINS

    def test_a_comma_separated_list_is_split_and_stripped(self):
        assert config_module._split_origins(
            "https://clinic.example.com, https://www.clinic.example.com"
        ) == ("https://clinic.example.com", "https://www.clinic.example.com")

    def test_blank_entries_are_dropped(self):
        assert config_module._split_origins("https://a.example, ,https://b.example") == (
            "https://a.example",
            "https://b.example",
        )
