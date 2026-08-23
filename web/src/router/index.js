import { createRouter, createWebHashHistory } from 'vue-router'

// Route views are lazy-loaded so specialised features do not enlarge the
// initial news-feed bundle. Each route remains independently deployable.
const FlashView = () => import('../views/FlashView.vue')
const ArticlesView = () => import('../views/ArticlesView.vue')
const DashboardView = () => import('../views/DashboardView.vue')
const SentimentView = () => import('../views/SentimentView.vue')
const FavoritesView = () => import('../views/FavoritesView.vue')
const AiView = () => import('../views/AiView.vue')
const CalendarView = () => import('../views/CalendarView.vue')
const MarketView = () => import('../views/MarketView.vue')
const StyleGuideView = () => import('../views/StyleGuideView.vue')
const EasyTdxView = () => import('../views/EasyTdxView.vue')
const ScreenerView = () => import('../views/ScreenerView.vue')

// 原「新闻流」已拆分为「快讯」与「财经」两个独立模块：
//   - /flash    ：快讯（7×24 实时短消息）
//   - /articles ：财经（长文/深度内容）
const routes = [
  { path: '/', redirect: '/flash' },
  { path: '/flash', name: 'flash', component: FlashView, meta: { title: '快讯' } },
  { path: '/articles', name: 'articles', component: ArticlesView, meta: { title: '财经' } },
  { path: '/sentiment', name: 'sentiment', component: SentimentView, meta: { title: '舆情' } },
  { path: '/calendar', name: 'calendar', component: CalendarView, meta: { title: '财经日历' } },
  { path: '/market', name: 'market', component: MarketView, meta: { title: '行情' } },
  { path: '/favorites', name: 'favorites', component: FavoritesView, meta: { title: '收藏' } },
  { path: '/dashboard', name: 'dashboard', component: DashboardView, meta: { title: '仪表盘' } },
  { path: '/ai', name: 'ai', component: AiView, meta: { title: 'AI 分析' } },
  { path: '/easytdx', name: 'easytdx', component: EasyTdxView, meta: { title: 'easy-tdx' } },
  { path: '/screener', name: 'screener', component: ScreenerView, meta: { title: '智能选股' } },
  { path: '/styleguide', name: 'styleguide', component: StyleGuideView, meta: { title: '设计规范' } },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
