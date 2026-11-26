from app.core.config import Settings


def test_settings_load_without_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    s = Settings(_env_file=None)
    assert not hasattr(s, "secret_key")


def test_settings_ignore_legacy_secret_key_in_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=legacy\nDEBUG=true\n")
    s = Settings(_env_file=str(env))
    assert s.debug is True


def test_default_gemini_model_is_not_retired():
    assert Settings(_env_file=None).gemini_model != "gemini-2.0-flash-lite"
