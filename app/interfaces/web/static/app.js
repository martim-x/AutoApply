(() => {
  const $ = (id) => document.getElementById(id);
  const t = (key, vars) => (window.AA_I18N ? window.AA_I18N.t(key, vars) : key);
  const profileSelect = $("profileSelect");
  const statusPill = $("statusPill");
  const statusLabel = $("statusLabel");
  const statusMessage = $("statusMessage");
  const remoteModal = $("remoteModal");
  const remoteCanvas = $("remoteCanvas");
  const remoteOverlay = $("remoteOverlay");
  const remoteUrl = $("remoteUrl");
  const explainModal = $("explainModal");
  const launchModal = $("launchModal");
  const ctx = remoteCanvas.getContext("2d");

  let remoteEnabled = false;
  let ws = null;
  let viewport = { width: 1280, height: 900 };
  let img = new Image();
  let lastLaunch = null;
  let launchLoaded = false;
  let remoteOverlayKey = null;
  let lastStatusCode = "idle";
  let lastHasSession = false;
  let lastHasLiSession = false;
  let workspace = "hh";
  let liTab = "network";
  const WORKSPACE_KEY = "aa-workspace";

  function profile() {
    return profileSelect.value || "default";
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
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

  function setBusy(busy) {
    ["btnLogin", "btnRemoteBrowser", "btnSearch", "btnApply"].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = busy && id !== "btnRemoteBrowser";
    });
  }

  function syncLoginLabel() {
    const loginLabel = document.querySelector("[data-label-login]");
    if (!loginLabel) return;
    const key = remoteEnabled ? "login.remote" : "login.connect";
    loginLabel.setAttribute("data-i18n", key);
    loginLabel.textContent = t(key);
  }

  function applyRemoteUiFlag(enabled) {
    remoteEnabled = !!enabled;
    $("btnRemoteBrowser").hidden = !remoteEnabled;
    $("remoteHint").hidden = !remoteEnabled;
    syncLoginLabel();
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
    s = s.replace(/\b(HIGH|MEDIUM|LOW)\b/g, '<span class="score">$1</span>');
    s = s.replace(/\b(score[=:]?\s*\d+)\b/gi, '<span class="score">$1</span>');
    s = s.replace(/\b(applied|queued|skipped|dry_run|ok)\b/gi, '<span class="ok">$1</span>');
    s = s.replace(/\b(error[:\w.-]*)\b/gi, '<span class="err">$1</span>');
    return s;
  }

  async function refreshProfiles() {
    const data = await api("/api/profiles");
    const current = profileSelect.value || "default";
    profileSelect.innerHTML = "";
    (data.profiles || []).forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = p.has_session ? `${p.name} ●` : p.name;
      profileSelect.appendChild(opt);
    });
    if ([...profileSelect.options].some((o) => o.value === current)) {
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
      .map((n) => `<div class="notify-item">${escapeHtml(n)}</div>`)
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
    el.textContent = t("alert.last", { event: ev, message: alert.message });
  }

  function applyWorkspace(ws) {
    workspace = ws === "linkedin" ? "linkedin" : "hh";
    try {
      localStorage.setItem(WORKSPACE_KEY, workspace);
    } catch (_) {}
    const sw = $("workspaceSwitch");
    if (sw) sw.dataset.workspace = workspace;
    document.querySelectorAll("[data-workspace-set]").forEach((btn) => {
      btn.setAttribute(
        "aria-pressed",
        btn.getAttribute("data-workspace-set") === workspace ? "true" : "false"
      );
    });
    const isLi = workspace === "linkedin";
    if ($("hhActions")) $("hhActions").hidden = isLi;
    if ($("liActions")) $("liActions").hidden = !isLi;
    if ($("liTabs")) $("liTabs").hidden = !isLi;
    if ($("hhPanels")) $("hhPanels").hidden = isLi;
    if ($("liPanels")) $("liPanels").hidden = !isLi;
    if ($("statsGrid")) $("statsGrid").hidden = isLi;
    if ($("liStatsGrid")) $("liStatsGrid").hidden = !isLi;
    if ($("linkedinRisk")) $("linkedinRisk").hidden = !isLi;
    if ($("criteria-bar") || document.querySelector(".criteria-bar")) {
      const bar = document.querySelector(".criteria-bar");
      if (bar) bar.hidden = isLi;
    }
    applyLiTab(liTab);
  }

  function applyLiTab(tab) {
    liTab = tab === "vacancies" ? "vacancies" : "network";
    document.querySelectorAll("[data-li-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-li-tab") === liTab);
    });
    if ($("liNetworkPanel")) $("liNetworkPanel").hidden = liTab !== "network";
    if ($("liVacPanel")) $("liVacPanel").hidden = liTab !== "vacancies";
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
    lastHasSession = !!st.has_session;
    lastHasLiSession = !!st.has_linkedin_session;
    statusPill.dataset.status = status;
    statusLabel.textContent = statusDisplay(status);
    statusMessage.textContent = st.message || "";
    setBusy(!!st.busy);

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

    const sched = st.report_schedule;
    const hint = $("reportScheduleHint");
    if (hint && sched) {
      if (sched.enabled) {
        const when = sched.next_run_iso
          ? sched.next_run_iso
          : `${String(sched.hour).padStart(2, "0")}:${String(sched.minute).padStart(2, "0")} ${sched.timezone || ""}`;
        const last = sched.last_run_at
          ? new Date(sched.last_run_at * 1000).toLocaleString()
          : (sched.last_file && sched.last_file.created_at
              ? new Date(sched.last_file.created_at * 1000).toLocaleString()
              : "—");
        hint.textContent = t("report.schedule.hint", { when, last });
      } else {
        hint.textContent = t("report.schedule.off");
      }
    }

    const parseSched = st.parse_schedule;
    const parseHint = $("parseScheduleHint");
    if (parseHint && parseSched) {
      if (parseSched.enabled) {
        const when = parseSched.next_run_iso
          ? parseSched.next_run_iso
          : (parseSched.times_display || "—");
        const last = parseSched.last_run_at
          ? new Date(parseSched.last_run_at * 1000).toLocaleString()
          : "—";
        parseHint.textContent = t("parse.schedule.hint", {
          times: parseSched.times_display || "12:00,00:00",
          tz: parseSched.timezone || "Europe/Minsk",
          when,
          last,
        });
      } else {
        parseHint.textContent = t("parse.schedule.off");
      }
    }

    if (st.remote_browser && typeof st.remote_browser.enabled === "boolean") {
      applyRemoteUiFlag(st.remote_browser.enabled);
    }
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
    const data = await api(`/api/logs?profile=${encodeURIComponent(profile())}&limit=50`);
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
        highlightLogMessage(l.message || "");
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
        $("explainText").textContent = data.error;
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
      $("explainText").textContent = String(e.message || e);
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

  async function refreshLiContacts() {
    const data = await api(
      `/api/linkedin/contacts?profile=${encodeURIComponent(profile())}&limit=80`
    );
    const body = $("liContactBody");
    if (!body) return;
    body.innerHTML = "";
    (data.contacts || []).forEach((c) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(c.status || "")}</td>
        <td><a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.name || c.url)}</a></td>
        <td>${escapeHtml(c.query || "")}</td>`;
      body.appendChild(tr);
    });
  }

  async function refreshLiVacancies() {
    const data = await api(
      `/api/linkedin/vacancies?profile=${encodeURIComponent(profile())}&limit=80`
    );
    const body = $("liVacBody");
    if (!body) return;
    body.innerHTML = "";
    (data.vacancies || []).forEach((v) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><a href="${escapeHtml(v.url)}" target="_blank" rel="noopener">${escapeHtml(v.title || v.url)}</a></td>
        <td>${escapeHtml(v.location || "")}</td>
        <td>${escapeHtml(v.query || "")}</td>`;
      body.appendChild(tr);
    });
  }

  async function refreshLiLogs() {
    const data = await api(`/api/logs?profile=${encodeURIComponent(profile())}&limit=50`);
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
        highlightLogMessage(l.message || "");
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
      statusMessage.textContent = String(e.message || e);
    }
  }

  async function withAction(fn) {
    try {
      const r = await fn();
      if (r && r.error) statusMessage.textContent = r.error;
      else if (r && r.message) statusMessage.textContent = r.message;
      await refreshAll();
      return r;
    } catch (e) {
      statusMessage.textContent = String(e.message || e);
      return null;
    }
  }

  function wsUrl() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}/api/remote-browser/ws?profile=${encodeURIComponent(profile())}`;
  }

  function scalePoint(e) {
    const rect = remoteCanvas.getBoundingClientRect();
    const clientX = e.clientX ?? (e.touches && e.touches[0] && e.touches[0].clientX) ?? 0;
    const clientY = e.clientY ?? (e.touches && e.touches[0] && e.touches[0].clientY) ?? 0;
    const x = ((clientX - rect.left) / rect.width) * viewport.width;
    const y = ((clientY - rect.top) / rect.height) * viewport.height;
    return {
      x: Math.max(0, Math.min(viewport.width, x)),
      y: Math.max(0, Math.min(viewport.height, y)),
    };
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
    remoteCanvas.focus();
  }

  function closeRemoteModalUi() {
    remoteModal.hidden = true;
    if (ws) {
      try { ws.close(); } catch (_) {}
      ws = null;
    }
  }

  async function startRemoteViewer(wsName) {
    openRemoteModal();
    try {
      const started = await post("/api/remote-browser/start", {
        profile: profile(),
        workspace: wsName || workspace || "hh",
      });
      if (started && started.error) {
        setRemoteOverlay(started.error, false);
        statusMessage.textContent = started.error;
        return;
      }
      if (started && started.viewport) viewport = started.viewport;
    } catch (e) {
      setRemoteOverlay(String(e.message || e), false);
      return;
    }

    if (ws) {
      try { ws.close(); } catch (_) {}
    }

    ws = new WebSocket(wsUrl());
    ws.onopen = () => {
      setRemoteOverlay("remote.waiting_frames", true);
      remoteCanvas.focus();
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.type === "hello") {
        if (msg.viewport) viewport = msg.viewport;
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
      await post("/api/remote-browser/stop", { profile: profile(), save: !!save });
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
          ? post("/api/remote-browser/save")
          : post("/api/login/confirm")
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
    $("btnLiStop").onclick = async () => {
      if (remoteEnabled && (!remoteModal.hidden || (ws && ws.readyState === WebSocket.OPEN))) {
        await closeRemoteViewer(true);
        return;
      }
      await withAction(() => post("/api/stop"));
    };
  }
  if ($("btnLiCriteria")) {
    $("btnLiCriteria").onclick = async () => {
      try {
        const data = await api("/api/linkedin/launch");
        $("liLaunchText").value = JSON.stringify(data.launch || {}, null, 2);
        if (data.notifications) showNotifications(data.notifications);
        $("liLaunchMessage").textContent = "";
      } catch (e) {
        $("liLaunchMessage").textContent = String(e.message || e);
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
          $("liLaunchMessage").textContent = r.error || t("launch.err.save");
          return;
        }
        $("liLaunchMessage").textContent = t("launch.saved", { path: r.path });
        $("liLaunchModal").hidden = true;
        await refreshAll();
      } catch (e) {
        $("liLaunchMessage").textContent = String(e.message || e);
      }
    };
  }
  $("btnConfirm").onclick = () =>
    withAction(() =>
      remoteEnabled && !remoteModal.hidden
        ? post("/api/remote-browser/save")
        : post("/api/login/confirm")
    );
  $("btnRemoteSave").onclick = () => withAction(() => post("/api/remote-browser/save"));
  $("btnRemoteClose").onclick = () => closeRemoteViewer(true);
  $("btnSearch").onclick = () => withAction(() => post("/api/search"));
  $("btnApply").onclick = () => withAction(() => post("/api/apply"));
  $("btnDownloadReport").onclick = () => {
    const kind = ($("reportKind") && $("reportKind").value) || "work";
    const url =
      `/api/reports/${encodeURIComponent(kind)}.pdf` +
      `?profile=${encodeURIComponent(profile())}`;
    window.location.href = url;
  };
  $("btnStop").onclick = async () => {
    if (remoteEnabled && (!remoteModal.hidden || (ws && ws.readyState === WebSocket.OPEN))) {
      await closeRemoteViewer(true);
      return;
    }
    await withAction(() => post("/api/stop"));
  };
  profileSelect.onchange = () => refreshAll();

  function setLaunchMessage(text, ok) {
    const el = $("launchMessage");
    el.textContent = text || "";
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("err", !ok && !!text);
  }

  function updateLaunchMeta(launch) {
    lastLaunch = launch || null;
    launchLoaded = true;
    if (!launch) {
      $("launchMeta").textContent = t("launch.meta.empty");
      return;
    }
    const loc = launch.location || {};
    const city = loc.city || loc.country || "?";
    const sal =
      launch.salary_min_usd != null || launch.salary_max_usd != null
        ? `$${launch.salary_min_usd ?? "?"}-${launch.salary_max_usd ?? "?"}`
        : "—";
    const q = (launch.queries || []).length;
    $("launchMeta").textContent =
      `${launch.site || "?"} · ${city} · ${sal} · queries=${q}`;
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
    if (e.key === "Escape" && launchModal && !launchModal.hidden) {
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
      $("cfgHint").textContent =
        `${cfg.app_name} · ${cfg.base_url}` +
        ` · area=${cfg.search_area}` +
        ` · remote/hybrid=${cfg.require_remote_or_hybrid}` +
        ` · launch=on`;
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

  window.addEventListener("aa:lang", () => {
    syncLoginLabel();
    statusLabel.textContent = statusDisplay(lastStatusCode);
    $("stSession").textContent = lastHasSession
      ? t("stats.session_ok")
      : t("stats.session_no");
    if (!statusMessage.textContent.trim()) {
      statusMessage.textContent = t("status.ready");
    }
    if (launchLoaded) updateLaunchMeta(lastLaunch);
    if (remoteOverlayKey) {
      remoteOverlay.textContent = t(remoteOverlayKey);
    }
    document.querySelectorAll('[data-i18n="vac.explain"]').forEach((el) => {
      el.textContent = t("vac.explain");
    });
  });

  initTheme();
  initWorkspace();
  if (window.AA_I18N) window.AA_I18N.initLang();
  statusMessage.textContent = t("status.ready");

  (async () => {
    try {
      const cfg = await api("/api/config");
      applyRemoteUiFlag(!!cfg.enable_remote_browser);
      if (cfg.notifications) showNotifications(cfg.notifications);
      $("cfgHint").textContent =
        `${cfg.app_name} · ${cfg.base_url}` +
        ` · area=${cfg.search_area || "-"}` +
        ` · remote/hybrid=${cfg.require_remote_or_hybrid}` +
        ` · weights=config/weights.json` +
        ` · remote_browser=${cfg.enable_remote_browser ? "on" : "off"}` +
        ` · workspaces=hh+linkedin`;
      await refreshLaunch();
    } catch (_) {}
    await refreshProfiles();
    await refreshAll();
    setInterval(refreshAll, 2000);
  })();
})();
