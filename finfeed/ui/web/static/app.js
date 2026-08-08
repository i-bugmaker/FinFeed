/**
 * FinFeed Shared App Runtime
 * 主题切换 | hash 路由 | 无限滚动 | 片段加载 | SSE 连接 | 工具函数
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'finfeed_theme';
  const THEME_ATTR = 'data-theme';

  window.FF = window.FF || {
    theme: 'light',
    currentView: 'news',
    sse: null,
    fragments: {},
    observers: new Map(),
    toastEl: null,
  };

  /* ------------------------------------------------------------------
     Theme utilities
     ------------------------------------------------------------------ */
  function initTheme() {
    const saved = localStorage.getItem(STORAGE_KEY);
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    setTheme(theme, false);
  }

  function setTheme(theme, save = true) {
    if (!theme || (theme !== 'light' && theme !== 'dark')) theme = 'light';
    document.documentElement.setAttribute(THEME_ATTR, theme);
    window.FF.theme = theme;
    if (save) localStorage.setItem(STORAGE_KEY, theme);
    document.dispatchEvent(new CustomEvent('ff:themechange', { detail: { theme } }));
  }

  function toggleTheme() {
    setTheme(window.FF.theme === 'light' ? 'dark' : 'light');
  }

  /* ------------------------------------------------------------------
     Routing (hash based)
     ------------------------------------------------------------------ */
  function getHash() {
    return (window.location.hash || '#news').replace(/^#/, '') || 'news';
  }

  function initRouter(switchFn) {
    window.FF._switchView = switchFn;
    window.addEventListener('hashchange', () => {
      if (window.FF._switchView) window.FF._switchView(getHash());
    });
    // initial route
    const initial = getHash();
    if (window.FF._switchView) window.FF._switchView(initial);
  }

  function navigate(view) {
    window.location.hash = view;
  }

  /* ------------------------------------------------------------------
     Infinite scroll via IntersectionObserver
     ------------------------------------------------------------------ */
  function observeSentinel(sentinel, onEnter, options) {
    if (!sentinel || !onEnter) return;
    // disconnect previous if same sentinel
    if (window.FF.observers.has(sentinel)) {
      window.FF.observers.get(sentinel).disconnect();
    }
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !sentinel.dataset.loading) {
          sentinel.dataset.loading = '1';
          Promise.resolve(onEnter()).finally(() => {
            delete sentinel.dataset.loading;
          });
        }
      });
    }, Object.assign({ root: null, rootMargin: '200px', threshold: 0 }, options || {}));
    obs.observe(sentinel);
    window.FF.observers.set(sentinel, obs);
    return obs;
  }

  function disconnectObservers() {
    window.FF.observers.forEach((obs) => obs.disconnect());
    window.FF.observers.clear();
  }

  /* ------------------------------------------------------------------
     Fragment loader with script rehydration
     ------------------------------------------------------------------ */
  async function loadFragment(view, url, containerSelector, globalInitName) {
    if (window.FF.fragments[view]) return; // already loaded
    const container = document.querySelector(containerSelector);
    if (!container) return;

    try {
      container.innerHTML = '<div class="loading"><span class="spinner"></span>加载中…</div>';
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const html = await res.text();
      container.innerHTML = html;

      // Rehydrate inline scripts because innerHTML does not execute <script>
      const scripts = container.querySelectorAll('script');
      scripts.forEach((oldScript) => {
        const newScript = document.createElement('script');
        if (oldScript.src) {
          newScript.src = oldScript.src;
          newScript.async = oldScript.async;
        } else {
          newScript.textContent = oldScript.textContent;
        }
        oldScript.parentNode.replaceChild(newScript, oldScript);
      });

      window.FF.fragments[view] = true;

      // call global init if provided
      if (globalInitName && typeof window[globalInitName] === 'function') {
        try { window[globalInitName](); } catch (e) { console.warn('fragment init failed:', e); }
      }
      if (globalInitName && window[globalInitName] && typeof window[globalInitName].init === 'function') {
        try { window[globalInitName].init(); } catch (e) { console.warn('fragment init failed:', e); }
      }
    } catch (err) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">加载失败</div><p>请检查网络或服务状态</p></div>';
      console.error('loadFragment', view, err);
    }
  }

  /* ------------------------------------------------------------------
     SSE
     ------------------------------------------------------------------ */
  function connectSSE(handlers, options) {
    if (!window.EventSource) return;
    if (window.FF.sse) window.FF.sse.close();

    const sse = new EventSource('/api/events');
    window.FF.sse = sse;

    sse.onopen = () => {
      if (options && options.onOpen) options.onOpen();
    };

    // support both per-event handlers and fallback onmessage
    if (handlers && typeof handlers === 'object') {
      Object.keys(handlers).forEach(evt => {
        if (evt === 'error') return; // handled below
        sse.addEventListener(evt, (ev) => {
          let data = null;
          try { data = JSON.parse(ev.data); } catch (e) { data = ev.data; }
          handlers[evt](data, ev);
        });
      });
    } else if (typeof handlers === 'function') {
      sse.onmessage = (ev) => {
        let data = null;
        try { data = JSON.parse(ev.data); } catch (e) { data = ev.data; }
        handlers(data);
      };
    }

    sse.onerror = () => {
      if (handlers && typeof handlers === 'object' && handlers.error) handlers.error(sse);
      if (options && options.onError) options.onError(sse);
    };

    return sse;
  }

  function disconnectSSE() {
    if (window.FF.sse) {
      window.FF.sse.close();
      window.FF.sse = null;
    }
  }

  /* ------------------------------------------------------------------
     Lazy image loader (native lazy + fade)
     ------------------------------------------------------------------ */
  function lazyImages(root = document) {
    const imgs = root.querySelectorAll('img[data-src]');
    imgs.forEach((img) => {
      img.setAttribute('src', img.dataset.src);
      img.removeAttribute('data-src');
      if (!img.hasAttribute('loading')) img.setAttribute('loading', 'lazy');
      img.addEventListener('load', () => { img.style.opacity = '1'; });
      img.style.opacity = '0';
      img.style.transition = 'opacity 200ms ease';
    });
  }

  /* ------------------------------------------------------------------
     Toast
     ------------------------------------------------------------------ */
  function toast(message, type = 'info', duration = 3000) {
    if (!window.FF.toastEl) {
      window.FF.toastEl = document.createElement('div');
      window.FF.toastEl.className = 'toast-stack';
      document.body.appendChild(window.FF.toastEl);
    }
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    window.FF.toastEl.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 200);
    }, duration);
  }

  /* ------------------------------------------------------------------
     Date / time helpers
     ------------------------------------------------------------------ */
  function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const pad = (n) => String(n).padStart(2, '0');
    if (isToday) {
      return `今天 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
    return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function debounce(fn, wait = 200) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ------------------------------------------------------------------
     API helpers
     ------------------------------------------------------------------ */
  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  }

  async function getJSON(url) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  }

  /* ------------------------------------------------------------------
     Export public API
     ------------------------------------------------------------------ */
  Object.assign(window.FF, {
    initTheme,
    setTheme,
    toggleTheme,
    getHash,
    initRouter,
    navigate,
    observeSentinel,
    disconnectObservers,
    loadFragment,
    connectSSE,
    disconnectSSE,
    lazyImages,
    toast,
    formatTime,
    debounce,
    escapeHtml,
    postJSON,
    getJSON,
  });

  // Auto-init theme
  initTheme();
})();
