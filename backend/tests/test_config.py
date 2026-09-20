import pytest
from pydantic import ValidationError

from backend.config import Settings


def settings(**values):
    return Settings(_env_file=None, database_url="sqlite://", **values)


def test_all_environments_require_an_explicit_secret():
    with pytest.raises(ValidationError, match="non-placeholder"):
        settings(app_env="development", jwt_secret=None)


def test_development_accepts_explicit_local_secret():
    configured = settings(
        app_env="development",
        jwt_secret="local-random-secret-value-for-tests-123456",
    )

    assert configured.jwt_secret == "local-random-secret-value-for-tests-123456"


def test_development_rejects_known_placeholder_secret():
    with pytest.raises(ValidationError, match="non-placeholder"):
        settings(
            app_env="development",
            jwt_secret="development-only-secret-change-me-now",
        )


@pytest.mark.parametrize(
    "secret",
    [
        None,
        "short",
        "replace-with-a-long-random-production-secret",
        "development-only-secret-change-me-now",
    ],
)
def test_production_rejects_missing_or_placeholder_secret(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        settings(app_env="production", jwt_secret=secret)


def test_production_accepts_explicit_high_entropy_secret():
    configured = settings(
        app_env="production",
        jwt_secret="v3ry-long-random-looking-production-value-91!",
    )

    assert configured.app_env == "production"


def test_app_env_rejects_unknown_values():
    with pytest.raises(ValidationError):
        settings(app_env="prod", jwt_secret="x" * 40)
