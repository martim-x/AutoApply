"""Remote interactive browser session via CDP screencast (headless-friendly)."""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.enums import JobStatus
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.launch import (
    browser_context_kwargs,
    launch_chromium,
    user_facing_browser_error,
)
from app.infrastructure.browser.workspace import (
    browser_slot_key,
    normalize_workspace,
    storage_state_path,
)
from app.infrastructure.settings import Settings

log = logging.getLogger(__name__)

VIEWPORT = {"width": 1280, "height": 900}


@dataclass
class SessionInfo:
    profile: str
    running: bool
    url: str = ""
    error: str = ""
    workspace: str = "hh"


class RemoteBrowserSession:
    """One Playwright Chromium + CDP screencast for a profile×workspace (own thread)."""

    def __init__(
        self,
        profile: str,
        uow: UnitOfWork,
        settings: Settings,
        *,
        start_url: str | None = None,
        state_path: Path | None = None,
        workspace: str = "hh",
    ) -> None:
        self.profile = profile
        self.uow = uow
        self.settings = settings
        self.workspace = normalize_workspace(workspace)
        self.state_path_override = Path(state_path) if state_path else None
        if start_url:
            self.start_url = start_url
        elif self.workspace == "linkedin":
            from app.domain.linkedin_profile import LINKEDIN_LOGIN

            self.start_url = LINKEDIN_LOGIN
        else:
            from app.domain.launch_profile import load_launch_profile

            launch = load_launch_profile(settings.launch_path)
            base = launch.base_url if launch else settings.base_url
            self.start_url = f"{base}/account/login"
        self.cmd_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.frame_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: str | None = None
        self._url = ""
        self._thread = threading.Thread(
            target=self._run,
            name=f"remote-browser-{profile}-{self.workspace}",
            daemon=True,
        )
        self._cdp: Any = None
        self._page: Any = None
        self._context: Any = None
        self._browser: Any = None
        self._saved = False

    def resolved_state_path(self) -> Path:
        if self.state_path_override is not None:
            return Path(self.state_path_override)
        return storage_state_path(self.settings, self.profile, self.workspace)

    def start(self) -> None:
        self._thread.start()

    def wait_ready(self, timeout: float = 45.0) -> bool:
        return self._ready.wait(timeout)

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    @property
    def url(self) -> str:
        return self._url

    def stop(self, *, save: bool = False) -> None:
        if save:
            self.cmd_queue.put({"type": "save"})
        self.cmd_queue.put({"type": "stop"})
        self._stop.set()

    def request_save(self) -> None:
        self.cmd_queue.put({"type": "save"})

    def push_cmd(self, cmd: dict[str, Any]) -> None:
        if self.alive:
            self.cmd_queue.put(cmd)

    def get_frame(self, timeout: float = 0.5) -> dict[str, Any] | None:
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def join(self, timeout: float | None = 15.0) -> None:
        self._thread.join(timeout=timeout)

    def info(self) -> SessionInfo:
        return SessionInfo(
            profile=self.profile,
            running=self.alive,
            url=self._url,
            error=self._error or "",
            workspace=self.workspace,
        )

    def _run(self) -> None:
        from playwright.sync_api import sync_playwright

        s = self.settings
        uow = self.uow
        profile = self.profile
        uow.jobs.set_status(
            profile,
            JobStatus.LOGGING_IN,
            "Remote browser: открывается сессия…",
        )
        uow.journal.log(
            profile, "remote_browser_start", self.start_url, service=self.workspace
        )

        try:
            with sync_playwright() as p:
                browser, context, sp = self._launch(p, profile)
                self._browser = browser
                self._context = context
                page = context.new_page()
                self._page = page
                page.goto(self.start_url, wait_until="domcontentloaded")
                self._url = page.url or self.start_url

                cdp = context.new_cdp_session(page)
                self._cdp = cdp
                cdp.on("Page.screencastFrame", self._on_frame)
                cdp.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": s.remote_browser_jpeg_quality,
                        "maxWidth": VIEWPORT["width"],
                        "maxHeight": VIEWPORT["height"],
                        "everyNthFrame": max(1, s.remote_browser_every_nth_frame),
                    },
                )

                uow.jobs.set_status(
                    profile,
                    JobStatus.WAITING_USER,
                    "Remote browser: войдите в аккаунт в окне UI, затем «Сессия сохранена»",
                )
                self._ready.set()

                while not self._stop.is_set():
                    try:
                        cmd = self.cmd_queue.get(timeout=0.05)
                    except queue.Empty:
                        try:
                            self._url = page.url or self._url
                        except Exception:
                            pass
                        continue
                    if not self._handle_cmd(page, context, sp, cmd):
                        break

                try:
                    cdp.send("Page.stopScreencast")
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            self._error = user_facing_browser_error(e)
            log.exception("remote browser failed for %s", profile)
            short = self._error
            uow.journal.log(
                profile,
                "remote_browser_error",
                short,
                level="error",
                payload={"tb": traceback.format_exc()[-2000:], "raw": str(e)[:2000]},
                service=self.workspace,
            )
            uow.jobs.set_status(profile, JobStatus.ERROR, f"Remote browser: {short}")
            self._ready.set()
            return

        if self._saved:
            uow.jobs.set_status(
                profile,
                JobStatus.DONE,
                f"Сессия сохранена (remote): {self.resolved_state_path().name}",
            )
        else:
            uow.jobs.set_status(profile, JobStatus.IDLE, "Remote browser закрыт")
        uow.journal.log(
            profile,
            "remote_browser_stop",
            "сессия завершена",
            service=self.workspace,
        )

    def _on_frame(self, params: dict[str, Any]) -> None:
        sid = params.get("sessionId")
        if self._cdp is not None and sid is not None:
            try:
                self._cdp.send("Page.screencastFrameAck", {"sessionId": sid})
            except Exception:
                pass
        frame = {
            "type": "frame",
            "data": params.get("data", ""),
            "metadata": params.get("metadata") or {},
            "url": self._url,
        }
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frame_queue.put_nowait(frame)
            except queue.Full:
                pass

    def _handle_cmd(self, page, context, sp, cmd: dict[str, Any]) -> bool:
        """Return False to exit loop."""
        kind = cmd.get("type")
        if kind == "stop":
            return False
        if kind == "save":
            try:
                context.storage_state(path=str(sp))
                # HH session is tracked on profiles; LinkedIn uses a separate file
                if self.workspace != "linkedin":
                    self.uow.profiles.save_session(self.profile, sp)
                self._saved = True
                event = (
                    "linkedin_session_saved"
                    if self.workspace == "linkedin"
                    else "session_saved"
                )
                self.uow.journal.log(
                    self.profile, event, f"Сессия → {sp}", service=self.workspace
                )
                self.uow.jobs.set_status(
                    self.profile,
                    JobStatus.WAITING_USER,
                    f"Сессия сохранена: {sp.name}. Можно закрыть remote browser.",
                )
            except Exception as e:
                self.uow.journal.log(
                    self.profile,
                    "session_save_fail",
                    str(e),
                    level="error",
                    service=self.workspace,
                )
            return True
        if kind == "navigate":
            url = cmd.get("url") or self.start_url
            try:
                page.goto(url, wait_until="domcontentloaded")
                self._url = page.url or url
            except Exception as e:
                log.warning("navigate failed: %s", e)
            return True
        if kind == "mouse":
            self._mouse(page, cmd)
            return True
        if kind == "key":
            self._key(page, cmd)
            return True
        return True

    @staticmethod
    def _mouse(page, cmd: dict[str, Any]) -> None:
        event = cmd.get("event") or "move"
        x = float(cmd.get("x", 0))
        y = float(cmd.get("y", 0))
        button = cmd.get("button") or "left"
        try:
            if event == "move":
                page.mouse.move(x, y)
            elif event == "down":
                page.mouse.move(x, y)
                page.mouse.down(button=button)
            elif event == "up":
                page.mouse.move(x, y)
                page.mouse.up(button=button)
            elif event == "click":
                page.mouse.click(
                    x,
                    y,
                    button=button,
                    click_count=int(cmd.get("clickCount") or 1),
                )
            elif event == "dblclick":
                page.mouse.dblclick(x, y, button=button)
            elif event == "wheel":
                page.mouse.move(x, y)
                page.mouse.wheel(
                    float(cmd.get("deltaX") or 0),
                    float(cmd.get("deltaY") or 0),
                )
        except Exception as e:
            log.debug("mouse cmd failed: %s", e)

    @staticmethod
    def _key(page, cmd: dict[str, Any]) -> None:
        event = cmd.get("event") or "press"
        try:
            if event == "type":
                text = cmd.get("text") or ""
                if text:
                    page.keyboard.type(text, delay=0)
            elif event == "down":
                page.keyboard.down(cmd.get("key") or "")
            elif event == "up":
                page.keyboard.up(cmd.get("key") or "")
            else:
                key = cmd.get("key") or ""
                if key:
                    page.keyboard.press(key)
        except Exception as e:
            log.debug("key cmd failed: %s", e)

    def _launch(self, p, profile: str):
        s = self.settings
        sp = self.resolved_state_path()
        kwargs = browser_context_kwargs(
            s,
            locale="en-US" if self.workspace == "linkedin" else "ru-RU",
            viewport=dict(VIEWPORT),
        )
        browser = launch_chromium(p, headless=s.effective_headless())
        if sp.exists():
            context = browser.new_context(storage_state=str(sp), **kwargs)
        else:
            context = browser.new_context(**kwargs)
        context.set_default_navigation_timeout(s.navigation_timeout_ms)
        context.set_default_timeout(s.content_timeout_ms)
        return browser, context, sp


