// ECharts 按需引入统一入口
// 整包 `import * as echarts from 'echarts'` 会把全部图表与组件打进产物（约 1MB+），
// 这里仅注册项目实际用到的图表/组件，配合 tree-shaking 显著减小构建体积。
// 新增图表类型时：先在此处 import 并加入 use()，再在各组件中从本模块导入 echarts。
import * as echarts from 'echarts/core'
import {
  BarChart,
  CandlestickChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
} from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  CandlestickChart,
  RadarChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
])

export { echarts }
