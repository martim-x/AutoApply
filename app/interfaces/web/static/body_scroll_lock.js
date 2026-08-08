(() => {
  /** @type {Set<string>} */
  const holders = new Set();
  let savedY = 0;
  /** @type {{ overflow: string, position: string, top: string, left: string, right: string, width: string } | null} */
  let saved = null;

  function applyLock() {
    const body = document.body;
    const html = document.documentElement;
    savedY = window.scrollY || window.pageYOffset || 0;
    saved = {
      overflow: body.style.overflow,
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      right: body.style.right,
      width: body.style.width,
    };
    html.classList.add("modal-open");
    body.classList.add("modal-open");
    body.style.overflow = "hidden";
    // iOS: fixed body + restore scrollY on unlock (overflow:hidden alone still chains).
    body.style.position = "fixed";
    body.style.top = `-${savedY}px`;
    body.style.left = "0";
    body.style.right = "0";
    body.style.width = "100%";
  }

  function releaseLock() {
    const body = document.body;
    const html = document.documentElement;
    html.classList.remove("modal-open");
    body.classList.remove("modal-open");
    if (saved) {
      body.style.overflow = saved.overflow;
      body.style.position = saved.position;
      body.style.top = saved.top;
      body.style.left = saved.left;
      body.style.right = saved.right;
      body.style.width = saved.width;
      saved = null;
    } else {
      body.style.removeProperty("overflow");
      body.style.removeProperty("position");
      body.style.removeProperty("top");
      body.style.removeProperty("left");
      body.style.removeProperty("right");
      body.style.removeProperty("width");
    }
    window.scrollTo(0, savedY);
  }

  function lock(token) {
    const key = token == null ? "_default" : String(token);
    const before = holders.size;
    holders.add(key);
    if (before === 0) applyLock();
  }

  function unlock(token) {
    const key = token == null ? "_default" : String(token);
    if (!holders.has(key)) return;
    holders.delete(key);
    if (holders.size === 0) releaseLock();
  }

  function syncFromModals(nodes) {
    (nodes || []).forEach((el) => {
      if (!el || !el.id) return;
      if (!el.hidden) lock(el.id);
      else unlock(el.id);
    });
  }

  function watchModals(nodes) {
    const list = (nodes || []).filter(Boolean);
    const sync = () => syncFromModals(list);
    list.forEach((el) => {
      new MutationObserver(sync).observe(el, {
        attributes: true,
        attributeFilter: ["hidden"],
      });
    });
    sync();
  }

  window.AA_BODY_SCROLL = { lock, unlock, watchModals };
})();