class RemoteBrowserManager:
    """Process-wide registry: up to one remote Chromium per profile×workspace."""

    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings
        self._lock = threading.Lock()
        self._sessions: dict[str, RemoteBrowserSession] = {}

    def enabled(self) -> bool:
        return bool(self.settings.enable_remote_browser)

    def get(
        self, profile: str, workspace: str = "hh"
    ) -> RemoteBrowserSession | None:
        key = browser_slot_key(profile, workspace)
        with self._lock:
            sess = self._sessions.get(key)
            if sess and not sess.alive:
                self._sessions.pop(key, None)
                return None
            return sess

    def any_running(self, profile: str) -> bool:
        profile = (profile or "default").strip() or "default"
        with self._lock:
            dead: list[str] = []
            found = False
            for key, sess in self._sessions.items():
                if not key.startswith(f"{profile}:"):
                    continue
                if sess.alive:
                    found = True
                else:
                    dead.append(key)
            for key in dead:
                self._sessions.pop(key, None)
            return found

    def start(
        self,
        profile: str,
        *,
        start_url: str | None = None,
        workspace: str = "hh",
        state_path: Path | None = None,
    ) -> dict[str, Any]:
        if not self.enabled():
            return {
                "ok": False,
                "error": "remote browser disabled (set ENABLE_REMOTE_BROWSER=true)",
            }
        profile = (profile or "default").strip() or "default"
        workspace = normalize_workspace(workspace)
        key = browser_slot_key(profile, workspace)
        with self._lock:
            existing = self._sessions.get(key)
            if existing and existing.alive:
                return {
                    "ok": True,
                    "message": "already running",
                    "profile": profile,
                    "workspace": workspace,
                    "viewport": VIEWPORT,
                    "url": existing.url,
                    "ws_path": (
                        f"/api/remote-browser/ws?profile={profile}"
                        f"&workspace={workspace}"
                    ),
                }
            self.uow.profiles.ensure_profile(profile)
            sess = RemoteBrowserSession(
                profile,
                self.uow,
                self.settings,
                start_url=start_url,
                state_path=state_path,
                workspace=workspace,
            )
            self._sessions[key] = sess
            sess.start()

        if not sess.wait_ready(timeout=60.0):
            sess.stop()
            with self._lock:
                self._sessions.pop(key, None)
            return {"ok": False, "error": "browser start timeout"}
        if sess.error:
            with self._lock:
                self._sessions.pop(key, None)
            return {"ok": False, "error": sess.error}
        return {
            "ok": True,
            "message": "remote browser started",
            "profile": profile,
            "viewport": VIEWPORT,
            "url": sess.url,
            "ws_path": (
                f"/api/remote-browser/ws?profile={profile}&workspace={workspace}"
            ),
            "workspace": workspace,
        }

    def save(self, profile: str, *, workspace: str = "hh") -> dict[str, Any]:
        workspace = normalize_workspace(workspace)
        sess = self.get(profile, workspace)
        if not sess:
            sp = storage_state_path(self.settings, profile, workspace)
            if sp.exists():
                if workspace != "linkedin":
                    self.uow.profiles.save_session(profile, sp)
                return {"ok": True, "message": "session file already on disk"}
            return {"ok": False, "error": "remote browser not running"}
        sess.request_save()
        time.sleep(0.3)
        return {"ok": True, "message": "save requested", "workspace": workspace}

    def stop(
        self,
        profile: str,
        *,
        save: bool = True,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Stop one workspace session, or all for profile when workspace is None."""
        profile = (profile or "default").strip() or "default"
        stopped: list[str] = []
        with self._lock:
            if workspace is None:
                keys = [
                    k
                    for k in list(self._sessions)
                    if k.startswith(f"{profile}:")
                ]
            else:
                keys = [browser_slot_key(profile, workspace)]
            sessions = []
            for key in keys:
                sess = self._sessions.pop(key, None)
                if sess:
                    sessions.append(sess)
        for sess in sessions:
            sess.stop(save=save)
            sess.join(timeout=20.0)
            stopped.append(sess.workspace)
        if not stopped:
            return {"ok": True, "message": "nothing to stop"}
        return {
            "ok": True,
            "message": "stopped",
            "workspaces": stopped,
        }

    def status(self, profile: str, *, workspace: str = "hh") -> dict[str, Any]:
        workspace = normalize_workspace(workspace)
        sess = self.get(profile, workspace)
        if not sess:
            return {
                "enabled": self.enabled(),
                "running": False,
                "profile": profile,
                "workspace": workspace,
                "viewport": VIEWPORT,
            }
        info = sess.info()
        return {
            "enabled": self.enabled(),
            "running": info.running,
            "profile": info.profile,
            "workspace": info.workspace,
            "url": info.url,
            "error": info.error,
            "viewport": VIEWPORT,
        }

    def status_all(self, profile: str) -> dict[str, Any]:
        return {
            "enabled": self.enabled(),
            "hh": self.status(profile, workspace="hh"),
            "linkedin": self.status(profile, workspace="linkedin"),
        }
