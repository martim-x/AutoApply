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


def test_effective_headless_forced_by_remote_browser():
    """Docker/Railway: remote on + HEADLESS=false must still launch headless."""
    s = Settings(
        _env_file=None,
        headless=False,
        enable_remote_browser=True,
        data_dir="/tmp/autoapply-test-data",
    )
    assert s.effective_headless() is True


def test_effective_headless_respects_explicit_false():
    s = Settings(
        _env_file=None,
        headless=False,
        enable_remote_browser=False,
        data_dir="/tmp/autoapply-test-data",
    )
    assert s.effective_headless() is False


def test_user_facing_browser_error_shortens_xserver_dump():
    from app.infrastructure.browser.launch import user_facing_browser_error

    raw = (
        "Failed to launch Chromium.\n"
        "{'headless': False}: BrowserType.launch: Target page closed\n"
        "Looks like you launched a headed browser without having a XServer running.\n"
        + ("x" * 2000)
    )
    msg = user_facing_browser_error(RuntimeError(raw))
    assert "дисплея" in msg or "HEADLESS" in msg
    assert len(msg) < 300
    assert "xxxx" not in msg


def test_user_facing_browser_error_platform_init_without_dump():
    from app.infrastructure.browser.launch import user_facing_browser_error

    raw = (
        "Failed to launch Chromium. {'headless': False}: "
        "BrowserType.launch: Target page, context or browser has been closed\n"
        "The platform failed to initialize\n"
        + ("stack" * 400)
    )
    msg = user_facing_browser_error(RuntimeError(raw))
    assert "дисплея" in msg or "HEADLESS" in msg
    assert len(msg) < 300
    assert "stackstack" not in msg
    assert "{'headless'" not in msg
