import logging
import secrets

from app.core.config import Settings

logger = logging.getLogger(__name__)


class InsecureConfigurationError(RuntimeError):
    """Raised at startup when the security configuration is unsafe."""


def api_key_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison of the provided API key against the expected one."""
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def validate_security_settings(cfg: Settings) -> None:
    """Fail fast when the API would run unauthenticated outside debug mode."""
    if cfg.api_key:
        return
    if cfg.debug:
        logger.warning("API_KEY not set — API is unauthenticated (debug mode)")
        return
    raise InsecureConfigurationError(
        "API_KEY is empty and DEBUG is false: refusing to start an unauthenticated API. "
        "Set API_KEY to a secret value (or DEBUG=true for local development only)."
    )
