"""Remote browser settings / public config flag."""

from app.infrastructure.settings import Settings


def test_remote_browser_defaults_off():
    s = Settings(
        _env_file=None,
        enable_remote_browser=False,
        data_dir="/tmp/autoapply-test-data",
    )
    assert s.enable_remote_browser is False
    assert 1 <= s.remote_browser_jpeg_quality <= 100
    assert s.remote_browser_every_nth_frame >= 1


def test_remote_browser_env_toggle(monkeypatch):
    monkeypatch.setenv("ENABLE_REMOTE_BROWSER", "true")
    monkeypatch.setenv("REMOTE_BROWSER_JPEG_QUALITY", "40")
    s = Settings(
        _env_file=None,
        data_dir="/tmp/autoapply-test-data",
    )
    assert s.enable_remote_browser is True
    assert s.remote_browser_jpeg_quality == 40
