import { createRouter, createWebHashHistory } from 'vue-router'
import NewsView from '../views/NewsView.vue'
import DashboardView from '../views/DashboardView.vue'
import SentimentView from '../views/SentimentView.vue'
import FavoritesView from '../views/FavoritesView.vue'
import AiView from '../views/AiView.vue'
import CalendarView from '../views/CalendarView.vue'
import MarketView from '../views/MarketView.vue'
import MarketLiveView from '../views/MarketLiveView.vue'
import CalendarDrillView from '../views/CalendarDrillView.vue'
import StyleGuideView from '../views/StyleGuideView.vue'

const routes = [
  { path: '/', redirect: '/news' },
  { path: '/news', name: 'news', component: NewsView, meta: { title: '新闻流' } },
  { path: '/sentiment', name: 'sentiment', component: SentimentView, meta: { title: '舆情' } },
  { path: '/calendar', name: 'calendar', component: CalendarView, meta: { title: '财经日历' } },
  { path: '/calendar-drill', name: 'calendar-drill', component: CalendarDrillView, meta: { title: '日历下钻' } },
  { path: '/market', name: 'market', component: MarketView, meta: { title: '行情' } },
  { path: '/market-live', name: 'market-live', component: MarketLiveView, meta: { title: '行情直播' } },
  { path: '/favorites', name: 'favorites', component: FavoritesView, meta: { title: '收藏' } },
  { path: '/dashboard', name: 'dashboard', component: DashboardView, meta: { title: '仪表盘' } },
  { path: '/ai', name: 'ai', component: AiView, meta: { title: 'AI 分析' } },
  { path: '/styleguide', name: 'styleguide', component: StyleGuideView, meta: { title: '设计规范' } },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
