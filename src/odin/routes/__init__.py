"""Route registration. Importing this package wires every router into `odin.app.app`."""

from odin.app import app
from odin.routes import account, auth, pages, profile

app.include_router(pages.router)
app.include_router(profile.router)
app.include_router(auth.router)
app.include_router(account.router)

__all__ = ["account", "auth", "pages", "profile"]
