/* THS F10 Web — 内联 SVG 图标库（手绘线性图标，跟随 currentColor） */
(function () {
  const w = (inner) =>
    `<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

  window.ICONS = {
    // 通用
    search: w('<circle cx="11" cy="11" r="7"/><path d="M16.6 16.6 21 21"/>'),
    close: w('<path d="M6 6l12 12M18 6L6 18"/>'),
    chevronDown: w('<path d="M6 9l6 6 6-6"/>'),
    chevronRight: w('<path d="M9 6l6 6-6 6"/>'),
    chevronLeft: w('<path d="M15 6l-6 6 6 6"/>'),
    refresh: w('<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>'),
    download: w('<path d="M12 4v11"/><path d="M6 10l6 6 6-6"/><path d="M5 20h14"/>'),
    copy: w('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
    check: w('<path d="M5 13l4.5 4.5L19 7"/>'),
    sun: w('<circle cx="12" cy="12" r="4"/><path d="M12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M19.1 4.9l-1.6 1.6M6.5 17.5l-1.6 1.6"/>'),
    moon: w('<path d="M20.6 13.2A8.4 8.4 0 1 1 10.8 3.4a6.6 6.6 0 0 0 9.8 9.8z"/>'),
    auto: w('<circle cx="12" cy="12" r="8.6"/><path d="M12 3.4v17.2"/><path d="M12 3.4a8.6 8.6 0 0 1 0 17.2z" fill="currentColor" stroke="none"/>'),
    keyboard: w('<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M17.5 10h.01M7 14h10"/>'),
    menu: w('<path d="M4 7h16M4 12h16M4 17h16"/>'),
    alert: w('<path d="M12 3.5 2.7 19.5h18.6L12 3.5z"/><path d="M12 10v4.5"/><path d="M12 17.5h.01"/>'),
    info: w('<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.8h.01"/>'),
    file: w('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'),
    braces: w('<path d="M8.5 3.5c-2 0-2.5 1-2.5 2.5v2c0 1.5-.7 2.5-2.5 3 1.8.5 2.5 1.5 2.5 3v4c0 1.5.5 2.5 2.5 2.5"/><path d="M15.5 3.5c2 0 2.5 1 2.5 2.5v2c0 1.5.7 2.5 2.5 3-1.8.5-2.5 1.5-2.5 3v4c0 1.5-.5 2.5-2.5 2.5"/>'),
    text: w('<path d="M4 6h16M4 11h16M4 16h10"/>'),
    logo: `<svg viewBox="0 0 48 48" width="1em" height="1em" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="gpLogoBg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#ef6a52"/>
          <stop offset=".55" stop-color="#d5453c"/>
          <stop offset="1" stop-color="#a92c46"/>
        </linearGradient>
        <linearGradient id="gpLogoHi" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#ffffff" stop-opacity=".28"/>
          <stop offset=".4" stop-color="#ffffff" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="46" height="46" rx="12.5" fill="url(#gpLogoBg)"/>
      <rect x="1" y="1" width="46" height="46" rx="12.5" fill="url(#gpLogoHi)"/>
      <g stroke="#ffd9d2" stroke-width="2" stroke-linecap="round" opacity=".85">
        <line x1="14.5" y1="17" x2="14.5" y2="38"/>
        <line x1="24" y1="11" x2="24" y2="33"/>
        <line x1="33.5" y1="7" x2="33.5" y2="27"/>
      </g>
      <rect x="10.5" y="23" width="8" height="10" rx="2" fill="#ffffff" opacity=".82"/>
      <rect x="20" y="16" width="8" height="12" rx="2" fill="#ffffff" opacity=".91"/>
      <rect x="29.5" y="10" width="8" height="13" rx="2" fill="#ffffff"/>
      <circle cx="36.6" cy="12.4" r="2.1" fill="#ffe9b8"/>
    </svg>`,

    // 14 个模块
    mCompany: w('<rect x="4.5" y="3.5" width="15" height="17.5" rx="1.5"/><path d="M8.5 7.5h2M13.5 7.5h2M8.5 11h2M13.5 11h2M8.5 14.5h2M13.5 14.5h2"/><path d="M10.5 21v-3.5h3V21"/>'),
    mLatest: w('<path d="M3 12h3.5l2.5-6 4 12 2.5-6H21"/>'),
    mHolder: w('<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5"/><circle cx="16.8" cy="9.5" r="2.6"/><path d="M15.5 14.7c2.6.2 4.4 1.9 5 4.8"/>'),
    mOperate: w('<path d="M21.2 15.9A9.5 9.5 0 1 1 8.1 2.8"/><path d="M21.5 12A9.5 9.5 0 0 0 12 2.5V12z"/>'),
    mEquity: w('<path d="M12 2.5 2.5 7.5 12 12.5l9.5-5L12 2.5z"/><path d="M2.5 12.5 12 17.5l9.5-5"/><path d="M2.5 17 12 22l9.5-5"/>'),
    mCapital: w('<path d="M17 3.5 21 7.5l-4 4"/><path d="M21 7.5H8"/><path d="M7 20.5 3 16.5l4-4"/><path d="M3 16.5h13"/>'),
    mForecast: w('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.8"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>'),
    mNews: w('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 8.5h6M7 12h10M7 15.5h10"/><path d="M16.5 8.5h.5"/>'),
    mConcept: w('<path d="M12.6 3H5a2 2 0 0 0-2 2v7.6a2 2 0 0 0 .6 1.4l8 8a2 2 0 0 0 2.8 0l6.6-6.6a2 2 0 0 0 0-2.8l-8-8A2 2 0 0 0 12.6 3z"/><path d="M7.5 7.5h.01"/>'),
    mPosition: w('<rect x="2.5" y="7" width="19" height="13.5" rx="2"/><path d="M8.5 7V5.5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2V7"/><path d="M2.5 12.5h19"/>'),
    mFinance: w('<rect x="4.5" y="2.5" width="15" height="19" rx="2"/><path d="M8 6.5h8"/><path d="M8 11h.01M12 11h.01M16 11h.01M8 14.5h.01M12 14.5h.01M16 14.5h.01M8 18h.01M12 18h.01M16 18h.01"/>'),
    mBonus: w('<path d="M20 12v8.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 20.5V12"/><rect x="2.5" y="7.5" width="19" height="4.5" rx="1"/><path d="M12 22V7.5"/><path d="M12 7.5c-1.5 0-4-.7-4-2.75C8 3 9 2.5 10 2.5c2 0 2 3 2 5zM12 7.5c1.5 0 4-.7 4-2.75C16 3 15 2.5 14 2.5c-2 0-2 3-2 5z"/>'),
    mEvent: w('<path d="M18 9a6 6 0 0 0-12 0c0 6.5-2.5 8-2.5 8h17S18 15.5 18 9z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>'),
    mCompare: w('<path d="M18 20V10M12 20V4M6 20v-6"/><path d="M3 20h18"/>'),
  };

  window.icon = (name, cls) =>
    `<span class="icn${cls ? " " + cls : ""}">${ICONS[name] || ""}</span>`;
})();
