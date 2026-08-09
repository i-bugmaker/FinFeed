import { defineStore } from 'pinia'

const THEME_KEY = 'finfeed_theme'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: localStorage.getItem(THEME_KEY) || 'light',
    live: false,
    pendingNews: [], // SSE 收到的、尚未并入列表的新条目
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
    },
    applyTheme() {
      document.documentElement.setAttribute('data-theme', this.theme)
    },
    setLive(v) {
      this.live = v
    },
    pushPending(items) {
      // 去重（按 id）
      const seen = new Set(this.pendingNews.map((n) => n.id))
      for (const it of items) if (!seen.has(it.id)) this.pendingNews.unshift(it)
      // 最多暂存 200 条
      if (this.pendingNews.length > 200) this.pendingNews.length = 200
    },
    takePending() {
      const items = this.pendingNews.slice()
      this.pendingNews = []
      return items
    },
    setSources(s) {
      this.sources = s
    },
  },
})
