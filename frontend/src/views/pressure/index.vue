<template>
  <section class="page" data-module="pressure">
    <header class="page-head">
      <div>
        <h2>压力监测管理</h2>
        <p class="page-desc">维护压力记录，围绕监测编号、监测点位、监测时段、平均压力做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记压力记录</button>
        <button class="btn" type="button" :disabled="loading" @click="exportRows">另存当前范围清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>监测编号</span>
        <input v-model="keyword" placeholder="按监测编号检索" />
      </label>
      <label class="filter-item">
        <span>监测点位</span>
        <input v-model="point" placeholder="按监测点位缩小范围" />
      </label>
      <label class="filter-item">
        <span>监测时段（起）</span>
        <input v-model="periodStart" type="date" />
      </label>
      <label class="filter-item">
        <span>监测时段（止）</span>
        <input v-model="periodEnd" type="date" />
      </label>
      <label class="filter-item">
        <span>监测状态</span>
        <select v-model="status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn primary" type="submit" :disabled="loading">查询</button>
      <!-- 重置只回到第一页：当前筛选条件原样保留，不丢条件 -->
      <button class="btn ghost" type="button" title="回到第一页，保留当前筛选条件" @click="resetToFirstPage">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :id="`pressure-row-${String(row.id)}`"
          :key="String(row.id)"
          :class="{ 'row-focus': String(focusId) === String(row.id) }"
        >
          <td v-for="column in columns" :key="column">{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看明细</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!loading && !errorMessage && !rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ hasFilters ? '当前筛选条件下没有匹配的压力监测记录，请调整监测点位或监测时段' : '暂无压力监测数据，可先登记压力记录' }}
          </td>
        </tr>
        <tr v-if="loading">
          <td :colspan="columns.length + 1" class="empty-state">正在读取压力监测记录…</td>
        </tr>
        <tr v-if="errorMessage">
          <td :colspan="columns.length + 1" class="empty-state">
            <span class="error-text">{{ errorMessage }}</span>
            <button class="btn" type="button" style="margin-left: 8px" @click="reload">重新取数</button>
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条压力监测记录</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="loading || page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="loading || page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </span>
      <span v-if="exportMessage" class="export-text">{{ exportMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/pressure'
const PAGE_SIZE = 8
const columns = ["监测编号", "监测点位", "监测时段", "平均压力", "峰值压力", "越限次数", "采集人员", "监测状态", "归属班组"]
const actions = ["启动采集", "标记越限", "停止监测"]
const statuses = ["待采集", "采集正常", "压力越限", "已停测"]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const errorMessage = ref('')
const exportMessage = ref('')
const focusId = ref('')
const stats = ref([
  { label: '在测点位（同一点位只算一次）', value: 0 },
  { label: '压力越限点位（同一点位只算一次）', value: 0 },
  { label: '今日越限次数', value: 0 },
])

// 筛选条件：与 URL query 双向同步，是「页面重开/退回再进/翻页不丢条件」的唯一数据源
const keyword = ref('')
const point = ref('')
const periodStart = ref('')
const periodEnd = ref('')
const status = ref('')

const hasFilters = computed(() =>
  Boolean(keyword.value.trim() || point.value.trim() || periodStart.value || periodEnd.value || status.value),
)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function readQuery() {
  keyword.value = String(route.query.keyword ?? '')
  point.value = String(route.query.point ?? '')
  periodStart.value = String(route.query.period_start ?? '')
  periodEnd.value = String(route.query.period_end ?? '')
  status.value = String(route.query.status ?? '')
  page.value = Math.max(1, Number(route.query.page) || 1)
  focusId.value = String(route.query.focus ?? '')
}

function buildQuery(): Record<string, string> {
  const query: Record<string, string> = {}
  if (keyword.value.trim()) query.keyword = keyword.value.trim()
  if (point.value.trim()) query.point = point.value.trim()
  if (periodStart.value) query.period_start = periodStart.value
  if (periodEnd.value) query.period_end = periodEnd.value
  if (status.value) query.status = status.value
  query.page = String(page.value)
  query.size = String(PAGE_SIZE)
  return query
}

// 只把当前条件写进 URL，清空的字段也会从 URL 移除
function syncUrl() {
  const query: Record<string, string> = buildQuery()
  if (focusId.value) query.focus = focusId.value
  void router.replace({ path: route.path, query })
}

async function reload() {
  loading.value = true
  errorMessage.value = ''
  const token = Symbol('request')
  ;(reload as unknown as { token?: symbol }).token = token
  const query = new URLSearchParams(buildQuery()).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error(`压力记录列表读取失败（HTTP ${response.status}），请重新取数`)
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    // 只接受最后一次请求的结果，旧一批数据不许顶上来
    if ((reload as unknown as { token?: symbol }).token !== token) return
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (focusId.value) {
      setTimeout(() => {
        document.getElementById(`pressure-row-${focusId.value}`)?.scrollIntoView({ block: 'center' })
      }, 0)
    }
  } catch (error) {
    if ((reload as unknown as { token?: symbol }).token !== token) return
    // 取数失败：清空上一批旧数据，提示并允许重试；保留已经填好的筛选条件
    rows.value = []
    total.value = 0
    errorMessage.value = error instanceof Error ? error.message : '压力监测列表读取失败，请重新取数'
  } finally {
    if ((reload as unknown as { token?: symbol }).token === token) loading.value = false
  }
}

// URL 是条件的唯一来源：首次进入与 query 变化都从这里同步表单并重新取数
watch(
  () => route.query,
  () => {
    readQuery()
    void reload()
  },
  { immediate: true },
)

function applyFilters() {
  page.value = 1
  focusId.value = ''
  syncUrl()
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  syncUrl()
}

function resetToFirstPage() {
  // 不清除已填条件，仅回到第一页重新查询
  page.value = 1
  syncUrl()
}

function openDetail(row: Row) {
  const query: Record<string, string> = { point: String(row['监测点位'] ?? '') }
  // 把列表当前条件完整带给明细页，明细按同一口径取数，返回时也能原样恢复
  if (keyword.value.trim()) query.keyword = keyword.value.trim()
  if (periodStart.value) query.period_start = periodStart.value
  if (periodEnd.value) query.period_end = periodEnd.value
  if (status.value) query.status = status.value
  query.focus = String(row.id)
  void router.push({ path: '/pressure/detail', query })
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = (await response.json()) as Record<string, number>
    stats.value[0].value = data.active_points ?? 0
    stats.value[1].value = data.overlimit_points ?? 0
    stats.value[2].value = data.today_overlimit ?? 0
  } catch {
    // 看板统计失败不影响列表，保留 0
  }
}

