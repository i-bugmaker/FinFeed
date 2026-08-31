/* 股谱 — 个股 F10 资料查询（Web 界面）应用逻辑
 * 数据流：搜索建议 -> 选择股票 -> 按模块抓取（后端带缓存）-> 渲染章节卡片
 * 路由：#/600519/8  （股票代码 / 模块序号），支持前进后退与深链接
 */
(function () {
  "use strict";
  const { el, esc, toast, modal, menu, attachScroll } = UI;

  /* ------------------------------------------------------------ 状态 */
  const MODULE_ICONS = [
    "mCompany", "mLatest", "mHolder", "mOperate", "mEquity", "mCapital",
    "mForecast", "mNews", "mConcept", "mPosition", "mFinance", "mBonus",
    "mEvent", "mCompare",
  ];
  const HOT_STOCKS = [
    { kw: "贵州茅台", name: "贵州茅台", code: "600519" },
    { kw: "宁德时代", name: "宁德时代", code: "300750" },
    { kw: "中芯国际", name: "中芯国际", code: "688981" },
    { kw: "招商银行", name: "招商银行", code: "600036" },
    { kw: "比亚迪", name: "比亚迪", code: "002594" },
  ];

  const S = {
    meta: null,
    stock: null,          // {code,name,market_id,type}
    idx: 1,
    cache: new Map(),     // "code:idx" -> {status:'ok'|'error', data?, error?}
    pending: new Map(),   // "code:idx" -> Promise
    themePref: localStorage.getItem("ths_theme") || "auto",
    elapsedTimer: 0,
  };

  const $ = (sel) => document.querySelector(sel);
  const known = () => {
    try { return JSON.parse(localStorage.getItem("ths_known") || "{}"); }
    catch { return {}; }
  };
  const rememberStock = (r) => {
    const k = known();
    k[r.code] = r;
    localStorage.setItem("ths_known", JSON.stringify(k));
  };

  /* ------------------------------------------------------------ 主题 */
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  function applyTheme() {
    const mode = S.themePref === "auto" ? (mq.matches ? "dark" : "light") : S.themePref;
    document.documentElement.dataset.theme = mode;
    const btn = $("#themeBtn");
    if (btn) btn.innerHTML = UI.el(`<span class="icn">${ICONS[mode === "dark" ? "sun" : "moon"]}</span>`).innerHTML;
  }
  function setTheme(pref) {
    S.themePref = pref;
    localStorage.setItem("ths_theme", pref);
    applyTheme();
  }
  mq.addEventListener("change", () => S.themePref === "auto" && applyTheme());

  /* ------------------------------------------------------------- API */
  // 集成到 FinFeed 后接口挂在 /api/f10 下；保留此处便于独立运行时覆盖。
  const API_BASE = window.F10_API_BASE || "/api/f10";
  async function api(path, { timeout = 90000 } = {}) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeout);
    try {
      const res = await fetch(API_BASE + path, { signal: ctrl.signal });
      const data = await res.json();
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    } catch (e) {
      if (e.name === "AbortError") throw new Error("请求超时，请稍后重试");
      throw e;
    } finally {
      clearTimeout(t);
    }
  }
  const apiSearch = (kw) =>
    api(`/search?kw=${encodeURIComponent(kw)}`, { timeout: 15000 }).then((d) => d.results || []);

  function moduleInfo(idx) {
    const m = S.meta?.modules?.[idx];
    return m || { index: idx, name: `模块 ${idx + 1}` };
  }

  /* ------------------------------------------------------------ 路由 */
  function parseHash() {
    const m = location.hash.match(/^#\/(\d{6})(?:\/(\d+))?/);
    return m ? { code: m[1], idx: m[2] != null ? +m[2] : null } : null;
  }
  function syncHash() {
    const h = S.stock ? `#/${S.stock.code}/${S.idx}` : "#/";
    if (location.hash !== h) history.replaceState(null, "", h);
  }
  window.addEventListener("hashchange", async () => {
    const r = parseHash();
    if (!r) return;
    if (r.code !== S.stock?.code) {
      const k = known()[r.code];
      if (k) pickStock(k, r.idx ?? 1, { fromRoute: true });
      else {
        try {
          const rows = await apiSearch(r.code);
          const hit = rows.find((x) => x.code === r.code) || rows[0];
          if (hit) pickStock(hit, r.idx ?? 1, { fromRoute: true });
          else toast({ msg: `未找到股票 ${r.code}`, type: "error" });
        } catch (e) {
          toast({ msg: e.message, type: "error" });
        }
      }
    } else if (r.idx != null && r.idx !== S.idx) {
      S.idx = r.idx;
      renderNav();
      renderCrumb();
      loadModule(S.idx);
    }
  });

  /* ------------------------------------------------------- 搜索建议 */
  const search = {
    box: null, input: null, drop: null, items: [], active: -1,
    debounce: 0, seq: 0,
  };

  function initSearch() {
    search.box = $("#searchBox");
    search.input = $("#searchInput");
    search.drop = $("#suggestBox");

    search.input.addEventListener("input", () => {
      $("#searchClear").hidden = !search.input.value;
      clearTimeout(search.debounce);
      const kw = search.input.value.trim();
      if (!kw) return closeSuggest();
      search.debounce = setTimeout(() => doSuggest(kw), 240);
    });
    search.input.addEventListener("focus", () => {
      search.box.classList.add("focus");
      if (search.input.value.trim() && search.items.length) openDrop();
    });
    search.input.addEventListener("blur", () => search.box.classList.remove("focus"));
    search.input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!search.items.length) return;
        e.preventDefault();
        search.active = (search.active + (e.key === "ArrowDown" ? 1 : -1) + search.items.length) % search.items.length;
        paintActive();
      } else if (e.key === "Enter") {
        if (search.active >= 0 && search.items[search.active]) pickSuggest(search.items[search.active]);
      } else if (e.key === "Escape") {
        closeSuggest();
        search.input.blur();
      }
    });
    $("#searchClear").addEventListener("click", () => {
      search.input.value = "";
      $("#searchClear").hidden = true;
      closeSuggest();
      search.input.focus();
    });
    document.addEventListener("pointerdown", (e) => {
      if (!search.box.contains(e.target) && !search.drop.contains(e.target)) closeSuggest();
    });
  }

  async function doSuggest(kw) {
    const seq = ++search.seq;
    $("#searchSpin").hidden = false;
    try {
      const rows = await apiSearch(kw);
      if (seq !== search.seq) return;
      search.items = rows;
      search.active = rows.length ? 0 : -1;
      renderSuggest(kw);
    } catch {
      if (seq === search.seq) {
        search.items = [];
        renderSuggest(kw, "搜索服务暂不可用");
      }
    } finally {
      if (seq === search.seq) $("#searchSpin").hidden = true;
    }
  }

  function renderSuggest(kw, emptyMsg) {
    const drop = search.drop;
    if (!search.items.length) {
      drop.innerHTML = `<div class="sg-empty">${esc(emptyMsg || `未找到「${kw}」对应的 A 股`)}</div>`;
    } else {
      drop.innerHTML = search.items
        .map((r, i) => `
          <button class="sg-item${i === search.active ? " active" : ""}" data-i="${i}">
            <span class="sg-name">${highlight(esc(r.name), kw)}</span>
            <span class="sg-code">${esc(r.code)}</span>
            <span class="sg-chip">${esc(r.type || "")}</span>
          </button>`)
        .join("");
      drop.querySelectorAll(".sg-item").forEach((n) => {
        n.addEventListener("click", () => pickSuggest(search.items[+n.dataset.i]));
      });
    }
    openDrop();
  }
  function highlight(nameHtml, kw) {
    if (!kw || kw.length > 8) return nameHtml;
    // 名称已转义，这里做纯文本高亮（kw 同样转义）
    const k = esc(kw).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return nameHtml.replace(new RegExp(k, "g"), (m) => `<mark>${m}</mark>`);
  }
  function paintActive() {
    search.drop.querySelectorAll(".sg-item").forEach((n, i) =>
      n.classList.toggle("active", i === search.active));
    const a = search.drop.querySelector(".sg-item.active");
    if (a) a.scrollIntoView({ block: "nearest" });
  }
  function openDrop() { search.drop.hidden = false; }
  function closeSuggest() { search.drop.hidden = true; search.active = -1; }

  function pickSuggest(r) {
    closeSuggest();
    search.input.value = "";
    $("#searchClear").hidden = true;
    search.input.blur();
    pickStock(r, 1);
  }

  /* ------------------------------------------------------- 股票切换 */
  function pickStock(r, idx = 1, { silent = false, fromRoute = false } = {}) {
    S.stock = r;
    S.idx = Math.min(Math.max(idx, 0), 13);
    rememberStock(r);
    if (!fromRoute) syncHash();
    renderStockCard();
    renderNav();
    renderCrumb();
    loadModule(S.idx, { silent });
  }

  /* -------------------------------------------------------- 侧边栏 */
  function renderNav() {
    const nav = $("#moduleNav");
    let list = nav.querySelector(".nav-list");
    if (!list) {
      list = el(`<div class="nav-list"></div>`);
      nav.appendChild(list);
    }
    const loadedKey = (i) => {
      const c = S.cache.get(`${S.stock?.code}:${i}`);
      return c?.status;
    };
    list.innerHTML = S.meta.modules.map((m) => {
      const st = loadedKey(m.index);
      const isActive = !!S.stock && m.index === S.idx;
      const dot = st === "ok"
        ? `<span class="nav-dot ok" title="已加载">${ICONS.check}</span>`
        : st === "error"
          ? `<span class="nav-dot err" title="加载失败">!</span>`
          : "";
      return `
        <button class="nav-item${isActive ? " active" : ""}" data-idx="${m.index}">
          <span class="nav-icn">${ICONS[MODULE_ICONS[m.index]] || ""}</span>
          <span class="nav-name">${esc(m.name)}</span>
          ${dot}
        </button>`;
    }).join("");
    list.querySelectorAll(".nav-item").forEach((n) => {
      n.addEventListener("click", () => {
        S.idx = +n.dataset.idx;
        syncHash();
        renderNav();
        renderCrumb();
        loadModule(S.idx);
        closeSidebarMobile();
      });
    });
  }

  function renderStockCard() {
    const card = $("#stockCard");
    if (!S.stock) { card.hidden = true; return; }
    card.hidden = false;
    card.innerHTML = `
      <div class="sc-top">
        <span class="sc-name" title="${esc(S.stock.name)}">${esc(S.stock.name)}</span>
        <span class="sc-code">${esc(S.stock.code)}</span>
        <span class="chip chip-accent">${esc(S.stock.type || marketName(S.stock.market_id))}</span>
      </div>`;
  }

  function marketName(mid) {
    return { 17: "沪A", 33: "深A", 151: "北A" }[String(mid)] || "A股";
  }

  function renderCrumb() {
    const c = $("#crumb");
    c.innerHTML = S.stock
      ? `<span class="crumb-mod">${esc(moduleInfo(S.idx).name)}</span>
         <span class="crumb-sep">/</span>
         <span class="crumb-stock">${esc(S.stock.name)} <i>${esc(S.stock.code)}</i></span>`
      : "";
  }

  /* ----------------------------------------------------- 模块加载渲染 */
  async function loadModule(idx, { silent = false, refresh = false, force = false } = {}) {
    if (!S.stock) return;
    const key = `${S.stock.code}:${idx}`;
    const cached = S.cache.get(key);
    if (!force && cached?.status === "ok" && !refresh) {
      renderSectionsView(cached.data, idx);
      return;
    }
    if (idx === S.idx) renderSkeleton(idx);
    $("#refreshBtn")?.classList.add("is-busy");

    const run = S.pending.get(key);
    if (run && !refresh && !force) {
      try { const d = await run; renderSectionsView(d, idx); return; } catch { /* fallthrough */ }
    }
    const p = (async () => {
      const d = await api(
        `/module?code=${S.stock.code}&mid=${S.stock.market_id}&idx=${idx}${refresh ? "&refresh=1" : ""}`);
      return d;
    })();
    S.pending.set(key, p);
    try {
      const d = await p;
      S.cache.set(key, { status: "ok", data: d });
      if (idx === S.idx) renderSectionsView(d, idx);
    } catch (e) {
      S.cache.set(key, { status: "error", error: e.message });
      if (idx === S.idx) renderErrorView(e.message, idx);
      if (!silent) toast({ msg: `「${moduleInfo(idx).name}」抓取失败：${e.message}`, type: "error" });
    } finally {
      S.pending.delete(key);
      $("#refreshBtn")?.classList.remove("is-busy");
      renderNav();
      renderStockCard._t && clearTimeout(renderStockCard._t);
      renderStockCard._t = setTimeout(() => renderStockCard(), 50);
    }
  }

  function stopElapsed() {
    if (S.elapsedTimer) { clearInterval(S.elapsedTimer); S.elapsedTimer = 0; }
  }

  function renderSkeleton(idx) {
    stopElapsed();
    const t0 = performance.now();
    $("#page").innerHTML = `
      <div class="page-head">
        <div>
          <h1>${esc(moduleInfo(idx).name)}</h1>
          <p class="ph-sub">${esc(S.stock.name)} <i>${esc(S.stock.code)}</i></p>
        </div>
      </div>
      <div class="sk-hint"><span class="spin sm"></span> 正在抓取「${esc(moduleInfo(idx).name)}」… <b id="skTime">0.0s</b><span class="dim">（首次抓取约 3~10 秒）</span></div>
      ${[1, 2].map(() => `
        <div class="section-card sk">
          <div class="sk-line w30"></div>
          <div class="sk-line w90"></div>
          <div class="sk-line w80"></div>
          <div class="sk-line w60"></div>
        </div>`).join("")}`;
    S.elapsedTimer = setInterval(() => {
      const n = $("#skTime");
      if (n) n.textContent = `${((performance.now() - t0) / 1000).toFixed(1)}s`;
      else stopElapsed();
    }, 100);
  }

  function renderErrorView(msg, idx) {
    stopElapsed();
    $("#page").innerHTML = `
      <div class="page-head">
        <div><h1>${esc(moduleInfo(idx).name)}</h1>
        <p class="ph-sub">${esc(S.stock.name)} <i>${esc(S.stock.code)}</i></p></div>
      </div>
      <div class="state-card error">
        ${UI.el(`<span class="icn big">${ICONS.alert}</span>`).outerHTML}
        <h3>模块抓取失败</h3>
        <p>${esc(msg)}</p>
        <div class="state-actions">
          <button class="btn solid sm" id="retryBtn">重试</button>
        </div>
      </div>`;
    $("#retryBtn").addEventListener("click", () => loadModule(idx, { refresh: true }));
  }

  /* ------------------------------------------------------ 内容渲染器 */
  const escHTML = esc;
  function rich(s) {
    // 有符号百分比着色（红涨绿跌，A 股惯例）
    let t = escHTML(s);
    t = t.replace(/(^|[^\d%])([+-]\d[\d,]*(?:\.\d+)?)\s?%/g,
      (m, p, n) => `${p}<b class="${n.startsWith("-") ? "dn" : "up"}">${n}%</b>`);
    return t;
  }

  function tableBlock(tb) {
    const wrap = el(`<div class="table-wrap"><table class="data-table"></table></div>`);
    const table = wrap.querySelector("table");
    const headRow = document.createElement("tr");
    tb.header.forEach((h, ci) => {
      const th = document.createElement("th");
      th.className = ci === 0 ? "rowhead" : (tb.num?.[ci] ? "num" : "");
      th.innerHTML = rich(h);
      headRow.appendChild(th);
    });
    const thead = document.createElement("thead");
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    tb.rows.forEach((r) => {
      const tr = document.createElement("tr");
      tb.header.forEach((_, ci) => {
        const td = document.createElement("td");
        const v = r[ci] ?? "";
        td.className = (ci === 0 ? "rowhead" : "") + (tb.num?.[ci] ? " num" : "");
        if (v === "--") td.innerHTML = `<span class="dim">--</span>`;
        else td.innerHTML = rich(v);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return wrap;
  }

  function kvBlock(items) {
    const box = el(`<div class="kv-grid"></div>`);
    // 数字层级（控股层级关系）：按层级从高到低展示股权链
    const lvl = items.filter((it) => it.sub && /^\d+$/.test(it.k));
    lvl.sort((a, b) => (+b.k) - (+a.k));
    let lvlDone = false;
    for (const it of items) {
      if (it.sub && /^\d+$/.test(it.k)) {
        if (!lvlDone) {
          for (const l of lvl) {
            box.appendChild(el(`
              <div class="lvl-row">
                <span class="lvl-badge">层级 ${escHTML(l.k)}</span>
                <span class="lvl-name">${escHTML(l.v)}</span>
              </div>`));
          }
          lvlDone = true;
        }
        continue;
      }
      if (it.sub) {
        const note = el(`<div class="note"><span class="note-k"></span><span class="note-v"></span></div>`);
        const kEl = note.querySelector(".note-k");
        if (it.k) kEl.textContent = it.k;
        else kEl.remove();
        note.querySelector(".note-v").innerHTML = rich(it.v).replace(/\n/g, "<br>");
        if (!it.v) note.classList.add("only-k");
        box.appendChild(note);
        continue;
      }
      // 「要点一：xxx」这类自带标签的长键条目，渲染为上下堆叠的便签
      if (/[：:]/.test(it.k) && it.k.length <= 40) {
        const note = el(`<div class="note"><span class="note-k"></span><span class="note-v"></span></div>`);
        note.querySelector(".note-k").textContent = it.k;
        note.querySelector(".note-v").innerHTML = rich(it.v).replace(/\n/g, "<br>");
        if (!it.v) note.classList.add("only-k");
        box.appendChild(note);
        continue;
      }
      box.appendChild(el(`
        <div class="kv-row">
          <span class="kv-k" title="${escHTML(it.k)}">${escHTML(it.k)}</span>
          <span class="kv-v">${rich(it.v).replace(/\n/g, "<br>")}</span>
        </div>`));
    }
    return box;
  }

  function metaItem(it) {
    const segs = it.text.split(/\s{2,}/).filter(Boolean);
    const box = el(`<div class="meta-line"></div>`);
    for (const seg of segs) {
      const m = seg.match(/^([^\s\d][^\d]*?)\s*([\d].*)$/s);
      if (m) {
        box.appendChild(el(`<span class="meta-seg"><i>${escHTML(m[1])}</i><b>${rich(m[2])}</b></span>`));
      } else {
        box.appendChild(el(`<span class="meta-seg"><b>${rich(seg)}</b></span>`));
      }
    }
    return box;
  }

  function textBlock(items) {
    const box = el(`<div class="text-block"></div>`);
    for (const it of items) {
      if (it.t === "p") {
        const p = el(`<p class="tp${(it.indent || 0) >= 6 ? " deep" : ""}">${rich(it.text)}</p>`);
        box.appendChild(p);
      } else if (it.t === "li") {
        box.appendChild(el(`<div class="tli"><i></i><span>${rich(it.text)}</span></div>`));
      } else if (it.t === "h") {
        box.appendChild(el(`<div class="th">${escHTML(it.text)}</div>`));
      } else if (it.t === "meta") {
        box.appendChild(metaItem(it));
      } else if (it.t === "rank") {
        const row = el(`<div class="rank-item"></div>`);
        if (it.rank) {
          row.appendChild(el(`<span class="rank-badge">行业排名 ${escHTML(it.rank)}</span>`));
        }
        row.appendChild(el(`<span class="rank-text">${rich(it.text)}</span>`));
        box.appendChild(row);
      } else if (it.t === "kv") {
        box.appendChild(el(`<div class="tinline"><b>${escHTML(it.k)}</b>${it.v ? `<span>${rich(it.v)}</span>` : ""}</div>`));
      }
    }
    return box;
  }

  function sectionToText(sec) {
    const out = [`■ ${sec.title}`];
    for (const b of sec.blocks) {
      if (b.type === "table") {
        out.push([b.header.join(" | "), ...b.rows.map((r) => r.join(" | "))].join("\n"));
      } else if (b.type === "kv") {
        for (const it of b.items) out.push(`${it.k}${it.v ? "：" + it.v.replace(/\n/g, "；") : ""}`);
      } else if (b.type === "text") {
        for (const it of b.items) {
          if (it.t === "p") out.push(it.text);
          else if (it.t === "li") out.push("· " + it.text);
          else if (it.t === "h") out.push("◆ " + it.text);
          else if (it.t === "meta") out.push(it.text);
          else if (it.t === "kv") out.push(`${it.k}: ${it.v || ""}`);
        }
      }
    }
    return out.join("\n");
  }

  function renderSectionsView(data, idx) {
    stopElapsed();
    const page = $("#page");
    const mod = moduleInfo(idx);
    const when = new Date(data.fetched_at * 1000);
    const hhmm = `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
    const head = el(`
      <div class="page-head">
        <div class="ph-title">
          <h1>${esc(mod.name)}</h1>
          <p class="ph-sub">${esc(S.stock.name)} <i>${esc(S.stock.code)}</i>
            <span class="ph-dot">·</span> ${esc(marketName(S.stock.market_id))}
            <span class="ph-dot">·</span> 抓取于 ${hhmm}
            ${data.cached ? '<span class="chip">缓存</span>' : ""}
          </p>
        </div>
        <div class="ph-pager">
          <button class="icon-btn" id="prevMod" data-tip="上一模块 ["><span class="icn">${ICONS.chevronLeft}</span></button>
          <button class="icon-btn" id="nextMod" data-tip="下一模块 ]"><span class="icn">${ICONS.chevronRight}</span></button>
        </div>
      </div>`);

    page.innerHTML = "";
    page.appendChild(head);
    $("#prevMod").addEventListener("click", () => gotoModule(S.idx - 1));
    $("#nextMod").addEventListener("click", () => gotoModule(S.idx + 1));

    if (!data.sections?.length) {
      page.appendChild(el(`
        <div class="state-card">
          ${UI.el(`<span class="icn big">${ICONS.info}</span>`).outerHTML}
          <h3>该模块暂无可解析内容</h3>
          <p>数据源可能尚未更新，或该股票无此类数据。</p>
        </div>`));
      return;
    }

    const list = el(`<div class="sections"></div>`);
    data.sections.forEach((sec, si) => {
      const card = el(`
        <section class="section-card${sec.level === 3 ? " lv3" : ""}" style="--d:${Math.min(si * 36, 360)}ms">
          <header class="sec-head">
            <h2>${escHTML(sec.title || "详情")}</h2>
            <div class="sec-tools">
              <span class="sec-count">${sec.blocks.filter((b) => b.type === "table").map((b) => `${b.rows.length} 行`).join(" · ")}</span>
              <button class="icon-btn sm sec-copy" data-tip="复制本节">${ICONS.copy}</button>
            </div>
          </header>
          <div class="sec-body"></div>
        </section>`);
      const body = card.querySelector(".sec-body");
      for (const b of sec.blocks) {
        if (b.type === "table") body.appendChild(tableBlock(b));
        else if (b.type === "kv") body.appendChild(kvBlock(b.items));
        else if (b.type === "text") body.appendChild(textBlock(b.items));
        else if (b.type === "div") body.appendChild(el(`<div class="sec-div"></div>`));
      }
      card.querySelector(".sec-copy").addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(sectionToText(sec));
          toast({ msg: `已复制「${sec.title}」`, type: "success" });
        } catch {
          toast({ msg: "复制失败，浏览器未授权剪贴板", type: "error" });
        }
      });
      list.appendChild(card);
    });
    page.appendChild(list);
  }

  function gotoModule(idx) {
    const next = (idx + 14) % 14;
    S.idx = next;
    syncHash();
    renderNav();
    renderCrumb();
    loadModule(S.idx);
  }

  /* ---------------------------------------------------------- 首页 */
  function renderHero() {
    stopElapsed();
    const page = $("#page");
    page.innerHTML = `
      <div class="hero">
        <div class="hero-glow"></div>
        <div class="hero-logo">${ICONS.logo}</div>
        <h1>上市公司资料全景</h1>
        <p>覆盖公司资料、股东研究、财务分析、概念题材等 <b>14 个模块</b></p>
        <div class="hero-chips">
          ${HOT_STOCKS.map((s) => `<button class="chip-btn" data-kw="${esc(s.kw)}">${esc(s.name)}<i>${esc(s.code)}</i></button>`).join("")}
        </div>
        <div class="hero-feats">
          <div>${UI.el(`<span class="icn">${ICONS.mFinance}</span>`).outerHTML}本地缓存 · 秒开重看</div>
          <div>${UI.el(`<span class="icn">${ICONS.download}</span>`).outerHTML}一键导出 Markdown / JSON</div>
        </div>
      </div>`;
    page.querySelectorAll(".chip-btn").forEach((b) => {
      b.addEventListener("click", async () => {
        b.classList.add("is-busy");
        try {
          const rows = await apiSearch(b.dataset.kw);
          const hit = rows.find((x) => x.name === b.dataset.kw) || rows[0];
          if (hit) pickStock(hit, 1);
          else toast({ msg: "未找到该股票", type: "warn" });
        } catch (e) {
          toast({ msg: e.message, type: "error" });
        } finally {
          b.classList.remove("is-busy");
        }
      });
    });
    renderCrumb();
  }

  /* ---------------------------------------------------------- 导出 */
  function stockCacheEntries() {
    if (!S.stock) return [];
    const out = [];
    for (let i = 0; i < 14; i++) {
      const c = S.cache.get(`${S.stock.code}:${i}`);
      if (c?.status === "ok") out.push({ idx: i, name: moduleInfo(i).name, data: c.data });
    }
    return out;
  }

  function sectionToMD(sec) {
    const out = [`### ${sec.title}`, ""];
    for (const b of sec.blocks) {
      if (b.type === "table") {
        out.push("| " + b.header.map((h) => h.replace(/\|/g, "\\|")).join(" | ") + " |");
        out.push("|" + b.header.map(() => "---").join("|") + "|");
        for (const r of b.rows) {
          out.push("| " + b.header.map((_, ci) => (r[ci] ?? "").replace(/\|/g, "\\|")).join(" | ") + " |");
        }
        out.push("");
      } else if (b.type === "kv") {
        for (const it of b.items) out.push(`- **${it.k}**${it.v ? "：" + it.v.replace(/\n/g, "；") : ""}`);
        out.push("");
      } else if (b.type === "text") {
        for (const it of b.items) {
          if (it.t === "p") out.push(it.text);
          else if (it.t === "li") out.push(`- ${it.text}`);
          else if (it.t === "h") out.push(`**◆ ${it.text}**`);
          else if (it.t === "meta") out.push(it.text);
          else if (it.t === "kv") out.push(`**${it.k}**${it.v ? "：" + it.v.replace(/\n/g, "；") : ""}`);
        }
        out.push("");
      }
    }
    return out.join("\n");
  }

  function download(name, content, mime) {
    const blob = new Blob([content], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  function exportMenu(anchor) {
    const entries = stockCacheEntries();
    const n = entries.length;
    menu([
      {
        label: `导出 Markdown（${n} 个模块）`,
        icon: "file",
        disabled: !n,
        hint: ".md",
        onClick() {
          const parts = [`# ${S.stock.name} (${S.stock.code}) — 同花顺 F10 资料`, ""];
          for (const e of entries) {
            parts.push(`## ${e.idx + 1}. ${e.name}`, "");
            for (const sec of e.data.sections) parts.push(sectionToMD(sec));
          }
          download(`F10_${S.stock.code}_${S.stock.name}.md`, parts.join("\n"), "text/markdown");
          toast({ msg: "已导出 Markdown", type: "success" });
        },
      },
      {
        label: `导出 JSON（${n} 个模块）`,
        icon: "braces",
        disabled: !n,
        hint: ".json",
        onClick() {
          const payload = {
            stock: S.stock,
            exported_at: new Date().toISOString(),
            modules: Object.fromEntries(entries.map((e) => [e.name, e.data.sections])),
          };
          download(`F10_${S.stock.code}_${S.stock.name}.json`,
            JSON.stringify(payload, null, 2), "application/json");
          toast({ msg: "已导出 JSON", type: "success" });
        },
      },
      { sep: true },
      {
        label: "复制当前模块文本",
        icon: "copy",
        onClick: async () => {
          const c = S.cache.get(`${S.stock.code}:${S.idx}`);
          if (c?.status !== "ok") return toast({ msg: "当前模块尚未加载", type: "warn" });
          const txt = c.data.sections.map(sectionToText).join("\n\n");
          await navigator.clipboard.writeText(txt);
          toast({ msg: "已复制当前模块文本", type: "success" });
        },
      },
    ], anchor);
  }

  /* ---------------------------------------------------------- 帮助 */
  function helpModal() {
    const rows = [
      ["/", "聚焦搜索框"], ["↑ ↓", "搜索建议切换"], ["Enter", "选中股票"],
      ["[ / ]", "上一个 / 下一个模块"], ["?", "打开本帮助"], ["Esc", "关闭弹层 / 搜索框"],
    ];
    const body = el(`<div class="kbd-list"></div>`);
    for (const [k, d] of rows) {
      body.appendChild(el(`<div class="kbd-row"><span class="kbd">${esc(k)}</span><span>${esc(d)}</span></div>`));
    }
    modal({ title: "键盘快捷键", body, width: 380 });
  }

  /* ---------------------------------------------------------- 移动端 */
  function closeSidebarMobile() {
    document.body.classList.remove("side-open");
  }

  /* ------------------------------------------------------------ 启动 */
  async function boot() {
    initSearch();
    applyTheme();
    attachScroll($("#content"));
    attachScroll($("#moduleNav"));

    $("#themeBtn").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme;
      setTheme(cur === "dark" ? "light" : "dark");
    });
    $("#refreshBtn").addEventListener("click", () => S.stock && loadModule(S.idx, { refresh: true, force: true }));
    $("#exportBtn").addEventListener("click", (e) => exportMenu(e.currentTarget));
    $("#helpBtn").addEventListener("click", helpModal);
    $("#menuBtn").addEventListener("click", () => document.body.classList.add("side-open"));
    $("#sideClose").addEventListener("click", closeSidebarMobile);
    $("#scrim").addEventListener("click", closeSidebarMobile);

    document.addEventListener("keydown", (e) => {
      const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (e.key === "/" && !inField) {
        e.preventDefault();
        search.input.focus();
      } else if (e.key === "?" && !inField) {
        e.preventDefault();
        helpModal();
      } else if (e.key === "[" && !inField) {
        gotoModule(S.idx - 1);
      } else if (e.key === "]" && !inField) {
        gotoModule(S.idx + 1);
      }
    });

    try {
      S.meta = await api("/meta", { timeout: 10000 });
    } catch (e) {
      toast({ msg: `无法连接本地服务：${e.message}`, type: "error" });
      S.meta = { modules: Array.from({ length: 14 }, (_, i) => ({ index: i, name: `模块 ${i + 1}` })) };
    }
    renderNav();
    renderCrumb();

    const r = parseHash();
    if (r) {
      const k = known()[r.code];
      if (k) pickStock(k, r.idx ?? 1, { fromRoute: true });
      else {
        try {
          const rows = await apiSearch(r.code);
          const hit = rows.find((x) => x.code === r.code) || rows[0];
          if (hit) pickStock(hit, r.idx ?? 1, { fromRoute: true });
          else renderHero();
        } catch { renderHero(); }
      }
    } else {
      renderHero();
      setTimeout(() => search.input.focus(), 300);
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
