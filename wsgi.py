"""
Production entry point.

`run.py` starts Flask's development server with `debug=True`, which serves
the Werkzeug interactive debugger — a remote code execution hole the moment
it is reachable from the internet. It stays as-is for local development;
anything public is served through this module instead, by a real WSGI
server:

    gunicorn --bind 0.0.0.0:$PORT wsgi:app

There is no `app.run()` here on purpose. This file is imported by the WSGI
server, never executed, so no accidental `python wsgi.py` can put the
development server back in front of real traffic.
"""

from app import create_app
from app import models  # noqa: F401  — registers the models with SQLAlchemy

app = create_app()
