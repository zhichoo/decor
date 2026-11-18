/* Guide view. Loaded before app.js and called through window.DecorGuides; at call
 * time it reuses app.js helpers (fetchApiJson, renderClaimCard, normalizeKnowledgeClaim,
 * escapeHtml, escapeAttr, setView, activeView) instead of copying card templates. */
(() => {
  "use strict";
  const SLUG = "all-inclusive-company";
  const KIND_LABELS = { points: "要点", pitfalls: "避坑", questions: "要问", documents: "要材料", differing: "不同说法" };
  const state = {
    guide: null, loading: false, error: "", tab: "read",
    openNotes: new Set(), checked: new Set(), tocCollapsed: false, storage: "unknown", copyMessage: "", resetArmed: false,
  };
  let resetTimer = 0;
  let availability = null;

  const view = () => document.querySelector("#guide-view");
  const storageKey = () => `decorGuideChecklist:${SLUG}`;

  function readChecklist() {
    try {
      const raw = window.localStorage.getItem(storageKey());
      const saved = raw ? JSON.parse(raw) : null;
      state.checked = new Set(Array.isArray(saved?.checked) ? saved.checked : []);
      state.storage = "ok";
    } catch {
      state.storage = "unavailable";
    }
  }

  function writeChecklist() {
    if (state.storage !== "ok") return;
    try {
      window.localStorage.setItem(storageKey(), JSON.stringify({ checked: [...state.checked] }));
    } catch {
      state.storage = "unavailable";
    }
  }

  function checklistItems() {
    return (state.guide?.checklist?.groups || []).flatMap((group) => group.subgroups.flatMap((sub) => sub.items));
  }

  /* Inline text: escape first, then a tiny Markdown subset (bold, links, note refs, card tokens). */
  /* Knowledge-card chip icon: a small index card with two text lines. */
  const CLAIM_ICON = '<svg class="guide-claim-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><rect x="1.75" y="3" width="12.5" height="10" rx="1.75" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M4.5 6.5h7M4.5 9.5h4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';

  function inline(text, { notes = true, itemKey = "" } = {}) {
    const guide = state.guide;
    let html = escapeHtml(text || "");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\[([^\]]+)\]\(note:([a-z0-9]+-\d+)\)/g, (_, label, key) =>
      `<button class="guide-note-jump" type="button" data-guide-note-jump="${escapeAttr(key)}">${label}</button>`);
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) =>
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`);
    html = html.replace(/\{\{claim:([A-Za-z0-9_-]+)\}\}/g, (_, id) => {
      const card = guide.claims?.[id];
      return card
        ? `<button class="guide-claim" type="button" data-guide-claim="${escapeAttr(id)}" aria-haspopup="dialog" aria-controls="guide-claims-dialog" aria-expanded="false" title="查看知识卡原文">${CLAIM_ICON}${escapeHtml(card.object_name || "知识卡")}</button>`
        : '<span class="guide-claim-pending">资料待补充</span>';
    });
    if (notes) {
      html = html.replace(/\s?\[\^([a-z0-9]+-\d+)\]/g, (_, key) => {
        const note = guide.notes[key];
        if (!note) return "";
        const open = state.openNotes.has(`${itemKey}|${key}`);
        return `<button class="guide-ref" type="button" data-guide-note="${escapeAttr(key)}" aria-expanded="${open}" aria-label="注释 ${escapeAttr(note.label)}">${escapeHtml(note.label)}</button>`;
      });
    }
    return html;
  }

  function noteRefs(text) {
    return [...String(text || "").matchAll(/\[\^([a-z0-9]+-\d+)\]/g)].map((match) => match[1]);
  }

  function renderNote(key, itemKey) {
    const note = state.guide.notes[key];
    return `<div class="guide-note" data-guide-note-key="${escapeAttr(key)}" data-status="${escapeAttr(note.status)}">
      <span class="guide-note-label">注释 ${escapeHtml(note.label)}</span>
      <div class="guide-note-text">${inline(note.text, { notes: false })}</div>
      ${note.status === "partial" ? '<p class="guide-note-flag">部分知识卡已变化，资料待补充。</p>' : ""}
    </div>`;
  }

  /* An item container carries its own open notes so state survives re-rendering. */
  function item(tag, key, text, extraClass = "") {
    const refs = [...new Set(noteRefs(text))];
    const open = refs.filter((ref) => state.openNotes.has(`${key}|${ref}`));
    return `<${tag} class="guide-item ${extraClass}" data-guide-item="${escapeAttr(key)}">
      <span class="guide-item-text">${inline(text, { itemKey: key })}</span>
      <div class="guide-notes">${open.map((ref) => renderNote(ref, key)).join("")}</div>
    </${tag}>`;
  }

  function renderBlock(block) {
    const label = block.label ? (KIND_LABELS[block.kind] || block.label) : "";
    const head = label ? `<span class="guide-block-label">${escapeHtml(label)}</span>` : "";
    let body = "";
    if (block.type === "paragraph") {
      // A paragraph holding only note references (e.g. under a table) reads as the table's source line.
      const refOnly = !block.label && !String(block.text).replace(/\[\^[a-z0-9]+-\d+\]/g, "").trim();
      body = item("div", block.id, refOnly ? `出处 ${block.text}` : block.text,
        [block.pending ? "is-pending" : "", refOnly ? "guide-ref-only" : ""].join(" "));
    } else if (block.type === "list") {
      const tag = block.ordered ? "ol" : "ul";
      body = `<${tag} class="guide-list">${block.items.map((entry) =>
        item("li", entry.id, entry.text, entry.pending ? "is-pending" : "")).join("")}</${tag}>`;
    } else if (block.type === "table") {
      body = `<div class="guide-table-wrap"><table class="guide-table">
        <thead><tr>${block.header.map((cell) => `<th scope="col">${inline(cell, { notes: false })}</th>`).join("")}</tr></thead>
        <tbody>${block.items.map((row) => `<tr>${row.cells.map((cell, index) =>
          item("td", `${row.id}-c${index}`, cell, row.pending ? "is-pending" : "")).join("")}</tr>`).join("")}</tbody>
      </table></div>`;
    }
    return `<div class="guide-block" data-kind="${escapeAttr(block.kind)}">${head}${body}</div>`;
  }

  function renderSources(sources) {
    if (!sources?.length) return "";
    return `<details class="guide-sources"><summary>本章新增来源（${sources.length}）</summary><ul>${sources.map((source) =>
      `<li><strong>${escapeHtml(source.code)}</strong>：${inline(source.text, { notes: false })}${source.link ? `　${inline(source.link, { notes: false })}` : ""}</li>`).join("")}</ul></details>`;
  }

  function renderRead(guide) {
    const tocLink = (entry, extra = "") => `<button type="button" class="guide-toc-link"${extra} data-guide-section="${escapeAttr(entry.id)}"><span class="guide-toc-num">${escapeHtml(entry.number)}</span><span class="guide-toc-title">${escapeHtml(entry.title)}</span></button>`;
    const toc = guide.chapters.map((chapter, index) => `<li class="guide-toc-chapter${index === 0 ? " is-current" : ""}" data-toc-chapter="${escapeAttr(chapter.id)}">
      ${tocLink(chapter)}
      <ol>${chapter.sections.map((section) => `<li>${tocLink(section)}</li>`).join("")}</ol>
    </li>`).join("");
    const chapters = guide.chapters.map((chapter) => `<section class="guide-chapter" id="guide-${escapeAttr(chapter.id)}" aria-labelledby="guide-${escapeAttr(chapter.id)}-title">
      <h2 id="guide-${escapeAttr(chapter.id)}-title" tabindex="-1"><span class="guide-number">${escapeHtml(chapter.number)}</span>${escapeHtml(chapter.title)}</h2>
      ${chapter.intro.map((text, index) => item("div", `${chapter.id}-intro-${index}`, text, "guide-intro")).join("")}
      ${chapter.sections.map((section) => `<article class="guide-section" id="guide-${escapeAttr(section.id)}" aria-labelledby="guide-${escapeAttr(section.id)}-title">
        <h3 id="guide-${escapeAttr(section.id)}-title" tabindex="-1"><span class="guide-number">${escapeHtml(section.number)}</span>${escapeHtml(section.title)}${section.tags.map((tag) => `<span class="guide-tag">${escapeHtml(tag)}</span>`).join("")}</h3>
        ${section.blocks.map(renderBlock).join("")}
      </article>`).join("")}
      ${renderSources(chapter.sources)}
    </section>`).join("");
    return `<div class="guide-read-layout">
      <button class="guide-toc-toggle" type="button" data-guide-toc-toggle aria-controls="guide-toc" aria-expanded="false">
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M2.5 4h11M2.5 8h11M2.5 12h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        <span>目录</span><span class="guide-toc-toggle-current"></span>
      </button>
      <div class="guide-toc-backdrop" data-guide-toc-close hidden></div>
      <nav class="guide-toc${state.tocCollapsed ? " is-collapsed" : ""}" id="guide-toc" aria-label="指南目录"><details open><summary aria-expanded="${!state.tocCollapsed}" title="收起或展开小节"><span>目录</span><span class="guide-toc-current" aria-hidden="true"></span><button class="guide-toc-close" type="button" data-guide-toc-close aria-label="关闭目录">×</button></summary><ol class="guide-toc-list">${toc}</ol></details></nav>
      <div class="guide-chapters">${chapters}</div>
    </div>`;
  }

  /* 要拿到的材料: one entry per document with what its text must contain (split on ；).
   * Only rows listed in checkable_rows (the contract body) are ticked point by point. */
  function hashText(text) {
    let hash = 5381;
    for (const char of text) hash = ((hash * 33) ^ char.codePointAt(0)) >>> 0;
    return hash.toString(36);
  }

  function documentEntries(documents = state.guide?.checklist?.documents) {
    const header = documents?.header || [];
    const [when, name, contents, source] = ["时间", "材料", "里面要写明", "出处"].map((label) => header.indexOf(label));
    if (when < 0 || name < 0) return null;
    const checkable = new Set(documents.checkable_rows || []);
    return (documents.rows || []).map((row, index) => ({
      when: row[when], name: row[name], checkable: checkable.has(index),
      sections: source < 0 ? [] : String(row[source] || "").match(/\d\.\d/g) || [],
      points: contents < 0 ? [] : String(row[contents] || "").split("；").map((point) => point.trim()).filter(Boolean)
        .map((point) => ({ id: `doc-${hashText(`${row[name]}|${point}`)}`, text: point })),
    }));
  }

  function documentPoints() {
    return (documentEntries() || []).filter((entry) => entry.checkable).flatMap((entry) => entry.points);
  }

  function statusHtml() {
    const items = checklistItems();
    const points = documentPoints();
    const done = items.filter((entry) => state.checked.has(entry.id)).length;
    const pointsDone = points.filter((point) => state.checked.has(point.id)).length;
    return `<strong>已核对 ${done}</strong> / ${items.length}　<span>未核对 ${items.length - done}</span>${points.length
      ? `　<span class="guide-status-docs">合同正文 ${pointsDone} / ${points.length}</span>` : ""}`;
  }

  function sectionLinks(numbers) {
    return numbers.map((number) =>
      `<button type="button" class="guide-section-link" data-guide-section="s${escapeAttr(number)}" aria-label="查看 ${escapeAttr(number)} 节">${escapeHtml(number)}</button>`).join("");
  }

  function renderDocuments(documents) {
    const entries = documentEntries(documents);
    const lead = documents.lead ? `<p class="guide-docs-lead">${inline(documents.lead, { notes: false })}</p>` : "";
    const source = documents.source ? `<p class="guide-docs-source">${inline(documents.source, { notes: false })}</p>` : "";
    if (!entries) {
      return `<section class="guide-check-group"><h2>要拿到的材料</h2>${lead}
        <div class="guide-table-wrap"><table class="guide-table">
          <thead><tr>${documents.header.map((cell) => `<th scope="col">${escapeHtml(cell)}</th>`).join("")}</tr></thead>
          <tbody>${documents.rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody>
        </table></div>${source}</section>`;
    }
    const stages = [];
    for (const entry of entries) {
      const last = stages[stages.length - 1];
      if (last && last.when === entry.when) last.entries.push(entry);
      else stages.push({ when: entry.when, entries: [entry] });
    }
    return `<section class="guide-check-group guide-docs" aria-labelledby="guide-docs-title"><h2 id="guide-docs-title">要拿到的材料</h2>${lead}
      ${stages.map((stage) => `<h3>${escapeHtml(stage.when)}</h3>
        <ul class="guide-doc-list">${stage.entries.map((entry) => `<li class="guide-doc">
          <div class="guide-doc-head"><strong>${escapeHtml(entry.name)}</strong><span class="guide-check-meta">${sectionLinks(entry.sections)}</span></div>
          ${entry.points.length && !entry.checkable ? `<p class="guide-doc-contents"><span>要写明</span>${escapeHtml(entry.points.map((point) => point.text).join("；"))}</p>` : ""}
          ${entry.points.length && entry.checkable ? `<ul class="guide-check-list guide-doc-points" aria-label="${escapeAttr(entry.name)}里面要写明">${entry.points.map((point) => `<li><label>
            <input type="checkbox" data-guide-check="${escapeAttr(point.id)}" ${state.checked.has(point.id) ? "checked" : ""} />
            <span>${escapeHtml(point.text)}</span></label></li>`).join("")}</ul>` : ""}
        </li>`).join("")}</ul>`).join("")}
      ${source}
    </section>`;
  }

  function renderChecklist(guide) {
    const groups = guide.checklist.groups.map((group) => `<section class="guide-check-group" aria-labelledby="guide-${escapeAttr(group.id)}-title">
      <h2 id="guide-${escapeAttr(group.id)}-title">${escapeHtml(group.title)}</h2>
      ${group.subgroups.map((sub) => `${sub.title ? `<h3>${escapeHtml(sub.title)}</h3>` : ""}
        <ul class="guide-check-list">${sub.items.map((entry) => `<li>
          <label><input type="checkbox" data-guide-check="${escapeAttr(entry.id)}" ${state.checked.has(entry.id) ? "checked" : ""} />
            <span>${escapeHtml(entry.text)}</span></label>
          <span class="guide-check-meta">${entry.tags.map((tag) => `<span class="guide-tag">${escapeHtml(tag)}</span>`).join("")}${entry.sections.map((number) =>
            sectionLinks([number])).join("")}</span>
        </li>`).join("")}</ul>`).join("")}
    </section>`).join("");
    return `<div class="guide-checklist">
      <div class="guide-check-toolbar">
        <p role="status">${statusHtml()}</p>
        <div class="guide-check-actions">
          <button class="primary-button small" type="button" data-guide-copy>复制清单</button>
          <button class="primary-button small quiet" type="button" data-guide-reset>${state.resetArmed ? "确认清空？" : "清空勾选"}</button>
        </div>
      </div>
      <p class="guide-check-note">${escapeHtml(guide.checklist.note)}${state.storage === "unavailable" ? "　当前浏览器不能保存勾选，关闭页面后不会保留。" : "　勾选只保存在这台设备的浏览器里。"}</p>
      ${state.copyMessage ? `<p class="guide-copy-message" role="status">${escapeHtml(state.copyMessage)}</p>` : ""}
      ${groups}
      ${renderDocuments(guide.checklist.documents)}
    </div>`;
  }

  function render() {
    const root = view();
    if (!root) return;
    if (!state.guide) {
      root.innerHTML = state.error
        ? `<div class="guide-empty" role="alert"><p>${escapeHtml(state.error)}</p><button class="primary-button small" type="button" data-guide-retry>重试</button></div>`
        : '<p class="guide-empty" role="status">正在加载指南…</p>';
      if (!state.loading && !state.error) load();
      return;
    }
    const guide = state.guide;
    root.innerHTML = `<header class="guide-head">
        <div>
          <h2 class="guide-title">${escapeHtml(guide.title)}</h2>
          <p class="guide-scope">${escapeHtml(guide.scope || "")}</p>
          <p class="guide-notice">${escapeHtml(guide.notice || "")}　内容更新于 ${escapeHtml(guide.updated_at)}。</p>
        </div>
        <div class="guide-tabs" role="tablist" aria-label="指南内容">
          <button type="button" role="tab" id="guide-tab-read" aria-controls="guide-panel" aria-selected="${state.tab === "read"}" data-guide-tab="read">分步阅读</button>
          <button type="button" role="tab" id="guide-tab-checklist" aria-controls="guide-panel" aria-selected="${state.tab === "checklist"}" data-guide-tab="checklist">核对清单</button>
        </div>
      </header>
      <div id="guide-panel" role="tabpanel" aria-labelledby="guide-tab-${state.tab}">${state.tab === "read" ? renderRead(guide) : renderChecklist(guide)}</div>`;
    if (state.tab === "read") {
      setTocDrawer(false);
      window.requestAnimationFrame(updateToc);
    }
  }

  async function load() {
    state.loading = true;
    state.error = "";
    try {
      state.guide = await fetchApiJson(`/guides/${SLUG}`);
      readChecklist();
    } catch (error) {
      state.error = error.status === 404 ? "指南暂未发布。" : "指南加载失败，请稍后重试。";
    } finally {
      state.loading = false;
      if (activeView === "guide") render();
    }
  }

  function scrollToSection(id) {
    const go = () => {
      const target = document.querySelector(`#guide-${CSS.escape(id)}`);
      if (!target) return;
      // Mark the destination at once and pause tracking while the smooth scroll passes other chapters,
      // otherwise the TOC mark would flicker through every chapter on the way.
      markToc(id.startsWith("s") ? id : null, target.closest(".guide-chapter")?.id.slice(6));
      tocLockUntil = performance.now() + 1200;
      target.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
      target.querySelector("h2, h3")?.focus({ preventScroll: true });
    };
    if (state.tab !== "read") {
      state.tab = "read";
      render();
      window.requestAnimationFrame(go);
    } else go();
  }

  /* Narrow screens: the TOC is a drawer on the left, opened from a floating button. */
  const TOC_DRAWER = "(max-width: 1080px)";

  function setTocDrawer(open, { restoreFocus = false } = {}) {
    const root = view();
    const toc = root?.querySelector(".guide-toc");
    if (!toc) return;
    const toggle = root.querySelector("[data-guide-toc-toggle]");
    const drawer = window.matchMedia(TOC_DRAWER).matches;
    open = open && drawer;
    toc.classList.toggle("is-open", open);
    toc.inert = drawer && !open;
    root.querySelector(".guide-toc-backdrop").hidden = !open;
    toggle?.setAttribute("aria-expanded", String(open));
    if (open) {
      toc.querySelector(".guide-toc-link[aria-current]")?.scrollIntoView({ block: "center" });
      toc.querySelector(".guide-toc-close")?.focus({ preventScroll: true });
    } else if (restoreFocus) toggle?.focus({ preventScroll: true });
  }

  window.matchMedia(TOC_DRAWER).addEventListener("change", () => setTocDrawer(false));

  /* TOC follows the reading position: the current chapter and section are marked. */
  let tocFrame = 0;
  let tocLockUntil = 0;

  function markToc(sectionId, chapterId) {
    const toc = view()?.querySelector(".guide-toc");
    if (!toc || !chapterId) return;
    const key = `${chapterId}|${sectionId || ""}`;
    if (toc.dataset.current === key) return;
    toc.dataset.current = key;
    toc.querySelectorAll(".guide-toc-chapter").forEach((entry) => {
      entry.classList.toggle("is-current", entry.dataset.tocChapter === chapterId);
    });
    toc.querySelectorAll(".guide-toc-link[aria-current]").forEach((link) => link.removeAttribute("aria-current"));
    const active = toc.querySelector(`.guide-toc-link[data-guide-section="${CSS.escape(sectionId || chapterId)}"]`);
    active?.setAttribute("aria-current", "location");
    if (active) {
      const text = `${active.querySelector(".guide-toc-num")?.textContent || ""} ${active.querySelector(".guide-toc-title")?.textContent || ""}`;
      view().querySelectorAll(".guide-toc-current, .guide-toc-toggle-current").forEach((label) => { label.textContent = text; });
    }
    // Keep the marked entry inside the TOC's own scroll box without moving the page.
    const box = toc.matches(":hover") ? null : toc;
    if (box && active && box.scrollHeight > box.clientHeight) {
      const boxRect = box.getBoundingClientRect();
      const rect = active.getBoundingClientRect();
      if (rect.top < boxRect.top + 40 || rect.bottom > boxRect.bottom - 40) {
        box.scrollTop += rect.top - boxRect.top - box.clientHeight / 3;
      }
    }
  }

  function updateToc() {
    tocFrame = 0;
    if (activeView !== "guide" || state.tab !== "read" || performance.now() < tocLockUntil) return;
    const root = view();
    if (!root) return;
    const line = (parseFloat(getComputedStyle(root).getPropertyValue("--guide-sticky-offset")) || 0) + 120;
    const passed = (selector) => {
      let current = null;
      for (const element of root.querySelectorAll(selector)) {
        if (element.getBoundingClientRect().top <= line) current = element;
        else break;
      }
      return current;
    };
    const chapter = passed(".guide-chapter") || root.querySelector(".guide-chapter");
    const section = passed(".guide-section");
    const inChapter = section && chapter?.contains(section);
    markToc(inChapter ? section.id.slice(6) : null, chapter?.id.slice(6));
  }

  window.addEventListener("scroll", () => {
    if (!tocFrame) tocFrame = window.requestAnimationFrame(updateToc);
  }, { passive: true });

  function toggleNote(button) {
    const container = button.closest("[data-guide-item]");
    const key = button.dataset.guideNote;
    const itemKey = container.dataset.guideItem;
    const stateKey = `${itemKey}|${key}`;
    const notes = container.querySelector(":scope > .guide-notes");
    const existing = notes.querySelector(`[data-guide-note-key="${CSS.escape(key)}"]`);
    if (state.openNotes.has(stateKey)) {
      state.openNotes.delete(stateKey);
      existing?.remove();
      button.setAttribute("aria-expanded", "false");
    } else {
      state.openNotes.add(stateKey);
      notes.insertAdjacentHTML("beforeend", renderNote(key, itemKey));
      button.setAttribute("aria-expanded", "true");
    }
  }

  function toggleNoteJump(button) {
    const key = button.dataset.guideNoteJump;
    const holder = button.closest(".guide-note-text");
    const existing = holder.querySelector(`:scope > .guide-note-nested[data-key="${CSS.escape(key)}"]`);
    if (existing) {
      existing.remove();
      button.setAttribute("aria-expanded", "false");
      return;
    }
    const note = state.guide.notes[key];
    if (!note) return;
    holder.insertAdjacentHTML("beforeend", `<div class="guide-note-nested" data-key="${escapeAttr(key)}">
      <span class="guide-note-label">${button.textContent}</span>${inline(note.text, { notes: false })}</div>`);
    button.setAttribute("aria-expanded", "true");
  }

  /* Cards open as a non-modal popover next to the clicked chip, so the text around it stays readable. */
  let claimAnchor = null;
  let claimFrame = 0;

  function placeClaim() {
    const dialog = document.querySelector("#guide-claims-dialog");
    if (!dialog?.open || !claimAnchor?.isConnected) return;
    const gap = 8;
    const margin = 16;
    const rect = claimAnchor.getBoundingClientRect();
    const width = Math.min(560, window.innerWidth - 2 * margin);
    const below = window.innerHeight - rect.bottom - gap - margin;
    const above = rect.top - gap - margin;
    const useBelow = below >= 260 || below >= above;
    const room = Math.max(160, useBelow ? below : above);
    dialog.style.width = `${width}px`;
    dialog.style.maxHeight = `${room}px`;
    dialog.style.left = `${Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin)}px`;
    const height = Math.min(dialog.scrollHeight, room);
    dialog.style.top = `${useBelow ? rect.bottom + gap : Math.max(margin, rect.top - gap - height)}px`;
  }

  function closeClaim({ restoreFocus = false } = {}) {
    const dialog = document.querySelector("#guide-claims-dialog");
    if (dialog?.open) dialog.close();
    if (restoreFocus) claimAnchor?.focus({ preventScroll: true });
    claimAnchor?.setAttribute("aria-expanded", "false");
    claimAnchor = null;
  }

  function openClaim(button) {
    const id = button.dataset.guideClaim;
    const card = state.guide.claims?.[id];
    const dialog = document.querySelector("#guide-claims-dialog");
    if (!card || !dialog) return;
    if (dialog.open && claimAnchor === button) return closeClaim();
    closeClaim();
    document.querySelector("#guide-claims-dialog-content").innerHTML =
      renderClaimCard(normalizeKnowledgeClaim(card), { allowDelete: false, showSource: true });
    claimAnchor = button;
    button.setAttribute("aria-expanded", "true");
    dialog.classList.add("is-anchored");
    dialog.show();
    dialog.scrollTop = 0;
    placeClaim();
    dialog.querySelector("button")?.focus({ preventScroll: true });
  }

  document.querySelector("#guide-claims-dialog")?.addEventListener("close", () => {
    claimAnchor?.setAttribute("aria-expanded", "false");
  });

  window.addEventListener("scroll", () => {
    if (claimFrame) return;
    claimFrame = window.requestAnimationFrame(() => { claimFrame = 0; placeClaim(); });
  }, { passive: true });
  window.addEventListener("resize", () => placeClaim());

  document.addEventListener("pointerdown", (event) => {
    const dialog = document.querySelector("#guide-claims-dialog");
    if (!dialog?.open) return;
    // A click on the open card's own chip toggles it in the click handler instead.
    if (dialog.contains(event.target) || event.target.closest?.("[data-guide-claim]") === claimAnchor) return;
    closeClaim();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view()?.querySelector(".guide-toc.is-open")) {
      event.preventDefault();
      return setTocDrawer(false, { restoreFocus: true });
    }
    if (event.key === "Escape" && document.querySelector("#guide-claims-dialog")?.open) {
      event.preventDefault();
      closeClaim({ restoreFocus: true });
    }
  });

  function checklistText() {
    const guide = state.guide;
    const lines = [`${guide.title} · ${guide.checklist.title}`, guide.checklist.note, ""];
    for (const group of guide.checklist.groups) {
      lines.push(`【${group.title}】`);
      for (const sub of group.subgroups) {
        if (sub.title) lines.push(`${sub.title}`);
        for (const entry of sub.items) {
          const refs = entry.sections.length ? `（见 ${entry.sections.join("、")}）` : "";
          lines.push(`${state.checked.has(entry.id) ? "[已核对]" : "[未核对]"} ${entry.text}${refs}`);
        }
      }
      lines.push("");
    }
    const entries = documentEntries();
    if (entries) {
      lines.push("【要拿到的材料】");
      for (const entry of entries) {
        const refs = entry.sections.length ? `（见 ${entry.sections.join("、")}）` : "";
        lines.push(`${entry.when}｜${entry.name}${refs}`);
        if (entry.checkable) {
          for (const point of entry.points) lines.push(`  ${state.checked.has(point.id) ? "[已核对]" : "[未核对]"} ${point.text}`);
        } else if (entry.points.length) {
          lines.push(`  要写明：${entry.points.map((point) => point.text).join("；")}`);
        }
      }
    }
    return lines.join("\n");
  }

  async function copyChecklist() {
    const text = checklistText();
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.append(area);
      area.select();
      try { copied = document.execCommand("copy"); } catch { copied = false; }
      area.remove();
    }
    state.copyMessage = copied ? "已复制到剪贴板。" : "复制失败：浏览器不允许访问剪贴板，请手动选择清单文字复制。";
    render();
    document.querySelector("[data-guide-copy]")?.focus();
  }

  document.addEventListener("click", (event) => {
    // Leaving for a source video closes the card dialog first; app.js handles the navigation.
    if (event.target.closest("#guide-claims-dialog [data-video-id]")) document.querySelector("#guide-claims-dialog")?.close();
  }, true);

  document.addEventListener("click", (event) => {
    if (!event.target.closest("#guide-view")) return;
    const target = event.target;
    const ref = target.closest("[data-guide-note]");
    if (ref) return toggleNote(ref);
    const jump = target.closest("[data-guide-note-jump]");
    if (jump) return toggleNoteJump(jump);
    const claim = target.closest("[data-guide-claim]");
    if (claim) return openClaim(claim);
    if (target.closest("[data-guide-toc-toggle]")) return setTocDrawer(true);
    if (target.closest("[data-guide-toc-close]")) {
      event.preventDefault();  // the close button sits inside <summary>; keep the list expanded
      return setTocDrawer(false, { restoreFocus: true });
    }
    // Wide screens: the summary folds the TOC down to chapter titles instead of hiding it.
    const summary = target.closest(".guide-toc summary");
    if (summary) {
      event.preventDefault();
      if (window.matchMedia(TOC_DRAWER).matches) return;
      state.tocCollapsed = !state.tocCollapsed;
      summary.closest(".guide-toc").classList.toggle("is-collapsed", state.tocCollapsed);
      summary.setAttribute("aria-expanded", String(!state.tocCollapsed));
      return;
    }
    const section = target.closest("[data-guide-section]");
    if (section) {
      if (section.closest(".guide-toc.is-open")) setTocDrawer(false);
      return scrollToSection(section.dataset.guideSection);
    }
    const tab = target.closest("[data-guide-tab]");
    if (tab && tab.dataset.guideTab !== state.tab) {
      state.tab = tab.dataset.guideTab;
      state.copyMessage = "";
      render();
      document.querySelector(`[data-guide-tab="${state.tab}"]`)?.focus();
      return;
    }
    if (target.closest("[data-guide-copy]")) return copyChecklist();
    if (target.closest("[data-guide-reset]")) {
      clearTimeout(resetTimer);
      if (state.resetArmed) {
        state.checked.clear();
        writeChecklist();
        state.resetArmed = false;
      } else {
        state.resetArmed = true;
        resetTimer = setTimeout(() => { state.resetArmed = false; if (activeView === "guide" && state.tab === "checklist") render(); }, 4000);
      }
      render();
      document.querySelector("[data-guide-reset]")?.focus();
      return;
    }
    if (target.closest("[data-guide-retry]")) {
      state.error = "";
      render();
    }
  });

  document.addEventListener("keydown", (event) => {
    const tab = event.target.closest?.("#guide-view [data-guide-tab]");
    if (!tab || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    state.tab = state.tab === "read" ? "checklist" : "read";
    render();
    document.querySelector(`[data-guide-tab="${state.tab}"]`)?.focus();
  });

  document.addEventListener("change", (event) => {
    const box = event.target.closest("#guide-view [data-guide-check]");
    if (!box) return;
    if (box.checked) state.checked.add(box.dataset.guideCheck);
    else state.checked.delete(box.dataset.guideCheck);
    writeChecklist();
    const status = document.querySelector("#guide-view .guide-check-toolbar [role=status]");
    if (status) status.innerHTML = statusHtml();
  });

  /* Hide the entry when no guide is published (e.g. an older public snapshot). */
  async function checkAvailability() {
    try {
      const payload = await fetchApiJson("/guides");
      availability = (payload.guides || []).some((guide) => guide.slug === SLUG);
    } catch {
      availability = false;
    }
    document.querySelectorAll('.nav-item[data-view="guide"]').forEach((button) => { button.hidden = !availability; });
    if (!availability && activeView === "guide") setView("overview", { replaceHistory: true });
  }

  window.addEventListener("DOMContentLoaded", checkAvailability);
  Object.defineProperty(window, "DecorGuides", { value: Object.freeze({ render, isAvailable: () => availability }) });
})();
