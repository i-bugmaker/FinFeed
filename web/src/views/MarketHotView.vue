<script setup>
/**
 * MarketHotView — 市场热榜（同花顺热榜）独立模块。
 *
 * 行情与量化分组下的人气榜单入口。原嵌于仪表盘，
 * 因体量较大（9 大类目、多子榜 + 日期回看）拆为独立路由，
 * 便于深看与外链分享。
 *
 * 页面遵循 v4.4 设计规范：h1 保留 sr-only 提供文档语义，
 * 可见标题由 ThsHotList 自身的 hero 区承担。
 */
import ThsHotList from '../components/ThsHotList.vue'
</script>

<template>
  <div class="ff-page">
    <h1 class="ff-sr-only">市场热榜</h1>
    <ThsHotList />
  </div>
</template>
