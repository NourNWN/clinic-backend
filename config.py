import os

from dotenv import load_dotenv

load_dotenv()  # يقرأ ملف .env ويحمّله كمتغيرات بيئة

# The value this app used to fall back to when SECRET_KEY was unset. It is
# public knowledge — it sat in this file in every clone of the repository —
# so anyone who knows it can forge an admin token for any deployment still
# running with it. Rejected by name rather than merely un-defaulted, so an
# older .env carrying it over fails loudly instead of looking configured.
INSECURE_SECRET_KEY = "dev-secret-change-me"

# Where the browser-facing site runs during local development. Only used
# when CORS_ORIGINS is unset; a deployment is expected to name its own.
DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def _split_origins(raw):
    """Parse the comma-separated CORS_ORIGINS variable into a tuple."""
    if not raw:
        return DEFAULT_CORS_ORIGINS
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY")
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

    # Which origins may call this API from a browser. Previously every
    # origin could, which let any page on the internet drive the API with a
    # visitor's browser.
    CORS_ORIGINS = _split_origins(os.environ.get("CORS_ORIGINS"))


def validate(config):
    """
    Fail startup on a configuration that would be unsafe or broken in a
    deployment, rather than booting and misbehaving later.

    Called from `create_app`, so the error surfaces as a clean startup
    failure naming the variable to set — not as a forged-token incident
    months later, or a 500 on the first database query.
    """
    secret = config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not set. Admin session tokens are signed with it, "
            "so an unset key means anyone can forge one. Generate a value "
            "with `python -c \"import secrets; print(secrets.token_hex(32))\"` "
            "and put it in .env (or the deployment's environment)."
        )
    if secret == INSECURE_SECRET_KEY:
        raise RuntimeError(
            f"SECRET_KEY is still the placeholder {INSECURE_SECRET_KEY!r}, "
            "which is published in this repository's history — admin tokens "
            "signed with it can be forged by anyone. Replace it with a real "
            "random value."
        )

    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill in "
            "your PostgreSQL connection details."
        )
