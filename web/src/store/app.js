import { defineStore } from 'pinia'

const THEME_KEY = 'finfeed_theme'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: localStorage.getItem(THEME_KEY) || 'light',
    live: false,
    pendingNews: [], // SSE 收到的、尚未并入列表的新条目
    pendingTruncated: { finance: false, forum: false }, // 按分类记录是否被截断
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
      if (truncated && items.length > 0 && items[0].category) {
        this.pendingTruncated[items[0].category] = true
      }
    },
    takePending(category = null) {
      let items
      if (category) {
        items = this.pendingNews.filter((n) => n.category === category)
        this.pendingNews = this.pendingNews.filter((n) => n.category !== category)
      } else {
        items = this.pendingNews.slice()
        this.pendingNews = []
      }
      const truncated = category
        ? this.pendingTruncated[category]
        : Object.values(this.pendingTruncated).some(Boolean)
      if (category) this.pendingTruncated[category] = false
      else this.pendingTruncated = { finance: false, forum: false }
      return { items, truncated }
    },
    // 标记某分类（或全部）未读缓冲为「已读」并清空，用于用户滚到顶部或
    // 点击「N 条新新闻」提示时。清空后角标自动隐藏，但列表已实时合并过，
    // 不会丢失任何新闻。
    markSeen(category = null) {
      if (category) {
        this.pendingNews = this.pendingNews.filter((n) => n.category !== category)
        if (this.pendingTruncated[category] !== undefined) {
          this.pendingTruncated[category] = false
        }
      } else {
        this.pendingNews = []
        this.pendingTruncated = { finance: false, forum: false }
      }
    },
    setSources(s) {
      this.sources = s
    },
  },
})
