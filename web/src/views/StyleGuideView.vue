<script setup>
import { ref, computed } from 'vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppInput from '../ui/AppInput.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppCheckbox from '../ui/AppCheckbox.vue'
import AppSwitch from '../ui/AppSwitch.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppSegmented from '../ui/AppSegmented.vue'
import AppTabs from '../ui/AppTabs.vue'
import AppPagination from '../ui/AppPagination.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppEmpty from '../ui/AppEmpty.vue'
import AppTooltip from '../ui/AppTooltip.vue'
import { ICONS } from '../ui/icons'

const iconNames = computed(() => Object.keys(ICONS).sort())
const selectedIcon = ref('newspaper')
const btnLoading = ref(false)
const inputValue = ref('')
const checkboxValue = ref(true)
const switchValue = ref(true)
const segmentedValue = ref('day')
const tabValue = ref('line')
const selectValue = ref('')
const dateValue = ref('')
const page = ref(1)
const pageSize = ref(20)

const segmentedOptions = [
  { label: '日', value: 'day' },
  { label: '周', value: 'week' },
  { label: '月', value: 'month' },
]
const tabItems = [
  { label: '折线', value: 'line' },
  { label: '柱状', value: 'bar' },
  { label: '饼图', value: 'pie' },
]
const selectOptions = [
  { label: '选项一', value: 'a' },
  { label: '选项二', value: 'b' },
  { label: '选项三', value: 'c' },
]
</script>

<template>
  <div class="ff-page ff-styleguide">
    <div class="ff-grid">
      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="色彩令牌">
          <div class="ff-styleguide__colors">
            <div class="ff-styleguide__color-group">
              <div class="ff-styleguide__swatch" style="background: var(--ff-bg-canvas)"><span>bg-canvas</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-bg-surface)"><span>bg-surface</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-bg-subtle)"><span>bg-subtle</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-bg-hover)"><span>bg-hover</span></div>
            </div>
            <div class="ff-styleguide__color-group">
              <div class="ff-styleguide__swatch" style="background: var(--ff-text-primary); color: var(--ff-bg-surface)"><span>text-primary</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-text-secondary); color: var(--ff-bg-surface)"><span>text-secondary</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-text-tertiary); color: var(--ff-bg-surface)"><span>text-tertiary</span></div>
            </div>
            <div class="ff-styleguide__color-group">
              <div class="ff-styleguide__swatch" style="background: var(--ff-border)"><span>border</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-border-brand)"><span>border-brand</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-border-up)"><span>border-up</span></div>
              <div class="ff-styleguide__swatch" style="background: var(--ff-border-down)"><span>border-down</span></div>
            </div>
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="字体层级">
          <div class="ff-styleguide__type">
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">display</code>
              <span class="ff-display">实时财经信号中枢</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">h1</code>
              <span class="ff-h1">市场复盘与情绪总览</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">h2</code>
              <span class="ff-h2">板块资金流向</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">h3</code>
              <span class="ff-h3">北向资金净流入</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">h4</code>
              <span class="ff-h4">今日涨停个股</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">lede</code>
              <span class="ff-lede">多源聚合 · 情绪量化 · 事件日历 · AI 解读</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">body</code>
              <span class="ff-body">正文以 15px / 行高 1.6 呈现，保证长文阅读舒适性与信息密度平衡。</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">body-sm</code>
              <span class="ff-body-sm">辅助正文用于列表项与说明文字，字重常规、行高 1.55。</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">caption</code>
              <span class="ff-caption">标注 / 脚注文字，使用三级文本色。</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">label</code>
              <span class="ff-label">栏目眉题 LABEL</span>
            </div>
            <div class="ff-styleguide__type-row">
              <code class="ff-styleguide__type-tag">overline</code>
              <span class="ff-overline">Market Overview</span>
            </div>
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="数据字体">
          <div class="ff-styleguide__num">
            <div class="ff-styleguide__num-row">
              <span class="ff-styleguide__num-name">最新价</span>
              <span class="ff-num ff-num--lg ff-t-up">3,284.56</span>
            </div>
            <div class="ff-styleguide__num-row">
              <span class="ff-styleguide__num-name">涨跌幅</span>
              <span class="ff-num ff-t-up">+2.37%</span>
            </div>
            <div class="ff-styleguide__num-row">
              <span class="ff-styleguide__num-name">成交额</span>
              <span class="ff-num ff-t-down">-1,204.80 亿</span>
            </div>
            <div class="ff-styleguide__num-row">
              <span class="ff-styleguide__num-name">标准</span>
              <span class="ff-num">12,345,678.90</span>
            </div>
            <div class="ff-styleguide__num-row">
              <span class="ff-styleguide__num-name">小号</span>
              <span class="ff-num ff-num--sm">1,024.50</span>
            </div>
            <div class="ff-styleguide__num-row ff-styleguide__num-row--sample">
              <span class="ff-styleguide__num-name">对齐示例</span>
              <span class="ff-styleguide__num-block">
                <span class="ff-num">100.00</span>
                <span class="ff-num">2,584.37</span>
                <span class="ff-num">36.05</span>
                <span class="ff-num">9,999.99</span>
              </span>
            </div>
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12">
        <AppCard title="图标库">
          <div class="ff-styleguide__icons">
            <button
              v-for="name in iconNames"
              :key="name"
              class="ff-styleguide__icon-btn"
              :class="selectedIcon === name && 'ff-styleguide__icon-btn--active'"
              @click="selectedIcon = name"
            >
              <AppIcon :name="name" size="md" />
              <span class="ff-styleguide__icon-name">{{ name }}</span>
            </button>
          </div>
          <div class="ff-styleguide__icon-preview">
            <AppIcon :name="selectedIcon" size="xl" />
            <code>&lt;AppIcon name="{{ selectedIcon }}" /&gt;</code>
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="按钮">
          <div class="ff-styleguide__row">
            <AppButton variant="primary">Primary</AppButton>
            <AppButton variant="secondary">Secondary</AppButton>
            <AppButton variant="tonal">Tonal</AppButton>
            <AppButton variant="ghost">Ghost</AppButton>
            <AppButton variant="danger">Danger</AppButton>
          </div>
          <div class="ff-styleguide__row">
            <AppButton variant="primary" size="sm">Small</AppButton>
            <AppButton variant="primary" size="md">Medium</AppButton>
            <AppButton variant="primary" size="lg">Large</AppButton>
          </div>
          <div class="ff-styleguide__row">
            <AppButton variant="primary" icon="refresh" :loading="btnLoading" @click="btnLoading = !btnLoading">
              {{ btnLoading ? '加载中' : '加载态' }}
            </AppButton>
            <AppButton variant="secondary" disabled>Disabled</AppButton>
            <AppButton variant="primary" icon="plus" />
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="输入组件">
          <div class="ff-styleguide__stack">
            <AppInput v-model="inputValue" label="文本输入" placeholder="请输入…" prefix-icon="search" clearable />
            <AppSelect v-model="selectValue" label="下拉选择" :options="selectOptions" placeholder="请选择" />
            <AppDatePicker v-model="dateValue" label="日期选择" />
            <AppCheckbox v-model="checkboxValue" label="复选框" />
            <AppSwitch v-model="switchValue" label="开关" />
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="状态与徽标">
          <div class="ff-styleguide__row">
            <AppBadge text="默认" />
            <AppBadge text="上涨" variant="up" />
            <AppBadge text="下跌" variant="down" />
            <AppBadge text="警告" variant="warn" />
            <AppBadge text="成功" variant="success" />
            <AppBadge text="品牌" variant="brand" />
          </div>
          <div class="ff-styleguide__row">
            <AppStatus text="正常" tone="success" pulse />
            <AppStatus text="预警" tone="warn" />
            <AppStatus text="熔断" tone="danger" />
            <AppStatus text="离线" tone="neutral" />
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="分段 / 标签">
          <div class="ff-styleguide__stack">
            <AppSegmented v-model="segmentedValue" :options="segmentedOptions" />
            <AppTabs v-model="tabValue" type="line" :items="tabItems" />
            <AppTabs v-model="tabValue" type="pill" :items="tabItems" />
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12">
        <AppCard title="分页">
          <AppPagination
            v-model="page"
            :total="237"
            v-model:page-size="pageSize"
            show-size-changer
          />
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="加载态">
          <AppSkeleton variant="text" :lines="3" />
          <div class="ff-styleguide__row" style="margin-top: var(--ff-space-4)">
            <AppSkeleton variant="circle" width="40px" height="40px" />
            <AppSkeleton variant="title" width="60%" />
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="空状态 / 提示">
          <div class="ff-styleguide__row">
            <AppEmpty title="暂无数据" description="当前列表为空" icon="inbox" />
            <AppTooltip content="这是一个文字提示">
              <AppButton variant="secondary" size="sm">Hover 提示</AppButton>
            </AppTooltip>
          </div>
        </AppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ff-styleguide {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-styleguide__colors {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-styleguide__color-group {
  display: flex;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}

.ff-styleguide__swatch {
  width: 96px;
  height: 64px;
  border-radius: var(--ff-radius-md);
  display: flex;
  align-items: flex-end;
  padding: var(--ff-space-2);
  font-size: var(--ff-fs-xs);
  font-weight: 600;
  border: 1px solid var(--ff-border);
}

.ff-styleguide__type {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}

.ff-styleguide__type-row {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-3);
  padding-bottom: var(--ff-space-2);
  border-bottom: 1px dashed var(--ff-border-subtle);
}

.ff-styleguide__type-row:last-child {
  border-bottom: 0;
}

.ff-styleguide__type-tag {
  flex: 0 0 64px;
  font-family: var(--ff-font-mono);
  font-size: var(--ff-fs-xs);
  font-weight: 600;
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-sm);
  padding: 2px 6px;
  text-align: center;
  line-height: 1.4;
}

