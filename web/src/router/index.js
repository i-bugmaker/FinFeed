import { createRouter, createWebHashHistory } from 'vue-router'

// Route views are lazy-loaded so specialised features do not enlarge the
// initial news-feed bundle. Each route remains independently deployable.
const FlashView = () => import('../views/FlashView.vue')
const ArticlesView = () => import('../views/ArticlesView.vue')
const DashboardView = () => import('../views/DashboardView.vue')
const SentimentView = () => import('../views/SentimentView.vue')
const FavoritesView = () => import('../views/FavoritesView.vue')
const CalendarView = () => import('../views/CalendarView.vue')
const MarketView = () => import('../views/MarketView.vue')
const StyleGuideView = () => import('../views/StyleGuideView.vue')
const EasyTdxView = () => import('../views/EasyTdxView.vue')
const ScreenerView = () => import('../views/ScreenerView.vue')
const StockMonitorView = () => import('../views/StockMonitorView.vue')
const LimitUpLadderView = () => import('../views/LimitUpLadderView.vue')
const NotificationSettingsView = () => import('../views/NotificationSettingsView.vue')
const MarketHotView = () => import('../views/MarketHotView.vue')

// AI 分析模块（v2.0 重构）：/ai 为布局容器，五个子路由对应
// 工作台 / 分析师 / 研究报告 / 任务中心 / 设置
const AiLayout = () => import('../views/ai/AiLayout.vue')
const WorkbenchView = () => import('../views/ai/WorkbenchView.vue')
const ReportsView = () => import('../views/ai/ReportsView.vue')
const ReportReaderView = () => import('../views/ai/ReportReaderView.vue')
const TasksView = () => import('../views/ai/TasksView.vue')
const SettingsView = () => import('../views/ai/SettingsView.vue')

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
  {
    path: '/ai',
    component: AiLayout,
    meta: { title: 'AI 分析' },
    children: [
      { path: '', name: 'ai', component: WorkbenchView, meta: { title: 'AI 分析' } },
      { path: 'analyst', name: 'ai-analyst', redirect: '/ai' },
      { path: 'reports', name: 'ai-reports', component: ReportsView, meta: { title: '研究报告' } },
      { path: 'reports/:id', name: 'ai-report', component: ReportReaderView, meta: { title: '报告阅读' } },
      { path: 'tasks', name: 'ai-tasks', component: TasksView, meta: { title: '任务中心' } },
      { path: 'settings', name: 'ai-settings', component: SettingsView, meta: { title: 'AI 设置' } },
    ],
  },
  { path: '/easytdx', name: 'easytdx', component: EasyTdxView, meta: { title: 'easy-tdx' } },
  { path: '/screener', name: 'screener', component: ScreenerView, meta: { title: '智能选股' } },
  { path: '/stock-monitor', name: 'stock-monitor', component: StockMonitorView, meta: { title: '股票监控' } },
  { path: '/limitup-ladder', name: 'limitup-ladder', component: LimitUpLadderView, meta: { title: '连板天地' } },
  { path: '/market-hot', name: 'market-hot', component: MarketHotView, meta: { title: '市场热榜' } },
  { path: '/notifications', name: 'notifications', component: NotificationSettingsView, meta: { title: '通知设置' } },
  { path: '/styleguide', name: 'styleguide', component: StyleGuideView, meta: { title: '设计规范' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 多标签页场景下用标题区分页面；meta.title 已定义但此前从未被消费
const BASE_TITLE = document.title || 'FinFeed 实时财经新闻监控'
router.afterEach((to) => {
  const t = to.meta?.title
  document.title = t ? `${t} · FinFeed` : BASE_TITLE
})

export default router
