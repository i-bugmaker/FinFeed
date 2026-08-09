import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
import {
  AppIcon, AppLogo, AppButton, AppInput, AppSelect, AppDatePicker,
  AppCheckbox, AppSwitch, AppModal, AppDrawer, AppPagination,
  AppSegmented, AppTabs, AppTooltip, AppSkeleton, AppEmpty,
  AppCard, AppBadge, AppStatus,
} from './ui'

const app = createApp(App)
app.use(createPinia())
app.use(router)

// 全局注册通用 UI 组件
const uiComponents = {
  AppIcon, AppLogo, AppButton, AppInput, AppSelect, AppDatePicker,
  AppCheckbox, AppSwitch, AppModal, AppDrawer, AppPagination,
  AppSegmented, AppTabs, AppTooltip, AppSkeleton, AppEmpty,
  AppCard, AppBadge, AppStatus,
}
for (const [name, comp] of Object.entries(uiComponents)) {
  app.component(name, comp)
}

app.mount('#app')
