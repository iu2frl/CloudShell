"""
tests/test_config.py - tests for startup configuration guards.
"""

import pytest

from backend.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_SECRET_KEY, get_settings


def test_non_dev_environment_rejects_default_secret_key(monkeypatch):
    """Non-development environments must reject default SECRET_KEY."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)

    with pytest.raises(ValueError, match="default SECRET_KEY"):
        get_settings()

    get_settings.cache_clear()


def test_development_environment_allows_default_secret_key(monkeypatch):
    """Development environment may use default SECRET_KEY for local setup."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)

    settings = get_settings()
    assert settings.secret_key == DEFAULT_SECRET_KEY

    get_settings.cache_clear()


def test_non_dev_environment_accepts_custom_secret_key(monkeypatch):
    """Non-development environments should start with custom SECRET_KEY."""
    custom_secret = "strong-custom-secret-key-for-prod"

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("SECRET_KEY", custom_secret)

    settings = get_settings()
    assert settings.secret_key == custom_secret

    get_settings.cache_clear()


def test_empty_secret_key_is_rejected(monkeypatch):
    """Any environment must reject empty SECRET_KEY."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "")

    with pytest.raises(ValueError, match="SECRET_KEY must be non-empty"):
        get_settings()

    get_settings.cache_clear()


def test_non_dev_environment_rejects_default_admin_password(monkeypatch):
    """Non-development environments must reject default ADMIN_PASSWORD."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "strong-secret-for-prod")
    monkeypatch.setenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    with pytest.raises(ValueError, match="default ADMIN_PASSWORD"):
        get_settings()

    get_settings.cache_clear()


def test_development_environment_allows_default_admin_password(monkeypatch):
    """Development environment may use default ADMIN_PASSWORD for local setup."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    monkeypatch.setenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    settings = get_settings()
    assert settings.admin_password == DEFAULT_ADMIN_PASSWORD

    get_settings.cache_clear()


def test_empty_admin_password_is_rejected(monkeypatch):
    """Any environment must reject empty ADMIN_PASSWORD."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    monkeypatch.setenv("ADMIN_PASSWORD", "")

    with pytest.raises(ValueError, match="ADMIN_PASSWORD must be non-empty"):
        get_settings()

    get_settings.cache_clear()
