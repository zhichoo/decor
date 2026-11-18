(() => {
  "use strict";

  const config = window.DecorThemeConfig || {};
  const base = new URL(".", document.currentScript.src);
  const catalog = new Map((config.themes || []).map((theme) => [theme.id, theme]));
  if (!catalog.has("original")) catalog.set("original", { id: "original", label: "原版", stylesheets: [] });
  const storageKey = config.storageKey || "decor.theme.v1";
  let current = "original";
  let generation = 0;
  let activeSheets = [];
  let cancelPending = [];
  let loading = false;
  let message = "";
  document.documentElement.dataset.theme = current;

  function renderControls() {
    document.querySelectorAll("[data-theme-options]").forEach((group) => {
      group.setAttribute("aria-busy", String(loading));
      group.querySelectorAll("[data-theme-select]").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.themeSelect === current));
      });
    });
    document.querySelectorAll("[data-theme-message]").forEach((element) => { element.textContent = message; });
  }

  function savePreference(id) {
    try { localStorage.setItem(storageKey, id); } catch { /* Storage may be unavailable in private browsing. */ }
    const url = new URL(location.href);
    if (url.searchParams.has("theme")) {
      url.searchParams.set("theme", id);
      history.replaceState(history.state, "", url);
    }
  }

  function capturePosition() {
    const y = window.scrollY;
    if (!y) return () => {};
    // Anchor an existing content row without depending on business state or rerendering it.
    const anchor = [...document.querySelectorAll("main article")].find((element) => {
      const box = element.getBoundingClientRect();
      return box.top >= 0 && box.top < innerHeight && box.height > 0;
    });
    const top = anchor?.getBoundingClientRect().top;
    return () => {
      if (anchor?.isConnected) window.scrollBy(0, anchor.getBoundingClientRect().top - top);
      else window.scrollTo(0, y);
    };
  }

  function prepareSheet(path) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = new URL(path, base).href;
    link.media = "not all";
    link.dataset.decorThemeSheet = "";
    let finish;
    let timer;
    const ready = new Promise((resolve) => {
      finish = (status) => {
        clearTimeout(timer);
        link.onload = link.onerror = null;
        if (status !== "loaded") link.remove();
        resolve({ link, status });
      };
      link.onload = () => finish("loaded");
      link.onerror = () => finish("error");
      timer = setTimeout(() => finish("error"), 8000);
    });
    document.head.append(link);
    return { ready, cancel: () => finish("cancelled"), link };
  }

  async function setTheme(id, { persist = true } = {}) {
    if (!catalog.has(id)) return { applied: false, theme: current, reason: "unknown_theme" };
    const ticket = ++generation;
    cancelPending.forEach((cancel) => cancel());
    cancelPending = [];
    message = "";
    loading = id !== current;
    renderControls();
    const prepared = id === current ? [] : (catalog.get(id).stylesheets || []).map(prepareSheet);
    cancelPending = prepared.map((sheet) => sheet.cancel);
    const sheets = await Promise.all(prepared.map((sheet) => sheet.ready));
    if (ticket !== generation) {
      prepared.forEach((sheet) => sheet.link.remove());
      return { applied: false, theme: current, reason: "superseded" };
    }
    cancelPending = [];
    if (sheets.some((sheet) => sheet.status !== "loaded")) {
      prepared.forEach((sheet) => sheet.link.remove());
      loading = false;
      message = "主题加载失败，已保留当前界面。";
      renderControls();
      return { applied: false, theme: current, reason: "load_failed" };
    }
    if (id !== current) {
      const restore = capturePosition();
      sheets.forEach(({ link }) => { link.media = "all"; });
      document.documentElement.dataset.theme = id;
      activeSheets.forEach((sheet) => sheet.remove());
      activeSheets = sheets.map(({ link }) => link);
      current = id;
      restore();
      document.dispatchEvent(new CustomEvent("decor:themechange", { detail: { theme: id } }));
    }
    loading = false;
    if (persist) savePreference(id);
    renderControls();
    return { applied: true, theme: current };
  }

  function mountControls() {
    document.querySelectorAll("[data-theme-options]").forEach((group) => {
      for (const theme of catalog.values()) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "primary-button small";
        button.dataset.themeSelect = theme.id;
        button.textContent = theme.label;
        button.addEventListener("click", () => { void setTheme(theme.id); });
        group.append(button);
      }
    });
    renderControls();
  }

  let stored = "";
  try { stored = localStorage.getItem(storageKey); } catch { /* The default works without local storage. */ }
  const requested = new URL(location.href).searchParams.get("theme");
  const initial = [requested, stored, config.defaultTheme, "original"].find((id) => catalog.has(id));
  const ready = setTheme(initial, { persist: false });
  window.DecorThemes = Object.freeze({
    get current() { return current; },
    list: () => [...catalog.values()].map(({ id, label }) => ({ id, label })),
    set: setTheme,
    ready,
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountControls, { once: true });
  else mountControls();
})();
