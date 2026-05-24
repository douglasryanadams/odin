"""Odin web application entry point.

`odin.main:app` is what gunicorn (prod) and uvicorn (dev) target in the
Dockerfile. The FastAPI instance lives in `odin.app`; importing
`odin.routes` registers every router module against it.
"""

from odin import routes  # noqa: F401  # pyright: ignore[reportUnusedImport]
from odin.app import app

__all__ = ["app"]