async function exportRows() {
  exportMessage.value = ''
  loading.value = true
  // 另存范围与列表当前范围完全一致：同样的条件、同一口径，只是不分页取全量
  const query = buildQuery()
  delete query.page
  delete query.size
  const qs = new URLSearchParams(query).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${qs}`)
    if (!response.ok) {
      throw new Error(`另存失败（HTTP ${response.status}），请重试`)
    }
    const payload = (await response.json()) as { total?: number }
    if ((payload.total ?? -1) !== total.value) {
      throw new Error('另存范围与列表当前范围条数不一致，请重新取数后再试')
    }
    const blob = await new Response(JSON.stringify(payload, null, 2)).blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '')
    link.href = url
    link.download = `压力监测清单_${stamp}.json`
    link.click()
    URL.revokeObjectURL(url)
    exportMessage.value = `已另存当前范围 ${payload.total} 条记录`
  } catch (error) {
    exportMessage.value = error instanceof Error ? error.message : '另存失败，请重试'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  errorMessage.value = '压力记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '压力监测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力监测操作失败'
  }
}

onMounted(loadStats)
</script>

<style scoped>
.pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.export-text {
  color: #1f6feb;
}
.row-focus {
  background: #fff7e6;
}
.filter-item select {
  padding: 4px 6px;
}
</style>
