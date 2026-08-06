(() => {
  const $ = (id) => document.getElementById(id);
  const profileSelect = $("profileSelect");
  const statusPill = $("statusPill");
  const statusLabel = $("statusLabel");
  const statusMessage = $("statusMessage");

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

  async function post(path) {
    return api(path, {
      method: "POST",
      body: JSON.stringify({ profile: profile() }),
    });
  }

  function setBusy(busy) {
    ["btnLogin", "btnSearch", "btnApply"].forEach((id) => {
      $(id).disabled = busy;
    });
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
  }

  async function refreshVacancies() {
    const data = await api(`/api/vacancies?profile=${encodeURIComponent(profile())}&limit=80`);
    const body = $("vacBody");
    body.innerHTML = "";
    (data.vacancies || []).forEach((v) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="cat-${v.category}">${v.category}</td>
        <td>${v.score}</td>
        <td><a href="${v.url}" target="_blank" rel="noopener">${escapeHtml(v.title || v.url)}</a></td>
        <td>${escapeHtml(v.filter_status || "")}</td>
        <td>${escapeHtml(v.apply_status || "")}</td>`;
      body.appendChild(tr);
    });
  }

  async function refreshLogs() {
    const data = await api(`/api/logs?profile=${encodeURIComponent(profile())}&limit=50`);
    const list = $("logList");
    list.innerHTML = "";
    (data.logs || []).forEach((l) => {
      const li = document.createElement("li");
      li.className = l.level === "error" ? "err" : "";
      li.innerHTML = `<span>${l.when || ""}</span> <span class="ev">${escapeHtml(l.event)}</span> ${escapeHtml(l.message || "")}`;
      list.appendChild(li);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

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
    } catch (e) {
      statusMessage.textContent = String(e.message || e);
    }
  }

  $("btnLogin").onclick = () => withAction(() => post("/api/login"));
  $("btnConfirm").onclick = () => withAction(() => post("/api/login/confirm"));
  $("btnSearch").onclick = () => withAction(() => post("/api/search"));
  $("btnApply").onclick = () => withAction(() => post("/api/apply"));
  $("btnStop").onclick = () => withAction(() => post("/api/stop"));
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
      $("cfgHint").textContent =
        `${cfg.app_name} · ${cfg.base_url} · queries: ${ (cfg.search_queries || []).slice(0, 2).join(", ") }` +
        ` · remote/hybrid=${cfg.require_remote_or_hybrid} · skip_gov=${cfg.skip_gov} · db=${cfg.database_backend}`;
    } catch (_) {}
    await refreshProfiles();
    await refreshAll();
    setInterval(refreshAll, 2000);
  })();
})();
