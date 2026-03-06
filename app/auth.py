"""Google OAuth configuration."""
import os

from starlette.config import Config
from authlib.integrations.starlette_client import OAuth

config = Config()  # reads from environment variables
oauth = OAuth(config)


def configure_oauth():
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email"},
    )


def get_allowed_emails() -> set[str]:
    raw = os.environ.get("ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}
