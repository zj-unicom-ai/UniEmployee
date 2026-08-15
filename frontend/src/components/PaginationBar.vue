<!-- 可复用分页组件：封装 Naive UI n-pagination，靠右显示总条数 + 页码 -->
<template>
  <div class="pagination-bar" v-if="total > pageSize">
    <n-pagination
      :page="page"
      :page-size="pageSize"
      :item-count="total"
      :page-sizes="pageSizes"
      :show-size-picker="showSizePicker"
      :prefix="prefix"
      @update:page="onPage"
      @update:page-size="onPageSize"
    />
  </div>
</template>

<script setup>
const props = defineProps({
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  total: { type: Number, default: 0 },
  pageSizes: { type: Array, default: () => [10, 20, 50] },
  showSizePicker: { type: Boolean, default: false },
})

const emit = defineEmits(['update:page', 'update:page-size'])

const prefix = ({ itemCount }) => `共 ${itemCount} 条`

function onPage(p) { emit('update:page', p) }
function onPageSize(s) { emit('update:page-size', s) }
</script>

<style scoped>
.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}
</style>