(() => {
  const MASK = "*******";
  const THEME_KEY = "aa-theme";

  const $ = (id) => document.getElementById(id);

  const form = $("envForm");
  const rawEl = $("envRaw");
  const listEl = $("varsList");
  const listPanel = $("varsListPanel");
  const rawPanel = $("varsRawPanel");
  const searchEl = $("envSearch");
  const btnRaw = $("btnRawEditor");
  const btnNew = $("btnNewVar");
  const varsCount = $("varsCount");
  const varsEmpty = $("varsEmpty");
  const varsNoMatch = $("varsNoMatch");
  const dialog = $("varDialog");
  const dialogForm = $("varDialogForm");
  const dialogTitle = $("varDialogTitle");
  const dialogError = $("varDialogError");
  const keyInput = $("varKey");
  const valueInput = $("varValue");
  const btnToggleValue = $("btnToggleValue");

  /** @type {{ type: 'blank'|'comment'|'kv', key?: string, value?: string, raw?: string, export?: boolean }[]} */
  let lines = [];
  /** @type {Set<string>} */
  const revealed = new Set();
  let rawMode = false;
  /** List edits pending serialize into #envRaw (avoids rewriting .env on no-op save). */
  let listDirty = false;
  /** @type {{ mode: 'add'|'edit', key?: string } | null} */
  let dialogMode = null;
  let openMenuKey = null;

  function t(key, vars) {
    return window.AA_I18N ? window.AA_I18N.t(key, vars) : key;
  }

  function applyI18n(root) {
    if (window.AA_I18N) window.AA_I18N.applyI18n(root || document);
  }

  function readInitial() {
    const el = $("env-initial");
    if (!el) return "";
    try {
      const parsed = JSON.parse(el.textContent || '""');
      return typeof parsed === "string" ? parsed : "";
    } catch (_) {
      return "";
    }
  }

  function unquote(raw) {
    const s = String(raw ?? "").trim();
    if (s.length >= 2) {
      const q = s[0];
      if ((q === '"' || q === "'") && s[s.length - 1] === q) {
        let inner = s.slice(1, -1);
        if (q === '"') {
          inner = inner
            .replace(/\\n/g, "\n")
            .replace(/\\r/g, "\r")
            .replace(/\\t/g, "\t")
            .replace(/\\"/g, '"')
            .replace(/\\\\/g, "\\");
        }
        return inner;
      }
    }
    // Unquoted: strip trailing inline comment " # ..."
    const m = s.match(/^(.*?)(\s+#.*)?$/);
    return (m ? m[1] : s).trimEnd();
  }

  function quoteValue(value) {
    const s = String(value ?? "");
    if (s === "") return "";
    if (/[\s#"'$`\\]/.test(s) || s.includes("\n") || s.includes("\r")) {
      return (
        '"' +
        s
          .replace(/\\/g, "\\\\")
          .replace(/"/g, '\\"')
          .replace(/\n/g, "\\n")
          .replace(/\r/g, "\\r")
          .replace(/\t/g, "\\t") +
        '"'
      );
    }
    return s;
  }

  function parseEnv(text) {
    const src = String(text ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const out = [];
    const parts = src.split("\n");
    // Drop final empty split from trailing newline; keep intentional blanks.
    if (parts.length && parts[parts.length - 1] === "") parts.pop();
    for (const line of parts) {
      const trimmed = line.trim();
      if (!trimmed) {
        out.push({ type: "blank", raw: line });
        continue;
      }
      if (trimmed.startsWith("#")) {
        out.push({ type: "comment", raw: line });
        continue;
      }
      const m = line.match(/^\s*(export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
      if (!m) {
        out.push({ type: "comment", raw: line });
        continue;
      }
      out.push({
        type: "kv",
        export: Boolean(m[1]),
        key: m[2],
        value: unquote(m[3]),
      });
    }
    return out;
  }

  function serializeEnv(items) {
    const body = items
      .map((item) => {
        if (item.type === "blank") return "";
        if (item.type === "comment") return item.raw ?? "";
        const prefix = item.export ? "export " : "";
        return `${prefix}${item.key}=${quoteValue(item.value)}`;
      })
      .join("\n");
    return body ? body + "\n" : "";
  }

  function listVariables() {
    /** @type {Map<string, { key: string, value: string }>} */
    const map = new Map();
    for (const item of lines) {
      if (item.type === "kv" && item.key) {
        map.set(item.key, { key: item.key, value: item.value ?? "" });
      }
    }
    return Array.from(map.values());
  }

  function syncRawFromLines() {
    rawEl.value = serializeEnv(lines);
    listDirty = false;
  }

  function syncLinesFromRaw() {
    lines = parseEnv(rawEl.value);
    listDirty = false;
  }

  function setRawMode(on) {
    rawMode = Boolean(on);
    if (rawMode) {
      if (listDirty) syncRawFromLines();
      listPanel.hidden = true;
      rawPanel.hidden = false;
      btnRaw.setAttribute("aria-pressed", "true");
      btnRaw.classList.add("is-active");
      btnNew.disabled = true;
      searchEl.disabled = true;
    } else {
      syncLinesFromRaw();
      listPanel.hidden = false;
      rawPanel.hidden = true;
      btnRaw.setAttribute("aria-pressed", "false");
      btnRaw.classList.remove("is-active");
      btnNew.disabled = false;
      searchEl.disabled = false;
      renderList();
    }
    btnRaw.setAttribute("data-i18n", rawMode ? "admin.env.list" : "admin.env.raw");
    btnRaw.textContent = rawMode ? t("admin.env.list") : t("admin.env.raw");
  }

  function closeMenus() {
    openMenuKey = null;
    listEl.querySelectorAll(".admin-vars-menu[open]").forEach((el) => {
      el.removeAttribute("open");
    });
  }

  function renderList() {
    const q = (searchEl.value || "").trim().toLowerCase();
    const vars = listVariables();
    const filtered = q
      ? vars.filter((v) => v.key.toLowerCase().includes(q))
      : vars;

    varsCount.textContent = t("admin.env.count", { n: String(vars.length) });
    listEl.innerHTML = "";
    varsEmpty.hidden = vars.length !== 0;
    varsNoMatch.hidden = !(vars.length && filtered.length === 0);

    for (const v of filtered) {
      const li = document.createElement("li");
      li.className = "admin-vars-row";
      li.dataset.key = v.key;

      const show = revealed.has(v.key);
      const display = show ? v.value || "—" : MASK;

      li.innerHTML = `
        <span class="admin-vars-ico" aria-hidden="true">
          <svg class="ico"><use href="#i-key"/></svg>
        </span>
        <span class="admin-vars-key"></span>
        <span class="admin-vars-val ${show ? "is-plain" : "is-masked"}"></span>
        <details class="admin-vars-menu">
          <summary class="admin-vars-menu-btn" aria-label="">
            <svg class="ico" aria-hidden="true"><use href="#i-dots"/></svg>
          </summary>
          <div class="admin-vars-menu-panel" role="menu">
            <button type="button" data-act="edit" role="menuitem"></button>
            <button type="button" data-act="toggle" role="menuitem"></button>
            <button type="button" data-act="delete" class="is-danger" role="menuitem"></button>
          </div>
        </details>
      `;

      li.querySelector(".admin-vars-key").textContent = v.key;
      const valEl = li.querySelector(".admin-vars-val");
      valEl.textContent = display;
      valEl.title = show ? v.value : "";

      const summary = li.querySelector("summary");
      summary.setAttribute("aria-label", t("admin.env.menu"));
      li.querySelector('[data-act="edit"]').textContent = t("admin.env.edit");
      li.querySelector('[data-act="toggle"]').textContent = show
        ? t("admin.env.hide")
        : t("admin.env.reveal");
      li.querySelector('[data-act="delete"]').textContent = t("admin.env.delete");

      const menu = li.querySelector("details");
      menu.addEventListener("toggle", () => {
        if (menu.open) {
          listEl.querySelectorAll(".admin-vars-menu[open]").forEach((el) => {
            if (el !== menu) el.removeAttribute("open");
          });
          openMenuKey = v.key;
        } else if (openMenuKey === v.key) {
          openMenuKey = null;
        }
      });

      li.querySelector('[data-act="edit"]').addEventListener("click", () => {
        closeMenus();
        openDialog("edit", v.key, v.value);
      });
      li.querySelector('[data-act="toggle"]').addEventListener("click", () => {
        if (revealed.has(v.key)) revealed.delete(v.key);
        else revealed.add(v.key);
        closeMenus();
        renderList();
      });
      li.querySelector('[data-act="delete"]').addEventListener("click", () => {
        closeMenus();
        if (!window.confirm(t("admin.env.delete.confirm", { key: v.key }))) return;
        deleteVariable(v.key);
        renderList();
      });

      listEl.appendChild(li);
    }
  }

  function upsertVariable(key, value, { renameFrom } = {}) {
    const k = key.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) {
      throw new Error(t("admin.env.err.key"));
    }
    if (renameFrom && renameFrom !== k) {
      const exists = lines.some((it) => it.type === "kv" && it.key === k);
      if (exists) throw new Error(t("admin.env.err.exists", { key: k }));
      let replaced = false;
      lines = lines.map((it) => {
        if (it.type === "kv" && it.key === renameFrom) {
          replaced = true;
          return { ...it, key: k, value };
        }
        return it;
      });
      if (!replaced) {
        lines.push({ type: "kv", key: k, value, export: false });
      }
      if (revealed.has(renameFrom)) {
        revealed.delete(renameFrom);
        revealed.add(k);
      }
      listDirty = true;
      return;
    }
    let found = false;
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const it = lines[i];
      if (it.type === "kv" && it.key === k) {
        it.value = value;
        found = true;
        break;
      }
    }
    if (!found) {
      if (lines.length && lines[lines.length - 1].type !== "blank") {
        lines.push({ type: "blank", raw: "" });
      }
      lines.push({ type: "kv", key: k, value, export: false });
    }
    listDirty = true;
  }

  function deleteVariable(key) {
    lines = lines.filter((it) => !(it.type === "kv" && it.key === key));
    revealed.delete(key);
    listDirty = true;
  }

  function setValueVisibility(show) {
    valueInput.type = show ? "text" : "password";
    const use = btnToggleValue.querySelector("use");
    if (use) use.setAttribute("href", show ? "#i-eye-off" : "#i-eye");
    const label = show ? t("admin.env.hide") : t("admin.env.reveal");
    btnToggleValue.setAttribute("title", label);
    btnToggleValue.setAttribute("aria-label", label);
  }

  function openDialog(mode, key = "", value = "") {
    dialogMode = { mode, key: key || undefined };
    dialogError.hidden = true;
    dialogError.textContent = "";
    keyInput.value = key;
    valueInput.value = value;
    keyInput.readOnly = false;
    setValueVisibility(false);
    if (mode === "add") {
      dialogTitle.setAttribute("data-i18n", "admin.env.dialog.add");
      dialogForm.querySelector('[value="save"]').setAttribute("data-i18n", "admin.env.dialog.ok");
    } else {
      dialogTitle.setAttribute("data-i18n", "admin.env.dialog.edit");
      dialogForm.querySelector('[value="save"]').setAttribute("data-i18n", "admin.env.dialog.save");
    }
    applyI18n(dialog);
    if (window.AA_BODY_SCROLL) window.AA_BODY_SCROLL.lock("admin-var-dialog");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    keyInput.focus();
    keyInput.select();
  }

  function closeDialog() {
    dialogMode = null;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
    if (window.AA_BODY_SCROLL) window.AA_BODY_SCROLL.unlock("admin-var-dialog");
  }

  if (dialog) {
    dialog.addEventListener("close", () => {
      if (window.AA_BODY_SCROLL) window.AA_BODY_SCROLL.unlock("admin-var-dialog");
    });
  }

  function initTheme() {
    const applyTheme = (pref) => {
      const p = pref === "light" || pref === "dark" || pref === "system" ? pref : "system";
      try {
        localStorage.setItem(THEME_KEY, p);
      } catch (_) {}
      document.documentElement.setAttribute("data-theme-pref", p);
      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const resolved = p === "system" ? (dark ? "dark" : "light") : p;
      document.documentElement.setAttribute("data-theme", resolved);
      document.querySelectorAll("[data-theme-set]").forEach((btn) => {
        btn.setAttribute(
          "aria-pressed",
          btn.getAttribute("data-theme-set") === p ? "true" : "false"
        );
      });
    };
    document.querySelectorAll("[data-theme-set]").forEach((btn) => {
      btn.addEventListener("click", () => applyTheme(btn.getAttribute("data-theme-set")));
    });
    let pref = "system";
    try {
      pref = localStorage.getItem(THEME_KEY) || "system";
    } catch (_) {}
    applyTheme(pref);
    try {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        const cur = document.documentElement.getAttribute("data-theme-pref") || "system";
        if (cur === "system") applyTheme("system");
      });
    } catch (_) {}
  }

  // Events
  btnRaw.addEventListener("click", () => setRawMode(!rawMode));
  btnNew.addEventListener("click", () => openDialog("add"));
  searchEl.addEventListener("input", () => {
    if (!rawMode) renderList();
  });

  document.addEventListener("click", (e) => {
    if (!openMenuKey) return;
    const tEl = e.target;
    if (tEl instanceof Element && tEl.closest(".admin-vars-menu")) return;
    closeMenus();
  });

  btnToggleValue.addEventListener("click", () => {
    setValueVisibility(valueInput.type === "password");
  });

  dialogForm.addEventListener("submit", (e) => {
    const submitter = e.submitter;
    const value = submitter && "value" in submitter ? submitter.value : "cancel";
    if (value !== "save") {
      closeDialog();
      return;
    }
    e.preventDefault();
    dialogError.hidden = true;
    try {
      const key = keyInput.value.trim();
      const val = valueInput.value;
      if (dialogMode?.mode === "edit") {
        upsertVariable(key, val, { renameFrom: dialogMode.key });
      } else {
        const exists = lines.some((it) => it.type === "kv" && it.key === key);
        if (exists) throw new Error(t("admin.env.err.exists", { key }));
        upsertVariable(key, val);
      }
      closeDialog();
      if (rawMode) syncRawFromLines();
      else renderList();
    } catch (err) {
      dialogError.textContent = err instanceof Error ? err.message : String(err);
      dialogError.hidden = false;
    }
  });

  form.addEventListener("submit", () => {
    if (!rawMode && listDirty) syncRawFromLines();
    rawEl.name = "content";
  });

  window.addEventListener("aa:lang", () => {
    if (rawMode) {
      btnRaw.textContent = t("admin.env.list");
    } else {
      btnRaw.textContent = t("admin.env.raw");
      renderList();
    }
  });

  // Boot
  initTheme();
  if (window.AA_I18N) window.AA_I18N.initLang();

  const initial = readInitial();
  const normalized = initial.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  rawEl.value = normalized && !normalized.endsWith("\n") ? normalized + "\n" : normalized;
  lines = parseEnv(rawEl.value);
  listDirty = false;

  setRawMode(false);
  applyI18n(document);
})();
