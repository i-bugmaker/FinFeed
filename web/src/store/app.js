import { defineStore } from 'pinia'

const THEME_KEY = 'finfeed_theme'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: localStorage.getItem(THEME_KEY) || 'light',
    live: false,
    pendingNews: [], // SSE 收到的、尚未并入列表的新条目
    pendingTruncated: false, // 最近一批 SSE 是否被截断（触发整表刷新）
    sources: [], // 数据源健康
  }),
  actions: {
    initTheme() {
      if (!localStorage.getItem(THEME_KEY)) {
        const prefersDark =
          window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
        this.theme = prefersDark ? 'dark' : 'light'
      }
      this.applyTheme()
    },
    toggleTheme() {
      this.theme = this.theme === 'light' ? 'dark' : 'light'
      localStorage.setItem(THEME_KEY, this.theme)
      this.applyTheme()
      this.animateThemeChange()
    },
    applyTheme() {
      document.documentElement.setAttribute('data-theme', this.theme)
    },
    animateThemeChange() {
      const root = document.documentElement
      root.classList.add('ff-theme-anim')
      if (this._themeTimer) window.clearTimeout(this._themeTimer)
      this._themeTimer = window.setTimeout(() => {
        root.classList.remove('ff-theme-anim')
      }, 360)
    },
    setLive(v) {
      this.live = v
    },
    pushPending(items, truncated = false) {
      // 去重（按 id）
      const seen = new Set(this.pendingNews.map((n) => n.id))
      for (const it of items) if (!seen.has(it.id)) this.pendingNews.unshift(it)
      // 最多暂存 200 条
      if (this.pendingNews.length > 200) this.pendingNews.length = 200
      if (truncated) this.pendingTruncated = true
    },
    takePending() {
      const items = this.pendingNews.slice()
      const truncated = this.pendingTruncated
      this.pendingNews = []
      this.pendingTruncated = false
      return { items, truncated }
    },
    setSources(s) {
      this.sources = s
    },
  },
})
