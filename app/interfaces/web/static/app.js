(() => {
  const $ = (id) => document.getElementById(id);
  const t = (key, vars) => (window.AA_I18N ? window.AA_I18N.t(key, vars) : key);
  const profileSelect = $("profileSelect");
  const statusPill = $("statusPill");
  const statusLabel = $("statusLabel");
  const statusMessage = $("statusMessage");
  const remoteModal = $("remoteModal");
  const remotePanel = remoteModal ? remoteModal.querySelector(".remote-panel") : null;
  const remoteCanvas = $("remoteCanvas");
  const remoteOverlay = $("remoteOverlay");
  const remoteUrl = $("remoteUrl");
  const btnRemoteFullscreen = $("btnRemoteFullscreen");
  const explainModal = $("explainModal");
  const launchModal = $("launchModal");
  const ctx = remoteCanvas.getContext("2d");

  let remoteEnabled = false;
  let remoteRunning = false;
  let remoteViewerWorkspace = "hh";
  let ws = null;
  let viewport = { width: 1280, height: 900 };
  let img = new Image();
  let lastLaunch = null;
  let launchLoaded = false;
  let remoteOverlayKey = null;
  let lastStatusCode = "idle";
  let lastStatusMessage = "";
  let lastBusy = false;
  let lastBusyHh = false;
  let lastBusyLi = false;
  let lastHasSession = false;
  let lastHasLiSession = false;
  let workspace = "hh";
  let liTab = "network";
  let remoteFsDesired = false;
  let logFullscreenId = null;
  const WORKSPACE_KEY = "aa-workspace";
  const PANEL_SIZE_KEY = "aa-panel-sizes";

  function profile() {
    if (profileSelect.value) return profileSelect.value;
    if (profileSelect.options.length) return profileSelect.options[0].value;
    return "";
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("Unauthorized");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    return data;
  }

  async function post(path, body) {
    return api(path, {
      method: "POST",
      body: JSON.stringify(body || { profile: profile() }),
    });
  }

  function setBtnLabel(el, key, vars) {
    if (!el) return;
    const label = el.querySelector(".btn-label") || el;
    label.setAttribute("data-i18n", key);
    if (vars) label.setAttribute("data-i18n-vars", JSON.stringify(vars));
    else label.removeAttribute("data-i18n-vars");
    label.textContent = t(key, vars);
  }

  function limitVars() {
    const launch = lastLaunch || {};
    const searchN = Number(launch.vacancy_limit) || 30;
    const applyN = Number(launch.apply_limit) || 30;
    return { searchN, applyN };
  }

  function syncLimitsHint() {
    const el = $("hhLimitsHint");
    if (!el) return;
    const { searchN, applyN } = limitVars();
    el.textContent = t("limits.hint", { search: searchN, apply: applyN });
  }

  const MSG_MAX = 180;

  function truncateMsg(text, max) {
    const s = String(text ?? "");
    const n = max == null ? MSG_MAX : max;
    if (s.length <= n) return s;
    return s.slice(0, Math.max(0, n - 1)) + "…";
  }

  function setStatusMessage(text) {
    statusMessage.textContent = truncateMsg(text);
  }

  function setBusy(busyHh, busyLi) {
    const hhOn = busyHh == null ? false : !!busyHh;
    const liOn = busyLi == null ? false : !!busyLi;
    const hhBusyIds = ["btnLogin", "btnSearch", "btnApply", "btnLaunchCriteria"];
    hhBusyIds.forEach((id) => {
      const el = $(id);
      if (el) el.disabled = hhOn;
    });
    const liBusyIds = [
      "btnLiLogin",
      "btnLiNetwork",
      "btnLiVacancies",
      "btnLiCriteria",
    ];
    liBusyIds.forEach((id) => {
      const el = $(id);
      if (el) el.disabled = liOn;
    });
    // Stop must stay clickable while a job (or remote browser) is running.
    ["btnStop", "btnLiStop", "btnConfirm", "btnLiConfirm"].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = false;
    });
    // Remote browser stays usable while connected (open/show viewer).
    const remoteBtn = $("btnRemoteBrowser");
    if (remoteBtn) remoteBtn.disabled = false;
    const liRemoteBtn = $("btnLiRemoteBrowser");
    if (liRemoteBtn) liRemoteBtn.disabled = false;
  }

  function syncLoginLabel() {
    const loginLabel = document.querySelector("[data-label-login]");
    if (!loginLabel) return;
    loginLabel.setAttribute("data-i18n", "login.connect");
    loginLabel.textContent = t("login.connect");
  }

  function syncActionLabels(status, message, busyHh, busyLi) {
    const code = status || "idle";
    const msg = String(message || "").toLowerCase();
    const searching = code === "searching";
    const applying = code === "applying";
    const waitingUser = code === "waiting_user" || code === "logging_in";
    const liNetwork = searching && msg.includes("network");
    const liVacancies =
      searching && (msg.includes("vacanc") || msg.includes("job"));
    const effHh = !!busyHh;
    const effLi = !!busyLi;

    const { searchN, applyN } = limitVars();
    const btnSearch = $("btnSearch");
    if (btnSearch) {
      const active = searching && workspace === "hh";
      setBtnLabel(
        btnSearch,
        active ? "search.busy" : "search",
        { n: searchN }
      );
      btnSearch.classList.toggle("is-busy", active);
      btnSearch.classList.remove("is-primary", "primary");
    }

    const btnApply = $("btnApply");
    if (btnApply) {
      setBtnLabel(
        btnApply,
        applying ? "apply.busy" : "apply",
        { n: applyN }
      );
      btnApply.classList.toggle("is-busy", applying);
      btnApply.classList.remove("is-primary", "primary");
    }

    syncLimitsHint();

    const btnRemote = $("btnRemoteBrowser");
    if (btnRemote) {
      const open =
        workspace === "hh" &&
        (remoteRunning ||
          (remoteModal && !remoteModal.hidden) ||
          (ws && ws.readyState === WebSocket.OPEN));
      setBtnLabel(btnRemote, open ? "remote.show" : "remote.open");
      btnRemote.classList.toggle("is-primary", !!open);
      btnRemote.classList.remove("primary");
    }
    const btnLiRemote = $("btnLiRemoteBrowser");
    if (btnLiRemote) {
      const open =
        workspace === "linkedin" &&
        (remoteRunning ||
          (remoteModal && !remoteModal.hidden) ||
          (ws && ws.readyState === WebSocket.OPEN));
      setBtnLabel(btnLiRemote, open ? "remote.show" : "remote.open");
      btnLiRemote.classList.toggle("is-primary", !!open);
      btnLiRemote.classList.remove("primary");
    }

    const btnConfirm = $("btnConfirm");
    if (btnConfirm) {
      const warn = waitingUser && workspace === "hh";
      btnConfirm.classList.remove("is-primary", "primary");
      btnConfirm.classList.toggle("is-warn", warn);
    }
    const btnLiConfirm = $("btnLiConfirm");
    if (btnLiConfirm) {
      const warn = waitingUser && workspace === "linkedin";
      btnLiConfirm.classList.remove("is-primary", "primary");
      btnLiConfirm.classList.toggle("is-warn", warn);
    }

    const btnLiNetwork = $("btnLiNetwork");
    if (btnLiNetwork) {
      setBtnLabel(
        btnLiNetwork,
        liNetwork ? "linkedin.network.busy" : "linkedin.network"
      );
      btnLiNetwork.classList.toggle("is-busy", liNetwork);
      btnLiNetwork.classList.remove("is-primary", "primary");
    }
    const btnLiVacancies = $("btnLiVacancies");
    if (btnLiVacancies) {
      setBtnLabel(
        btnLiVacancies,
        liVacancies ? "linkedin.vacancies.busy" : "linkedin.vacancies"
      );
      btnLiVacancies.classList.toggle("is-busy", liVacancies);
      btnLiVacancies.classList.remove("is-primary", "primary");
    }

    ["btnLogin", "btnLiLogin"].forEach((id) => {
      const el = $(id);
      if (el) el.classList.remove("is-primary", "primary", "is-busy");
    });

    syncLoginLabel();
    setBusy(effHh, effLi);
  }

  function syncActionLabelsCached() {
    syncActionLabels(
      lastStatusCode,
      lastStatusMessage,
      lastBusyHh,
      lastBusyLi
    );
  }

  function applyRemoteUiFlag(enabled) {
    remoteEnabled = !!enabled;
    ["btnRemoteBrowser", "btnLiRemoteBrowser"].forEach((id) => {
      const btn = $(id);
      if (btn) btn.hidden = !remoteEnabled;
    });
    syncLoginLabel();
    syncActionLabelsCached();
  }

  function sessionLooksInvalid(status, message) {
    const code = String(status || "");
    const msg = String(message || "").toLowerCase();
    if (code === "error" && /(сесс|session|login|войд|нет сесс)/i.test(msg)) {
      return true;
    }
    return /(session_lost|нет сессии|session expired|invalid session|сессия истек)/i.test(
      msg
    );
  }

  function updateSessionBanner(st) {
    const status = st.status || "idle";
    const message = st.message || "";
    const waiting =
      status === "waiting_user" || status === "logging_in";
    const invalid = sessionLooksInvalid(status, message);

    const hh = $("sessionBannerHh");
    const li = $("sessionBannerLi");

    function paint(el, hasSession) {
      if (!el) return;
      el.classList.remove("is-error");
      if (invalid || (status === "error" && !hasSession)) {
        el.hidden = false;
        el.classList.add("is-error");
        el.textContent = t("session.invalid");
        return;
      }
      if (waiting) {
        el.hidden = false;
        el.textContent = t("session.save.reminder");
        return;
      }
      el.hidden = true;
      el.textContent = "";
    }

    if (workspace === "linkedin") {
      if (hh) {
        hh.hidden = true;
        hh.textContent = "";
      }
      paint(li, !!st.has_linkedin_session);
    } else {
      if (li) {
        li.hidden = true;
        li.textContent = "";
      }
      paint(hh, !!st.has_session);
    }
  }

  function setReportMenuOpen(open) {
    const btn = $("btnDownloadReport");
    const panel = $("reportMenuPanel");
    if (!btn || !panel) return;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function downloadReport(kind) {
    const k = kind === "linkedin" ? "linkedin" : "work";
    const url =
      `/api/reports/${encodeURIComponent(k)}.pdf` +
      `?profile=${encodeURIComponent(profile())}`;
    window.location.href = url;
    setReportMenuOpen(false);
  }

  function initReportMenu() {
    const btn = $("btnDownloadReport");
    const panel = $("reportMenuPanel");
    if (!btn || !panel) return;
    btn.onclick = (e) => {
      e.stopPropagation();
      setReportMenuOpen(panel.hidden);
    };
    panel.querySelectorAll("[data-report-kind]").forEach((item) => {
      item.onclick = (e) => {
        e.stopPropagation();
        downloadReport(item.getAttribute("data-report-kind"));
      };
    });
    document.addEventListener("click", (e) => {
      const menu = $("reportMenu");
      if (!menu || menu.contains(e.target)) return;
      setReportMenuOpen(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") setReportMenuOpen(false);
    });
  }

  function statusDisplay(code) {
    const key = `status.${code}`;
    const translated = t(key);
    return translated === key ? code : translated;
  }

  function setRemoteOverlay(keyOrText, isKey) {
    if (isKey) {
      remoteOverlayKey = keyOrText;
      remoteOverlay.textContent = t(keyOrText);
      remoteOverlay.removeAttribute("data-i18n");
    } else {
      remoteOverlayKey = null;
      remoteOverlay.textContent = keyOrText;
      remoteOverlay.removeAttribute("data-i18n");
    }
  }

  const THEME_KEY = "aa-theme";

  function systemPrefersDark() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function resolveTheme(pref) {
    // "system" follows the device/OS preference — not a third palette.
    if (pref === "light" || pref === "dark") return pref;
    return systemPrefersDark() ? "dark" : "light";
  }

  function syncThemeButtons(pref) {
    document.querySelectorAll("[data-theme-set]").forEach((btn) => {
      btn.setAttribute(
        "aria-pressed",
        btn.getAttribute("data-theme-set") === pref ? "true" : "false"
      );
    });
  }

  function applyTheme(pref) {
    const mode = pref === "light" || pref === "dark" || pref === "system"
      ? pref
      : "system";
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch (e) {}
    document.documentElement.setAttribute("data-theme-pref", mode);
    document.documentElement.setAttribute("data-theme", resolveTheme(mode));
    syncThemeButtons(mode);
  }

  function initTheme() {
    let pref = "system";
    try {
      pref = localStorage.getItem(THEME_KEY) || "system";
    } catch (e) {}
    applyTheme(pref);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemSchemeChange = () => {
      const current =
        document.documentElement.getAttribute("data-theme-pref") || "system";
      if (current !== "system") return;
      document.documentElement.setAttribute(
        "data-theme",
        systemPrefersDark() ? "dark" : "light"
      );
    };
    if (mq.addEventListener) mq.addEventListener("change", onSystemSchemeChange);
    else if (mq.addListener) mq.addListener(onSystemSchemeChange);
    document.querySelectorAll("[data-theme-set]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyTheme(btn.getAttribute("data-theme-set"));
      });
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function highlightLogMessage(msg) {
    let s = escapeHtml(msg || "");
    s = s.replace(/\b(filtered:[a-z_]+)\b/gi, '<span class="filter">$1</span>');
    s = s.replace(/\bHIGH\b/g, '<span class="cat-HIGH">HIGH</span>');
    s = s.replace(/\bMEDIUM\b/g, '<span class="cat-MEDIUM">MEDIUM</span>');
    s = s.replace(/\bLOW\b/g, '<span class="cat-LOW">LOW</span>');
    s = s.replace(/\b(score[=:]?\s*\d+)\b/gi, '<span class="score">$1</span>');
    s = s.replace(/\b(applied|queued|skipped|dry_run|ok)\b/gi, '<span class="ok">$1</span>');
    s = s.replace(/\b(error[:\w.-]*)\b/gi, '<span class="err">$1</span>');
    return s;
  }

  async function refreshProfiles() {
    const data = await api("/api/profiles");
    const current = profileSelect.value;
    profileSelect.innerHTML = "";
    (data.profiles || []).forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = p.has_session ? `${p.name} ●` : p.name;
      profileSelect.appendChild(opt);
    });
    if (current && [...profileSelect.options].some((o) => o.value === current)) {
      profileSelect.value = current;
    } else if (profileSelect.options.length) {
      profileSelect.selectedIndex = 0;
    }
  }

  function showNotifications(list) {
    const bar = $("notifyBar");
    if (!bar) return;
    const items = (list || []).filter(Boolean);
    if (!items.length) {
      bar.hidden = true;
      bar.innerHTML = "";
      return;
    }
    bar.hidden = false;
    bar.innerHTML = items
      .slice(0, 6)
      .map(
        (n) =>
          `<div class="notify-item">${escapeHtml(truncateMsg(n, 200))}</div>`
      )
      .join("");
  }

  function showLastAlert(alert) {
    const el = $("lastAlertLine");
    if (!el) return;
    if (!alert || !alert.message) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    const ev = alert.event || "?";
    el.hidden = false;
    el.textContent = t("alert.last", {
      event: ev,
      message: truncateMsg(alert.message, 160),
    });
  }

  function applyWorkspace(ws) {
    workspace = ws === "linkedin" ? "linkedin" : "hh";
    try {
      localStorage.setItem(WORKSPACE_KEY, workspace);
    } catch (_) {}
    const sw = $("workspaceSwitch");
    if (sw) sw.dataset.workspace = workspace;
    const controls = $("controlsPanel");
    if (controls) controls.dataset.workspace = workspace;
    const shell = document.querySelector(".shell");
    if (shell) shell.dataset.workspace = workspace;
    document.documentElement.dataset.workspace = workspace;

    document.querySelectorAll("[data-workspace-set]").forEach((btn) => {
      btn.setAttribute(
        "aria-pressed",
        btn.getAttribute("data-workspace-set") === workspace ? "true" : "false"
      );
    });

    const isLi = workspace === "linkedin";
    document.querySelectorAll("[data-workspace-panel]").forEach((el) => {
      const pane = el.getAttribute("data-workspace-panel");
      if (!pane || pane === "shared") {
        el.hidden = false;
        return;
      }
      el.hidden = pane !== workspace;
    });

    // Nested panes: keep LI tab visibility correct after parent show.
    if ($("hhWorkspacePane")) $("hhWorkspacePane").hidden = isLi;
    if ($("liWorkspacePane")) $("liWorkspacePane").hidden = !isLi;
    if (logFullscreenId) setLogFullscreen(logFullscreenId, false);
    applyLiTab(liTab);
    syncActionLabelsCached();
  }

  function applyLiTab(tab) {
    liTab = tab === "vacancies" ? "vacancies" : "network";
    document.querySelectorAll("[data-li-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-li-tab") === liTab);
    });
    if ($("liNetworkPanel")) $("liNetworkPanel").hidden = liTab !== "network";
    if ($("liVacPanel")) $("liVacPanel").hidden = liTab !== "vacancies";
    if (logFullscreenId === "liVacPanel" && liTab !== "vacancies") {
      setLogFullscreen("liVacPanel", false);
    }
  }

  function initWorkspace() {
    let ws = "hh";
    try {
      ws = localStorage.getItem(WORKSPACE_KEY) || "hh";
    } catch (_) {}
    applyWorkspace(ws);
    document.querySelectorAll("[data-workspace-set]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyWorkspace(btn.getAttribute("data-workspace-set"));
        refreshAll();
      });
    });
    document.querySelectorAll("[data-li-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyLiTab(btn.getAttribute("data-li-tab"));
      });
    });
  }

  async function refreshStatus() {
    const st = await api(`/api/status?profile=${encodeURIComponent(profile())}`);
    const status = st.status || "idle";
    lastStatusCode = status;
    lastStatusMessage = st.message || "";
    lastBusy = !!st.busy;
    lastBusyHh = !!(st.busy_hh ?? st.busy);
    lastBusyLi = !!(st.busy_linkedin ?? st.busy);
    lastHasSession = !!st.has_session;
    lastHasLiSession = !!st.has_linkedin_session;
    statusPill.dataset.status = status;
    statusLabel.textContent = statusDisplay(status);
    setStatusMessage(st.message || "");

    const s = st.stats || {};
    $("stHigh").textContent = s.high ?? 0;
    $("stMedium").textContent = s.medium ?? 0;
    $("stLow").textContent = s.low ?? 0;
    $("stQueued").textContent = s.queued ?? 0;
    $("stApplied").textContent = s.applied ?? 0;
    $("stSession").textContent = st.has_session
      ? t("stats.session_ok")
      : t("stats.session_no");

    const li = st.linkedin_stats || {};
    const by = li.by_status || {};
    if ($("stLiContacts")) $("stLiContacts").textContent = li.total ?? 0;
    if ($("stLiConnected")) $("stLiConnected").textContent = by.connected ?? 0;
    if ($("stLiPending")) $("stLiPending").textContent = by.pending ?? 0;
    if ($("stLiVacancies")) {
      $("stLiVacancies").textContent = (li.vacancies && li.vacancies.total) || 0;
    }
    if ($("stLiSession")) {
      $("stLiSession").textContent = st.has_linkedin_session
        ? t("stats.session_ok")
        : t("stats.session_no");
    }

    if (st.notifications) showNotifications(st.notifications);
    showLastAlert(st.last_alert);
    updateSessionBanner(st);

    const remotes = st.remote_browsers || {};
    const remoteForWs =
      (workspace === "linkedin" ? remotes.linkedin : remotes.hh) ||
      st.remote_browser;
    if (remoteForWs) {
      remoteRunning = !!remoteForWs.running;
      const enabledFlag =
        typeof remotes.enabled === "boolean"
          ? remotes.enabled
          : typeof remoteForWs.enabled === "boolean"
            ? remoteForWs.enabled
            : typeof (st.remote_browser && st.remote_browser.enabled) === "boolean"
              ? st.remote_browser.enabled
              : null;
      if (enabledFlag !== null) {
        remoteEnabled = !!enabledFlag;
        ["btnRemoteBrowser", "btnLiRemoteBrowser"].forEach((id) => {
          const btn = $(id);
          if (btn) btn.hidden = !remoteEnabled;
        });
      }
    } else {
      remoteRunning = false;
    }
    syncActionLabels(status, st.message, lastBusyHh, lastBusyLi);
  }

  function explainButtonHtml(vacancyId) {
    return (
      `<button type="button" class="ghost touch btn-explain" data-vacancy-id="${vacancyId}">` +
      `<svg class="ico" aria-hidden="true"><use href="#i-spark"/></svg>` +
      `<span class="btn-label" data-i18n="vac.explain">${t("vac.explain")}</span></button>`
    );
  }

  async function refreshVacancies() {
    const data = await api(`/api/vacancies?profile=${encodeURIComponent(profile())}&limit=80`);
    const body = $("vacBody");
    const cards = $("vacCards");
    body.innerHTML = "";
    cards.innerHTML = "";
    (data.vacancies || []).forEach((v) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="cat-${v.category}">${escapeHtml(v.category)}</td>
        <td>${v.score}</td>
        <td><a href="${escapeHtml(v.url)}" target="_blank" rel="noopener">${escapeHtml(v.title || v.url)}</a></td>
        <td>${escapeHtml(v.filter_status || "")}</td>
        <td>${escapeHtml(v.apply_status || "")}</td>
        <td>${v.id != null ? explainButtonHtml(v.id) : ""}</td>`;
      body.appendChild(tr);

      const card = document.createElement("article");
      card.className = "vac-card";
      card.innerHTML = `
        <div class="vac-card-top">
          <span class="cat-${v.category}">${escapeHtml(v.category)}</span>
          <span>score ${v.score}</span>
        </div>
        <h3><a href="${escapeHtml(v.url)}" target="_blank" rel="noopener">${escapeHtml(v.title || v.url)}</a></h3>
        <div class="vac-card-meta">
          <span>${escapeHtml(v.filter_status || "")}</span>
          <span>${escapeHtml(v.apply_status || "")}</span>
        </div>
        ${v.id != null ? explainButtonHtml(v.id) : ""}`;
      cards.appendChild(card);
    });
  }

  async function refreshLogs() {
    const data = await api(
      `/api/logs?profile=${encodeURIComponent(profile())}&limit=50&service=hh`
    );
    const list = $("logList");
    list.innerHTML = "";
    (data.logs || []).forEach((l) => {
      const li = document.createElement("li");
      const lvl = (l.level || "info").toLowerCase();
      li.className = `lvl-${lvl}`;
      if (lvl === "error") li.classList.add("err");
      li.innerHTML =
        `<span class="t">${escapeHtml(l.when || "")}</span> ` +
        `<span class="ev">${escapeHtml(l.event || "")}</span> ` +
        highlightLogMessage(truncateMsg(l.message || "", 200));
      list.appendChild(li);
    });
  }

  async function openExplain(vacancyId) {
    explainModal.hidden = false;
    $("explainText").textContent = t("explain.loading");
    $("explainMeta").textContent = "";
    $("explainPos").innerHTML = "";
    $("explainNeg").innerHTML = "";
    $("explainAll").innerHTML = "";
    try {
      const data = await api(
        `/api/vacancies/explain?profile=${encodeURIComponent(profile())}&vacancy_id=${vacancyId}`
      );
      if (data.error) {
        $("explainText").textContent = truncateMsg(data.error, 200);
        return;
      }
      $("explainMeta").textContent =
        `${data.category} · score ${data.score} · weight ${data.total_weight}` +
        (data.title ? ` · ${data.title}` : "");
      $("explainText").textContent = data.explanation || "";
      const fill = (el, items, cls) => {
        el.innerHTML = "";
        (items || []).forEach((c) => {
          const li = document.createElement("li");
          li.innerHTML = `${escapeHtml(c.label)} <span class="${cls}">${c.weight > 0 ? "+" : ""}${c.weight}</span>`;
          el.appendChild(li);
        });
        if (!(items || []).length) {
          el.innerHTML = "<li>—</li>";
        }
      };
      fill($("explainPos"), data.top_positive, "w-pos");
      fill($("explainNeg"), data.top_negative, "w-neg");
      const all = $("explainAll");
      all.innerHTML = "";
      (data.contributions || []).forEach((c) => {
        const li = document.createElement("li");
        const cls = c.weight >= 0 ? "w-pos" : "w-neg";
        li.innerHTML = `${escapeHtml(c.label)} <span class="${cls}">${c.weight > 0 ? "+" : ""}${c.weight}</span>`;
        all.appendChild(li);
      });
    } catch (e) {
      $("explainText").textContent = truncateMsg(String(e.message || e), 200);
    }
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-explain");
    if (btn && btn.dataset.vacancyId) {
      openExplain(Number(btn.dataset.vacancyId));
    }
  });

  $("btnExplainClose").onclick = () => {
    explainModal.hidden = true;
  };
  explainModal.addEventListener("click", (e) => {
    if (e.target === explainModal) explainModal.hidden = true;
  });

  function setLiPanelEmpty(emptyId, tableId, isEmpty) {
    const empty = $(emptyId);
    const table = $(tableId);
    if (empty) empty.hidden = !isEmpty;
    if (table) table.hidden = !!isEmpty;
  }

  async function refreshLiContacts() {
    const data = await api(
      `/api/linkedin/contacts?profile=${encodeURIComponent(profile())}&limit=80`
    );
    const body = $("liContactBody");
    if (!body) return;
    body.innerHTML = "";
    const contacts = data.contacts || [];
    contacts.forEach((c) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(c.status || "")}</td>
        <td><a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.name || c.url)}</a></td>
        <td>${escapeHtml(c.query || "")}</td>`;
      body.appendChild(tr);
    });
    setLiPanelEmpty("liContactEmpty", "liContactTable", contacts.length === 0);
  }

  async function refreshLiVacancies() {
    const data = await api(
      `/api/linkedin/vacancies?profile=${encodeURIComponent(profile())}&limit=80`
    );
    const body = $("liVacBody");
    if (!body) return;
    body.innerHTML = "";
    const vacancies = data.vacancies || [];
    vacancies.forEach((v) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><a href="${escapeHtml(v.url)}" target="_blank" rel="noopener">${escapeHtml(v.title || v.url)}</a></td>
        <td>${escapeHtml(v.location || "")}</td>
        <td>${escapeHtml(v.query || "")}</td>`;
      body.appendChild(tr);
    });
    setLiPanelEmpty("liVacEmpty", "liVacTable", vacancies.length === 0);
  }

  async function refreshLiLogs() {
    const data = await api(
      `/api/logs?profile=${encodeURIComponent(profile())}&limit=50&service=linkedin`
    );
    const list = $("liLogList");
    if (!list) return;
    list.innerHTML = "";
    (data.logs || []).forEach((l) => {
      const li = document.createElement("li");
      const lvl = (l.level || "info").toLowerCase();
      li.className = `lvl-${lvl}`;
      if (lvl === "error") li.classList.add("err");
      li.innerHTML =
        `<span class="t">${escapeHtml(l.when || "")}</span> ` +
        `<span class="ev">${escapeHtml(l.event || "")}</span> ` +
        highlightLogMessage(truncateMsg(l.message || "", 200));
      list.appendChild(li);
    });
  }

  async function refreshAll() {
    try {
      await refreshStatus();
      if (workspace === "linkedin") {
        await Promise.all([
          refreshLiContacts(),
          refreshLiVacancies(),
          refreshLiLogs(),
        ]);
      } else {
        await Promise.all([refreshVacancies(), refreshLogs()]);
      }
    } catch (e) {
      setStatusMessage(String(e.message || e));
    }
  }

  async function withAction(fn) {
    try {
      const r = await fn();
      if (r && r.error) setStatusMessage(r.error);
      else if (r && r.message) setStatusMessage(r.message);
      await refreshAll();
      return r;
    } catch (e) {
      setStatusMessage(String(e.message || e));
      return null;
    }
  }

  async function requestStop() {
    // Stop only the current workspace so the other can keep running in parallel.
    await withAction(() =>
      post("/api/stop", { profile: profile(), workspace })
    );
    if (remoteViewerWorkspace === workspace) {
      closeRemoteModalUi();
    }
  }

  function wsUrl(wsName) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const wsVal = encodeURIComponent(wsName || workspace || "hh");
    return (
      `${proto}://${location.host}/api/remote-browser/ws` +
      `?profile=${encodeURIComponent(profile())}&workspace=${wsVal}`
    );
  }

  function syncRemoteCanvasSize() {
    const w = Math.max(1, viewport.width | 0);
    const h = Math.max(1, viewport.height | 0);
    if (remoteCanvas.width !== w) remoteCanvas.width = w;
    if (remoteCanvas.height !== h) remoteCanvas.height = h;
    remoteCanvas.style.aspectRatio = `${w} / ${h}`;
  }

  // Map pointer → remote CDP coords. Site popups (LinkedIn cards, surveys) are
  // just pixels in the JPEG screencast — no special CSS; only this transform matters.
  // Canvas element is sized with contain (max-width/max-height), so getBoundingClientRect()
  // matches the visible frame under modal scale and fullscreen.
  function scalePoint(e) {
    const rect = remoteCanvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return { x: 0, y: 0 };
    const touch =
      (e.touches && e.touches[0]) ||
      (e.changedTouches && e.changedTouches[0]) ||
      null;
    const clientX = e.clientX ?? (touch && touch.clientX) ?? 0;
    const clientY = e.clientY ?? (touch && touch.clientY) ?? 0;
    const x = ((clientX - rect.left) / rect.width) * viewport.width;
    const y = ((clientY - rect.top) / rect.height) * viewport.height;
    return {
      x: Math.max(0, Math.min(viewport.width, x)),
      y: Math.max(0, Math.min(viewport.height, y)),
    };
  }

  function isRemoteFullscreen() {
    return !!(
      remoteFsDesired ||
      (remoteModal && remoteModal.classList.contains("is-fullscreen")) ||
      (document.fullscreenElement &&
        remotePanel &&
        (document.fullscreenElement === remotePanel ||
          remotePanel.contains(document.fullscreenElement)))
    );
  }

  function syncRemoteFullscreenUi() {
    const on = isRemoteFullscreen();
    if (remoteModal) remoteModal.classList.toggle("is-fullscreen", on);
    if (!btnRemoteFullscreen) return;
    const key = on ? "remote.fullscreen_exit" : "remote.fullscreen";
    const label = t(key);
    btnRemoteFullscreen.setAttribute("data-i18n", key);
    btnRemoteFullscreen.setAttribute("title", label);
    btnRemoteFullscreen.setAttribute("aria-label", label);
    const labelEl = btnRemoteFullscreen.querySelector(".btn-label");
    if (labelEl) {
      labelEl.setAttribute("data-i18n", key);
      labelEl.textContent = label;
    }
    const useEl = $("remoteFsIconUse");
    if (useEl) useEl.setAttribute("href", on ? "#i-compress" : "#i-expand");
  }

  async function enterRemoteFullscreen() {
    remoteFsDesired = true;
    if (remoteModal) remoteModal.classList.add("is-fullscreen");
    syncRemoteFullscreenUi();
    if (remotePanel && remotePanel.requestFullscreen && !document.fullscreenElement) {
      try {
        await remotePanel.requestFullscreen();
      } catch (_) {
        /* CSS is-fullscreen already expands the panel */
      }
    }
    remoteCanvas.focus();
  }

  async function exitRemoteFullscreen() {
    remoteFsDesired = false;
    if (remoteModal) remoteModal.classList.remove("is-fullscreen");
    if (document.fullscreenElement) {
      try {
        await document.exitFullscreen();
      } catch (_) {}
    }
    syncRemoteFullscreenUi();
  }

  async function toggleRemoteFullscreen() {
    if (isRemoteFullscreen()) await exitRemoteFullscreen();
    else await enterRemoteFullscreen();
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  function mapKey(e) {
    const special = {
      Enter: "Enter",
      Backspace: "Backspace",
      Tab: "Tab",
      Escape: "Escape",
      ArrowLeft: "ArrowLeft",
      ArrowRight: "ArrowRight",
      ArrowUp: "ArrowUp",
      ArrowDown: "ArrowDown",
      Delete: "Delete",
      Home: "Home",
      End: "End",
      PageUp: "PageUp",
      PageDown: "PageDown",
    };
    if (special[e.key]) return special[e.key];
    if (e.key === " ") return "Space";
    return e.key;
  }

  function openRemoteModal() {
    remoteModal.hidden = false;
    remoteOverlay.hidden = false;
    setRemoteOverlay("remote.connecting", true);
    remoteUrl.textContent = "";
    remoteFsDesired = false;
    syncRemoteFullscreenUi();
    syncActionLabelsCached();
    remoteCanvas.focus();
  }

  function closeRemoteModalUi() {
    remoteFsDesired = false;
    if (remoteModal) remoteModal.classList.remove("is-fullscreen");
    if (document.fullscreenElement) {
      try { document.exitFullscreen(); } catch (_) {}
    }
    syncRemoteFullscreenUi();
    remoteModal.hidden = true;
    if (ws) {
      try { ws.close(); } catch (_) {}
      ws = null;
    }
    syncActionLabelsCached();
  }

  async function startRemoteViewer(wsName) {
    remoteViewerWorkspace = wsName === "linkedin" ? "linkedin" : "hh";
    openRemoteModal();
    try {
      const started = await post("/api/remote-browser/start", {
        profile: profile(),
        workspace: remoteViewerWorkspace,
      });
      if (started && started.error) {
        setRemoteOverlay(truncateMsg(started.error, 200), false);
        setStatusMessage(started.error);
        return;
      }
      if (started && started.viewport) {
        viewport = started.viewport;
        syncRemoteCanvasSize();
      }
    } catch (e) {
      setRemoteOverlay(truncateMsg(String(e.message || e), 200), false);
      setStatusMessage(String(e.message || e));
      return;
    }

    if (ws) {
      try { ws.close(); } catch (_) {}
    }

    ws = new WebSocket(wsUrl(remoteViewerWorkspace));
    ws.onopen = () => {
      setRemoteOverlay("remote.waiting_frames", true);
      remoteCanvas.focus();
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.type === "hello") {
        if (msg.viewport) {
          viewport = msg.viewport;
          syncRemoteCanvasSize();
        }
        if (msg.url) remoteUrl.textContent = msg.url;
        return;
      }
      if (msg.type === "error") {
        remoteOverlay.hidden = false;
        setRemoteOverlay(msg.error || "error", false);
        return;
      }
      if (msg.type === "closed") {
        remoteOverlay.hidden = false;
        if (msg.message) setRemoteOverlay(msg.message, false);
        else setRemoteOverlay("remote.closed", true);
        return;
      }
      if (msg.type === "frame" && msg.data) {
        if (msg.url) remoteUrl.textContent = msg.url;
        img.onload = () => {
          ctx.drawImage(img, 0, 0, remoteCanvas.width, remoteCanvas.height);
          remoteOverlay.hidden = true;
        };
        img.src = `data:image/jpeg;base64,${msg.data}`;
      }
    };
    ws.onerror = () => {
      remoteOverlay.hidden = false;
      setRemoteOverlay("remote.ws_error", true);
    };
    ws.onclose = () => {
      if (!remoteModal.hidden) {
        remoteOverlay.hidden = false;
        setRemoteOverlay("remote.conn_closed", true);
      }
    };
  }

  async function closeRemoteViewer(save) {
    try {
      await post("/api/remote-browser/stop", {
        profile: profile(),
        save: !!save,
        workspace: remoteViewerWorkspace || workspace || "hh",
      });
    } catch (_) {}
    closeRemoteModalUi();
    await refreshAll();
  }

  remoteCanvas.addEventListener("mousedown", (e) => {
    remoteCanvas.focus();
    const p = scalePoint(e);
    const button = e.button === 2 ? "right" : e.button === 1 ? "middle" : "left";
    send({ type: "mouse", event: "down", button, ...p });
  });
  remoteCanvas.addEventListener("mouseup", (e) => {
    const p = scalePoint(e);
    const button = e.button === 2 ? "right" : e.button === 1 ? "middle" : "left";
    send({ type: "mouse", event: "up", button, ...p });
  });
  remoteCanvas.addEventListener("mousemove", (e) => {
    send({ type: "mouse", event: "move", ...scalePoint(e) });
  });
  remoteCanvas.addEventListener("dblclick", (e) => {
    send({ type: "mouse", event: "dblclick", button: "left", ...scalePoint(e) });
  });
  remoteCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    send({
      type: "mouse",
      event: "wheel",
      ...scalePoint(e),
      deltaX: e.deltaX,
      deltaY: e.deltaY,
    });
  }, { passive: false });
  remoteCanvas.addEventListener("contextmenu", (e) => e.preventDefault());
  remoteCanvas.addEventListener("touchstart", (e) => {
    e.preventDefault();
    remoteCanvas.focus();
    send({ type: "mouse", event: "down", button: "left", ...scalePoint(e) });
  }, { passive: false });
  remoteCanvas.addEventListener("touchend", (e) => {
    e.preventDefault();
    send({ type: "mouse", event: "up", button: "left", ...scalePoint(e) });
  }, { passive: false });
  remoteCanvas.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isRemoteFullscreen()) {
      e.preventDefault();
      e.stopPropagation();
      exitRemoteFullscreen();
      return;
    }
    e.preventDefault();
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      send({ type: "key", event: "type", text: e.key });
      return;
    }
    send({ type: "key", event: "press", key: mapKey(e) });
  });

  $("btnLogin").onclick = async () => {
    if (remoteEnabled) {
      await withAction(() =>
        post("/api/login", { profile: profile(), workspace: "hh" })
      );
      await startRemoteViewer("hh");
      return;
    }
    await withAction(() => post("/api/login"));
  };
  $("btnRemoteBrowser").onclick = async () => {
    await withAction(() =>
      post("/api/remote-browser/start", {
        profile: profile(),
        workspace: "hh",
      })
    );
    await startRemoteViewer("hh");
  };

  if ($("btnLiRemoteBrowser")) {
    $("btnLiRemoteBrowser").onclick = async () => {
      await withAction(() =>
        post("/api/remote-browser/start", {
          profile: profile(),
          workspace: "linkedin",
        })
      );
      await startRemoteViewer("linkedin");
    };
  }

  if ($("btnLiLogin")) {
    $("btnLiLogin").onclick = async () => {
      if (remoteEnabled) {
        await withAction(() => post("/api/linkedin/login"));
        await startRemoteViewer("linkedin");
        return;
      }
      await withAction(() => post("/api/linkedin/login"));
    };
  }
  if ($("btnLiConfirm")) {
    $("btnLiConfirm").onclick = () =>
      withAction(() =>
        remoteEnabled && !remoteModal.hidden
          ? post("/api/remote-browser/save", {
              profile: profile(),
              workspace: "linkedin",
            })
          : post("/api/login/confirm", {
              profile: profile(),
              workspace: "linkedin",
            })
      );
  }
  if ($("btnLiNetwork")) {
    $("btnLiNetwork").onclick = () =>
      withAction(() => post("/api/linkedin/network"));
  }
  if ($("btnLiVacancies")) {
    $("btnLiVacancies").onclick = () =>
      withAction(() => post("/api/linkedin/vacancies/search"));
  }
  if ($("btnLiStop")) {
    $("btnLiStop").onclick = () => requestStop();
  }
  if ($("btnLiCriteria")) {
    $("btnLiCriteria").onclick = async () => {
      try {
        const data = await api("/api/linkedin/launch");
        $("liLaunchText").value = JSON.stringify(data.launch || {}, null, 2);
        if (data.notifications) showNotifications(data.notifications);
        $("liLaunchMessage").textContent = "";
      } catch (e) {
        $("liLaunchMessage").textContent = truncateMsg(String(e.message || e), 200);
      }
      $("liLaunchModal").hidden = false;
    };
  }
  if ($("btnLiLaunchClose")) {
    $("btnLiLaunchClose").onclick = () => {
      $("liLaunchModal").hidden = true;
    };
  }
  if ($("btnLiLaunchSave")) {
    $("btnLiLaunchSave").onclick = async () => {
      try {
        const launch = JSON.parse($("liLaunchText").value || "{}");
        const r = await api("/api/linkedin/launch", {
          method: "POST",
          body: JSON.stringify({ launch }),
        });
        if (!r.ok) {
          $("liLaunchMessage").textContent = truncateMsg(
            r.error || t("launch.err.save"),
            200
          );
          return;
        }
        $("liLaunchMessage").textContent = truncateMsg(
          t("launch.saved", { path: r.path }),
          200
        );
        $("liLaunchModal").hidden = true;
        await refreshAll();
      } catch (e) {
        $("liLaunchMessage").textContent = truncateMsg(String(e.message || e), 200);
      }
    };
  }
  $("btnConfirm").onclick = () =>
    withAction(() =>
      remoteEnabled && !remoteModal.hidden
        ? post("/api/remote-browser/save", {
            profile: profile(),
            workspace: "hh",
          })
        : post("/api/login/confirm", {
            profile: profile(),
            workspace: "hh",
          })
    );
  $("btnRemoteSave").onclick = () => withAction(() => post("/api/remote-browser/save"));
  $("btnRemoteClose").onclick = () => closeRemoteViewer(true);
  if (btnRemoteFullscreen) {
    btnRemoteFullscreen.onclick = () => toggleRemoteFullscreen();
  }
  document.addEventListener("fullscreenchange", () => {
    if (!remoteModal || remoteModal.hidden) return;
    if (document.fullscreenElement === remotePanel) {
      remoteFsDesired = true;
      syncRemoteFullscreenUi();
      return;
    }
    if (!document.fullscreenElement) {
      // Browser Esc / gesture left native FS — collapse CSS expand too.
      remoteFsDesired = false;
      remoteModal.classList.remove("is-fullscreen");
      syncRemoteFullscreenUi();
    }
  });
  window.addEventListener("aa:lang", () => syncRemoteFullscreenUi());
  $("btnSearch").onclick = () => withAction(() => post("/api/search"));
  $("btnApply").onclick = () => withAction(() => post("/api/apply"));
  initReportMenu();
  $("btnStop").onclick = () => requestStop();
  profileSelect.onchange = () => refreshAll();

  function setLaunchMessage(text, ok) {
    const el = $("launchMessage");
    el.textContent = text ? truncateMsg(text, 200) : "";
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("err", !ok && !!text);
  }

  function updateLaunchMeta(launch) {
    lastLaunch = launch || null;
    launchLoaded = true;
    if (!launch) {
      $("launchMeta").textContent = t("launch.meta.empty");
      syncLimitsHint();
      syncActionLabelsCached();
      return;
    }
    const loc = launch.location || {};
    const city = loc.city || loc.country || "?";
    const sal =
      launch.salary_min_usd != null || launch.salary_max_usd != null
        ? `$${launch.salary_min_usd ?? "?"}-${launch.salary_max_usd ?? "?"}`
        : "—";
    const q = (launch.queries || []).length;
    const vLim = launch.vacancy_limit ?? 30;
    const aLim = launch.apply_limit ?? 30;
    $("launchMeta").textContent =
      `${launch.site || "?"} · ${city} · ${sal} · queries=${q} · ` +
      `search≤${vLim} · apply≤${aLim}`;
    syncLimitsHint();
    syncActionLabelsCached();
  }

  async function refreshLaunch() {
    const data = await api("/api/launch");
    if (data.strict_text) $("launchText").value = data.strict_text;
    updateLaunchMeta(data.launch);
    return data;
  }

  function openLaunchModal() {
    launchModal.hidden = false;
    setLaunchMessage("", false);
    const ta = $("launchText");
    if (ta) {
      ta.focus();
      const len = ta.value.length;
      try { ta.setSelectionRange(len, len); } catch (_) {}
    }
  }

  function closeLaunchModal() {
    launchModal.hidden = true;
  }

  $("btnLaunchCriteria").onclick = async () => {
    try {
      await refreshLaunch();
    } catch (_) {}
    openLaunchModal();
  };
  $("btnLaunchClose").onclick = () => closeLaunchModal();
  launchModal.addEventListener("click", (e) => {
    if (e.target === launchModal) closeLaunchModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (remoteModal && !remoteModal.hidden && isRemoteFullscreen()) {
      e.preventDefault();
      exitRemoteFullscreen();
      return;
    }
    if (launchModal && !launchModal.hidden) {
      closeLaunchModal();
    }
  });

  $("btnLaunchValidate").onclick = async () => {
    try {
      const r = await api("/api/launch/validate", {
        method: "POST",
        body: JSON.stringify({ text: $("launchText").value }),
      });
      if (!r.ok) {
        setLaunchMessage(r.error || t("launch.err.validate"), false);
        return;
      }
      setLaunchMessage(t("launch.ok"), true);
      updateLaunchMeta(r.launch);
    } catch (e) {
      setLaunchMessage(String(e.message || e), false);
    }
  };

  $("btnLaunchSave").onclick = async () => {
    try {
      const r = await api("/api/launch/text", {
        method: "POST",
        body: JSON.stringify({ text: $("launchText").value }),
      });
      if (!r.ok) {
        setLaunchMessage(r.error || t("launch.err.save"), false);
        return;
      }
      if (r.strict_text) $("launchText").value = r.strict_text;
      updateLaunchMeta(r.launch);
      setLaunchMessage(t("launch.saved", { path: r.path }), true);
      const cfg = await api("/api/config");
      $("cfgHint").textContent = `${cfg.app_name} · ${cfg.base_url || ""}`.trim();
      closeLaunchModal();
    } catch (e) {
      setLaunchMessage(String(e.message || e), false);
    }
  };

  $("btnAddProfile").onclick = async () => {
    const name = ($("newProfile").value || "").trim();
    if (!name) return;
    await api("/api/profiles", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    $("newProfile").value = "";
    await refreshProfiles();
    profileSelect.value = name;
    await refreshAll();
  };

  $("btnRenameProfile").onclick = async () => {
    const current = profile();
    const next = window.prompt(t("profile.rename.prompt"), current);
    if (next == null) return;
    const name = String(next).trim();
    if (!name || name === current) return;
    try {
      const r = await api(`/api/profiles/${encodeURIComponent(current)}`, {
        method: "PATCH",
        body: JSON.stringify({ new_name: name }),
      });
      await refreshProfiles();
      profileSelect.value = r.name || name;
      await refreshAll();
    } catch (e) {
      setStatusMessage(String(e.message || e));
    }
  };

  $("btnDeleteProfile").onclick = async () => {
    const current = profile();
    if (!window.confirm(t("profile.delete.confirm", { name: current }))) return;
    try {
      const r = await api(`/api/profiles/${encodeURIComponent(current)}`, {
        method: "DELETE",
      });
      await refreshProfiles();
      if (r.selected) profileSelect.value = r.selected;
      await refreshAll();
    } catch (e) {
      setStatusMessage(String(e.message || e));
    }
  };

  window.addEventListener("aa:lang", () => {
    syncActionLabelsCached();
    statusLabel.textContent = statusDisplay(lastStatusCode);
    $("stSession").textContent = lastHasSession
      ? t("stats.session_ok")
      : t("stats.session_no");
    if ($("stLiSession")) {
      $("stLiSession").textContent = lastHasLiSession
        ? t("stats.session_ok")
        : t("stats.session_no");
    }
    updateSessionBanner({
      status: lastStatusCode,
      message: lastStatusMessage,
      has_session: lastHasSession,
      has_linkedin_session: lastHasLiSession,
    });
    if (!statusMessage.textContent.trim()) {
      setStatusMessage(t("status.ready"));
    }
    if (launchLoaded) updateLaunchMeta(lastLaunch);
    if (remoteOverlayKey) {
      remoteOverlay.textContent = t(remoteOverlayKey);
    }
    document.querySelectorAll('[data-i18n="vac.explain"]').forEach((el) => {
      el.textContent = t("vac.explain");
    });
  });

  function readPanelSizes() {
    try {
      const raw = localStorage.getItem(PANEL_SIZE_KEY);
      const data = raw ? JSON.parse(raw) : {};
      return data && typeof data === "object" ? data : {};
    } catch (_) {
      return {};
    }
  }

  function writePanelSizes(map) {
    try {
      localStorage.setItem(PANEL_SIZE_KEY, JSON.stringify(map || {}));
    } catch (_) {}
  }

  function initPanelSizes() {
    const saved = readPanelSizes();
    document.querySelectorAll("[data-panel-size]").forEach((el) => {
      const key = el.getAttribute("data-panel-size");
      const h = key && saved[key];
      if (typeof h === "number" && h > 120) {
        el.style.height = `${h}px`;
      }
      let timer = null;
      const persist = () => {
        if (!key || el.classList.contains("is-log-fullscreen")) return;
        const next = readPanelSizes();
        next[key] = Math.round(el.getBoundingClientRect().height);
        writePanelSizes(next);
      };
      const schedule = () => {
        clearTimeout(timer);
        timer = setTimeout(persist, 120);
      };
      el.addEventListener("pointerup", schedule);
      if (typeof ResizeObserver !== "undefined") {
        let ready = false;
        const ro = new ResizeObserver(() => {
          if (!ready) {
            ready = true;
            return;
          }
          schedule();
        });
        ro.observe(el);
      }
    });
  }

  function syncLogExpandBtn(panel, expanded) {
    if (!panel) return;
    const btn = panel.querySelector("[data-log-expand]");
    if (!btn) return;
    const key = expanded ? "log.collapse" : "log.expand";
    const label = t(key);
    btn.setAttribute("data-i18n", key);
    btn.setAttribute("title", label);
    btn.setAttribute("aria-label", label);
    const use = btn.querySelector("use");
    if (use) use.setAttribute("href", expanded ? "#i-compress" : "#i-expand");
  }

  function setLogFullscreen(panelId, on) {
    const panel = panelId ? $(panelId) : null;
    if (logFullscreenId && logFullscreenId !== panelId) {
      const prev = $(logFullscreenId);
      if (prev) {
        prev.classList.remove("is-log-fullscreen");
        syncLogExpandBtn(prev, false);
      }
    }
    if (!panel) {
      logFullscreenId = null;
      document.body.classList.remove("is-log-fs-open");
      return;
    }
    panel.classList.toggle("is-log-fullscreen", !!on);
    syncLogExpandBtn(panel, !!on);
    logFullscreenId = on ? panelId : null;
    document.body.classList.toggle("is-log-fs-open", !!on);
  }

  function initLogFullscreen() {
    document.querySelectorAll("[data-log-expand]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-log-expand");
        if (!id) return;
        const open = logFullscreenId === id;
        setLogFullscreen(id, !open);
      });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !logFullscreenId) return;
      if (remoteModal && !remoteModal.hidden) return;
      if (launchModal && !launchModal.hidden) return;
      if ($("liLaunchModal") && !$("liLaunchModal").hidden) return;
      if (explainModal && !explainModal.hidden) return;
      setLogFullscreen(logFullscreenId, false);
    });
    window.addEventListener("aa:lang", () => {
      document.querySelectorAll("[data-log-expand]").forEach((btn) => {
        const id = btn.getAttribute("data-log-expand");
        if (!id) return;
        syncLogExpandBtn($(id), logFullscreenId === id);
      });
    });
  }

  initTheme();
  initWorkspace();
  initPanelSizes();
  initLogFullscreen();
  if (window.AA_I18N) window.AA_I18N.initLang();
  setStatusMessage(t("status.ready"));

  const logoutForm = $("logoutForm");
  if (logoutForm) {
    logoutForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await fetch("/logout", {
          method: "POST",
          credentials: "same-origin",
          redirect: "manual",
          headers: { Accept: "text/html" },
        });
      } catch (_) {}
      window.location.replace("/login");
    });
  }

  (async () => {
    try {
      const cfg = await api("/api/config");
      applyRemoteUiFlag(!!cfg.enable_remote_browser);
      if (cfg.notifications) showNotifications(cfg.notifications);
      $("cfgHint").textContent = `${cfg.app_name} · ${cfg.base_url || ""}`.trim();
      await refreshLaunch();
    } catch (_) {}
    await refreshProfiles();
    await refreshAll();
    setInterval(refreshAll, 2000);
  })();
})();
