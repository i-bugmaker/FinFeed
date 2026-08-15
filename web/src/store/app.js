import { defineStore } from 'pinia'

const THEME_KEY = 'finfeed_theme'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: localStorage.getItem(THEME_KEY) || 'light',
    live: false,
    pendingNews: [], // SSE 收到的、尚未并入列表的新条目
    // 按分类记录是否被截断（快讯 flash / 财经文章 article / 舆情 forum）
    pendingTruncated: { flash: false, article: false, forum: false },
    badgeDismissedAt: 0, // 用户手动点击 badge 清除的时间戳，用于冷却期
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
      // 舆情(forum)新闻不在快讯/财经页展示（API 显式分类隔离），进入未读缓冲只会
      // 让角标永远清不掉、点了又出现，故直接忽略。
      const incoming = items.filter((it) => it.category !== 'forum')
      if (!incoming.length) return
      // 去重（按 id）
      const seen = new Set(this.pendingNews.map((n) => n.id))
      for (const it of incoming) if (!seen.has(it.id)) this.pendingNews.unshift(it)
      // 最多暂存 200 条
      if (this.pendingNews.length > 200) this.pendingNews.length = 200
      if (truncated && incoming.length > 0 && incoming[0].category) {
        this.pendingTruncated[incoming[0].category] = true
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
      else this.pendingTruncated = { flash: false, article: false, forum: false }
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
        this.pendingTruncated = { flash: false, article: false, forum: false }
        // 记录手动清除时间，用于冷却期防止 SSE 竞态导致 badge 立即重现
        this.badgeDismissedAt = Date.now()
      }
    },
    setSources(s) {
      this.sources = s
    },
  },
})
