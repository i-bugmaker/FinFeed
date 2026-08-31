/* THS F10 Web — 自定义 UI 组件库
 * 全部组件手写实现，不依赖任何 UI 框架与原生控件外观：
 *   toast()            轻提示（带进度条与类型色）
 *   modal()            模态弹窗（遮罩模糊、缩放入场、Esc/点外关闭）
 *   menu()             浮层下拉菜单（自动翻转定位）
 *   segmented()        滑块式分段选择器
 *   CScroll            覆盖式自定义滚动条（拖拽拇指、悬停显隐）
 */
(function () {
  "use strict";

  const el = (html) => {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  };
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------------------------------------------------------------- 提示 */
  const TOAST_ICONS = {
    info: "info",
    success: "check",
    error: "alert",
    warn: "alert",
  };
  const toastsBox = () => document.getElementById("toasts");

  function toast({ msg, type = "info", timeout = 3200 }) {
    const box = toastsBox();
    if (!box) return;
    const node = el(`
      <div class="toast t-${type}" role="status">
        <span class="toast-icn">${ICONS[TOAST_ICONS[type]] || ICONS.info}</span>
        <span class="toast-msg">${esc(msg)}</span>
        <button class="toast-x" aria-label="关闭">${ICONS.close}</button>
        <i class="toast-bar" style="animation-duration:${timeout}ms"></i>
      </div>`);
    const kill = () => {
      node.classList.add("out");
      setTimeout(() => node.remove(), 240);
    };
    node.querySelector(".toast-x").addEventListener("click", kill);
    box.appendChild(node);
    if (timeout > 0) setTimeout(kill, timeout);
    // 限制数量
    while (box.children.length > 5) box.firstElementChild.remove();
    return kill;
  }

  /* --------------------------------------------------------------- 弹窗 */
  function modal({ title, body, actions = [], width = 460, onClose }) {
    const root = document.getElementById("layerRoot");
    const node = el(`
      <div class="modal-mask">
        <div class="modal" style="width:min(${width}px, calc(100vw - 48px))" role="dialog" aria-modal="true">
          <div class="modal-head">
            <b>${esc(title)}</b>
            <button class="icon-btn modal-x" aria-label="关闭">${ICONS.close}</button>
          </div>
          <div class="modal-body"></div>
          <div class="modal-foot"></div>
        </div>
      </div>`);

    const bodyEl = node.querySelector(".modal-body");
    if (typeof body === "string") bodyEl.innerHTML = body;
    else if (body) bodyEl.appendChild(body);

    const foot = node.querySelector(".modal-foot");
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      document.removeEventListener("keydown", onKey);
      node.classList.add("out");
      setTimeout(() => node.remove(), 180);
      onClose && onClose();
    };
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
      }
    };

    for (const a of actions) {
      const btn = el(
        `<button class="btn ${a.kind || "ghost"}">${esc(a.label)}</button>`);
      btn.addEventListener("click", () => {
        const keep = a.onClick ? a.onClick(node) : undefined;
        if (keep !== false) close();
      });
      foot.appendChild(btn);
    }
    if (!actions.length) foot.remove();

    node.querySelector(".modal-x").addEventListener("click", close);
    node.addEventListener("pointerdown", (e) => {
      if (e.target === node) close();
    });
    document.addEventListener("keydown", onKey);
    root.appendChild(node);
    requestAnimationFrame(() => node.classList.add("in"));
    const focusable = node.querySelector("button, [href], input");
    focusable && focusable.focus();
    return { close, el: node };
  }

  /* ----------------------------------------------------------- 浮层菜单 */
  let openMenu = null;
  function closeMenu() {
    if (openMenu) {
      openMenu.remove();
      openMenu = null;
      document.removeEventListener("pointerdown", menuOutside, true);
      document.removeEventListener("keydown", menuKey, true);
    }
  }
  function menuOutside(e) {
    if (openMenu && !openMenu.contains(e.target)) closeMenu();
  }
  function menuKey(e) {
    if (e.key === "Escape") closeMenu();
  }

  function menu(items, anchor) {
    closeMenu();
    const node = el(`<div class="pop-menu" role="menu"></div>`);
    for (const it of items) {
      if (it.sep) {
        node.appendChild(el(`<div class="pop-sep"></div>`));
        continue;
      }
      const item = el(`
        <button class="pop-item${it.disabled ? " is-disabled" : ""}${it.danger ? " is-danger" : ""}" role="menuitem">
          ${it.icon ? `<span class="pop-icn">${ICONS[it.icon] || ""}</span>` : ""}
          <span class="pop-label">${esc(it.label)}</span>
          ${it.hint ? `<span class="pop-hint">${esc(it.hint)}</span>` : ""}
        </button>`);
      if (!it.disabled) {
        item.addEventListener("click", () => {
          closeMenu();
          it.onClick && it.onClick();
        });
      }
      node.appendChild(item);
    }
    document.body.appendChild(node);
    const r = anchor.getBoundingClientRect();
    const w = node.offsetWidth;
    const h = node.offsetHeight;
    let x = Math.min(r.left, window.innerWidth - w - 12);
    let y = r.bottom + 8;
    if (y + h > window.innerHeight - 12) y = r.top - h - 8;
    node.style.left = `${Math.max(12, x)}px`;
    node.style.top = `${Math.max(12, y)}px`;
    node.classList.add("in");
    openMenu = node;
    document.addEventListener("pointerdown", menuOutside, true);
    document.addEventListener("keydown", menuKey, true);
    return node;
  }

  /* --------------------------------------------------------- 分段选择器 */
  function segmented(container, { options, value, onChange }) {
    container.classList.add("seg");
    container.innerHTML =
      `<span class="seg-thumb"></span>` +
      options
        .map(
          (o, i) =>
            `<button class="seg-opt" data-i="${i}" data-v="${esc(o.value)}" title="${esc(o.tip || o.label)}">
               <span class="seg-icn">${ICONS[o.icon] || ""}</span>${esc(o.label)}
             </button>`
        )
        .join("");
    const thumb = container.querySelector(".seg-thumb");
    const opts = [...container.querySelectorAll(".seg-opt")];

    const sync = () => {
      const idx = Math.max(0, opts.findIndex((o) => o.dataset.v === value));
      opts.forEach((o, i) => o.classList.toggle("on", i === idx));
      const target = opts[idx];
      if (target) {
        thumb.style.width = `${target.offsetWidth}px`;
        thumb.style.transform = `translateX(${target.offsetLeft}px)`;
      }
    };
    opts.forEach((o) =>
      o.addEventListener("click", () => {
        if (o.dataset.v === value) return;
        value = o.dataset.v;
        sync();
        onChange && onChange(value);
      })
    );
    requestAnimationFrame(sync);
    window.addEventListener("resize", sync);
    // 字体加载/初次布局后校正一次
    setTimeout(sync, 120);
    return {
      set(v) { value = v; sync(); },
      sync,
    };
  }

  /* ------------------------------------------------- 覆盖式自定义滚动条 */
  class CScroll {
    constructor(host) {
      this.host = host;
      host.classList.add("cscroll-host");
      const bar = document.createElement("div");
      bar.className = "cscroll";
      bar.innerHTML = `<div class="cscroll-thumb" tabindex="-1"></div>`;
      host.appendChild(bar);
      this.bar = bar;
      this.thumb = bar.querySelector(".cscroll-thumb");
      this.hideTimer = 0;

      this.thumb.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        this.thumb.setPointerCapture(e.pointerId);
        this.startClientY = e.clientY;
        this.startScroll = this.host.scrollTop;
        this.thumb.classList.add("drag");
      });
      this.thumb.addEventListener("pointermove", (e) => {
        if (!this.thumb.classList.contains("drag")) return;
        const track = this.bar.clientHeight;
        const th = this.thumb.offsetHeight;
        const dy = e.clientY - this.startClientY;
        const max = this.host.scrollHeight - this.host.clientHeight;
        const scrollable = Math.max(1, track - th);
        this.host.scrollTop =
          Math.min(max, Math.max(0, this.startScroll + dy * (max / scrollable)));
      });
      this.thumb.addEventListener("pointerup", () => this.thumb.classList.remove("drag"));

      host.addEventListener("scroll", () => this.render(true), { passive: true });
      const ro = new ResizeObserver(() => this.render(false));
      ro.observe(host);
      this._ro = ro;
      // 内容增删后重算拇指尺寸
      this._mo = new MutationObserver(() => this.render(false));
      this._mo.observe(host, { childList: true, subtree: true });
      this.render(false);
    }

    render(show) {
      const { host, bar, thumb } = this;
      const overflow = host.scrollHeight - host.clientHeight > 2;
      bar.style.display = overflow ? "" : "none";
      if (!overflow) return;
      const track = host.clientHeight;
      const th = Math.max(36, (host.clientHeight / host.scrollHeight) * track);
      const y = (host.scrollTop / host.scrollHeight) * track;
      thumb.style.height = `${th}px`;
      thumb.style.transform = `translateY(${Math.min(y, track - th)}px)`;
      if (show) {
        bar.classList.add("show");
        clearTimeout(this.hideTimer);
        this.hideTimer = setTimeout(() => bar.classList.remove("show"), 900);
      }
    }

    destroy() {
      this._ro.disconnect();
      this._mo.disconnect();
      this.bar.remove();
    }
  }

  function attachScroll(el) {
    return el ? new CScroll(el) : null;
  }

  window.UI = { el, esc, toast, modal, menu, segmented, attachScroll };
})();
