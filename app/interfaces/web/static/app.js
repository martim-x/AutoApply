(() => {
  const $ = (id) => document.getElementById(id);
  const profileSelect = $("profileSelect");
  const statusPill = $("statusPill");
  const statusLabel = $("statusLabel");
  const statusMessage = $("statusMessage");
  const remoteModal = $("remoteModal");
  const remoteCanvas = $("remoteCanvas");
  const remoteOverlay = $("remoteOverlay");
  const remoteUrl = $("remoteUrl");
  const explainModal = $("explainModal");
  const ctx = remoteCanvas.getContext("2d");

  let remoteEnabled = false;
  let ws = null;
  let viewport = { width: 1280, height: 900 };
  let img = new Image();

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

  function applyRemoteUiFlag(enabled) {
    remoteEnabled = !!enabled;
    $("btnRemoteBrowser").hidden = !remoteEnabled;
    $("remoteHint").hidden = !remoteEnabled;
    $("btnLogin").textContent = remoteEnabled
      ? "Login (remote)"
      : "Login / Connect";
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

  async function refreshStatus() {
    const st = await api(`/api/status?profile=${encodeURIComponent(profile())}`);
    const status = st.status || "idle";
    statusPill.dataset.status = status;
    statusLabel.textContent = status;
    statusMessage.textContent = st.message || "";
    setBusy(!!st.busy);

    const s = st.stats || {};
    $("stHigh").textContent = s.high ?? 0;
    $("stMedium").textContent = s.medium ?? 0;
    $("stLow").textContent = s.low ?? 0;
    $("stQueued").textContent = s.queued ?? 0;
    $("stApplied").textContent = s.applied ?? 0;
    $("stSession").textContent = st.has_session ? "ok" : "нет";

    if (st.remote_browser && typeof st.remote_browser.enabled === "boolean") {
      applyRemoteUiFlag(st.remote_browser.enabled);
    }
  }

  function explainButtonHtml(vacancyId) {
    return `<button type="button" class="ghost touch btn-explain" data-vacancy-id="${vacancyId}">Explain</button>`;
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
    $("explainText").textContent = "Считаем веса…";
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

  async function refreshAll() {
    try {
      await refreshStatus();
      await Promise.all([refreshVacancies(), refreshLogs()]);
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
    remoteOverlay.textContent = "Подключение…";
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

  async function startRemoteViewer() {
    openRemoteModal();
    try {
      const started = await post("/api/remote-browser/start");
      if (started && started.error) {
        remoteOverlay.textContent = started.error;
        statusMessage.textContent = started.error;
        return;
      }
      if (started && started.viewport) viewport = started.viewport;
    } catch (e) {
      remoteOverlay.textContent = String(e.message || e);
      return;
    }

    if (ws) {
      try { ws.close(); } catch (_) {}
    }

    ws = new WebSocket(wsUrl());
    ws.onopen = () => {
      remoteOverlay.textContent = "Ожидание кадров…";
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
        remoteOverlay.textContent = msg.error || "error";
        return;
      }
      if (msg.type === "closed") {
        remoteOverlay.hidden = false;
        remoteOverlay.textContent = msg.message || "закрыто";
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
      remoteOverlay.textContent = "WebSocket error";
    };
    ws.onclose = () => {
      if (!remoteModal.hidden) {
        remoteOverlay.hidden = false;
        remoteOverlay.textContent = "Соединение закрыто";
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
      await withAction(() => post("/api/login"));
      await startRemoteViewer();
      return;
    }
    await withAction(() => post("/api/login"));
  };
  $("btnRemoteBrowser").onclick = async () => {
    await withAction(() => post("/api/remote-browser/start"));
    await startRemoteViewer();
  };
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
  $("btnStop").onclick = async () => {
    if (remoteEnabled && (!remoteModal.hidden || (ws && ws.readyState === WebSocket.OPEN))) {
      await closeRemoteViewer(true);
      return;
    }
    await withAction(() => post("/api/stop"));
  };
  profileSelect.onchange = () => refreshAll();

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

  (async () => {
    try {
      const cfg = await api("/api/config");
      applyRemoteUiFlag(!!cfg.enable_remote_browser);
      $("cfgHint").textContent =
        `${cfg.app_name} · ${cfg.base_url}` +
        ` · remote/hybrid=${cfg.require_remote_or_hybrid}` +
        ` · weights=config/weights.json` +
        ` · remote_browser=${cfg.enable_remote_browser ? "on" : "off"}`;
    } catch (_) {}
    await refreshProfiles();
    await refreshAll();
    setInterval(refreshAll, 2000);
  })();
})();