.ff-styleguide__num {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-styleguide__num-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ff-space-3);
}

.ff-styleguide__num-name {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-weight: 500;
}

.ff-styleguide__num-row--sample {
  flex-direction: column;
  align-items: stretch;
  gap: var(--ff-space-2);
  padding-top: var(--ff-space-2);
  border-top: 1px solid var(--ff-border);
}

.ff-styleguide__num-block {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: var(--ff-fs-data);
}

.ff-styleguide__icons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-1);
  margin-bottom: var(--ff-space-4);
}

.ff-styleguide__icon-btn {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 64px;
  gap: var(--ff-space-1);
  padding: var(--ff-space-2);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  cursor: pointer;
  transition: border-color var(--ff-dur-fast), background var(--ff-dur-fast);
}

.ff-styleguide__icon-btn:hover,
.ff-styleguide__icon-btn--active {
  border-color: var(--ff-border-brand);
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}

.ff-styleguide__icon-name {
  font-size: var(--ff-fs-micro);
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.ff-styleguide__icon-preview {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-4);
  border: 1px dashed var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
}

.ff-styleguide__row {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--ff-space-3);
}

.ff-styleguide__stack {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

/* ── 移动端适配（D4）── */
@media (max-width: 768px) {
  .ff-styleguide__colors {
    flex-wrap: wrap;
  }
  .ff-styleguide__swatch {
    width: 72px;
    height: 52px;
  }
  .ff-styleguide__color-group {
    flex: 1 1 100%;
  }
}
</style>
