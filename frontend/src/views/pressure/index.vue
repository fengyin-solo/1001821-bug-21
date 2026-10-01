<template>
  <section class="page" data-module="pressure">
    <header class="page-head">
      <div>
        <h2>压力监测管理</h2>
        <p class="page-desc">维护压力记录，围绕监测编号、监测点位、监测时段、平均压力做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记压力记录</button>
        <button class="btn" type="button" :disabled="loading" @click="exportRows">另存当前清单</button>
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
        <input v-model="filters.keyword" placeholder="按监测编号检索" />
      </label>
      <label class="filter-item">
        <span>监测点位</span>
        <input v-model="filters.point" list="pressure-points" placeholder="按监测点位缩小范围" />
        <datalist id="pressure-points">
          <option v-for="point in pointOptions" :key="point" :value="point" />
        </datalist>
      </label>
      <label class="filter-item">
        <span>监测时段起</span>
        <input v-model="filters.period_start" type="date" />
      </label>
      <label class="filter-item">
        <span>监测时段止</span>
        <input v-model="filters.period_end" type="date" />
      </label>
      <label class="filter-item">
        <span>监测状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit" :disabled="loading">{{ loading ? '查询中…' : '查询' }}</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="activeScopeText" class="scope-text">当前范围：{{ activeScopeText }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>归属片区</th>
          <th>判定口径</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row['归属片区'] ?? '—' }}</td>
          <td>{{ row['判定口径'] ?? '—' }}</td>
          <td class="row-actions">
            <RouterLink class="link" :to="detailLink(row)">查看详情</RouterLink>
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
        <tr v-if="!loading && loadedOnce && !rows.length">
          <td :colspan="columns.length + 3" class="empty-state">
            当前筛选条件下没有匹配的压力监测记录，已保留您填写的监测时段，请调整条件后重试
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条压力监测记录（当前范围与详情、另存清单同口径）</span>
      <span v-if="errorMessage" class="error-text">
        {{ errorMessage }}
        <button class="link" type="button" @click="reload">重新取数</button>
      </span>
    </footer>

    <nav class="pager" v-if="totalPages > 1">
      <button class="btn" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
      <span>第 {{ page }} / {{ totalPages }} 页</span>
      <button class="btn" type="button" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
    </nav>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Filters = {
  keyword: string
  point: string
  period_start: string
  period_end: string
  status: string
}

const ENDPOINT = '/api/pressure'
const STORAGE_KEY = 'pressure:filters'
const PAGE_SIZE = 20

const columns = ['监测编号', '监测点位', '监测时段', '平均压力', '峰值压力', '越限次数', '采集人员', '监测状态']
const actions = ['启动采集', '标记越限', '停止监测']
const statuses = ['待采集', '采集正常', '压力越限', '已停测']
const filterLabels: Record<keyof Filters, string> = {
  keyword: '监测编号',
  point: '监测点位',
  period_start: '时段起',
  period_end: '时段止',
  status: '状态',
}

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadedOnce = ref(false)
const errorMessage = ref('')
let requestSeq = 0
const stats = ref([
  { label: '在测点位（去重）', value: 0 },
  { label: '压力越限点位（去重）', value: 0 },
  { label: '今日越限次数', value: 0 },
])
const pointOptions = ref<string[]>([])
const filters = ref<Filters>({ keyword: '', point: '', period_start: '', period_end: '', status: '' })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const activeScopeText = computed(() => {
  const parts = (Object.keys(filterLabels) as (keyof Filters)[])
    .filter((key) => filters.value[key].trim())
    .map((key) => `${filterLabels[key]}=${filters.value[key].trim()}`)
  return parts.join('，')
})

/** 空白条件不进 query，URL 既是分享链接也是页面重开后的条件来源。 */
function toQuery(overrides: Record<string, string | number> = {}) {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(filters.value)) {
    const text = String(value).trim()
    if (text) {
      query[key] = text
    }
  }
  const nextPage = Number(overrides.page ?? page.value)
  if (nextPage > 1) {
    query.page = String(nextPage)
  }
  return query
}

function persistQuery() {
  const query = toQuery()
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(filters.value))
  // 用 replace 避免每次查询都堆一条浏览器历史。
  void router.replace({ name: 'pressure', query })
}

/** 条件优先取地址栏（详情返回、分享链接），其次取本地缓存（直接重开页面）。 */
function restoreFilters() {
  const cached = window.localStorage.getItem(STORAGE_KEY)
  let saved: Partial<Filters> = {}
  if (cached) {
    try {
      saved = JSON.parse(cached) as Partial<Filters>
    } catch {
      saved = {}
    }
  }
  const read = (key: keyof Filters) => {
    const fromQuery = route.query[key]
    if (typeof fromQuery === 'string') {
      return fromQuery
    }
    return typeof saved[key] === 'string' ? (saved[key] as string) : ''
  }
  filters.value = {
    keyword: read('keyword'),
    point: read('point'),
    period_start: read('period_start'),
    period_end: read('period_end'),
    status: read('status'),
  }
  page.value = Math.max(1, Number(route.query.page) || 1)
}

function applyFilters() {
  page.value = 1
  persistQuery()
  void reload()
}

function resetFilters() {
  // 重置只清空条件并回到第一页，状态本身可预期，不会把用户翻页位置悄悄丢掉。
  filters.value = { keyword: '', point: '', period_start: '', period_end: '', status: '' }
  page.value = 1
  persistQuery()
  void reload()
}

function goPage(next: number) {
  page.value = next
  persistQuery()
  void reload()
}

function detailLink(row: Row) {
  // 把当前范围完整带到详情页，详情按同一口径取数，保证两边条数对得上。
  return { name: 'pressure-detail', params: { id: row.id }, query: toQuery() }
}

function exportRows() {
  // 另存的范围严格跟随列表当前条件，而不是无条件的全量。
  const query = new URLSearchParams(toQuery({ page: 1 })).toString()
  window.open(`${ENDPOINT}/export?${query}`, '_blank')
}

function openCreate() {
  errorMessage.value = '压力记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('压力监测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力监测操作失败'
  }
}

async function reload() {
  // 请求序号：慢的旧响应回来时直接丢弃，不许把上一批旧数据顶上来。
  const seq = ++requestSeq
  loading.value = true
  errorMessage.value = ''
  const query = new URLSearchParams({ ...toQuery(), page: String(page.value), size: String(PAGE_SIZE) }).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error(`压力记录列表读取失败（HTTP ${response.status}），当前展示的仍是上一批数据`)
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    if (seq !== requestSeq) {
      return
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    loadedOnce.value = true
    void loadStats(query)
  } catch (error) {
    if (seq !== requestSeq) {
      return
    }
    // 取数失败：保留已填条件与已有列表，给出可重试的入口。
    errorMessage.value = error instanceof Error ? error.message : '压力监测列表读取失败'
  } finally {
    if (seq === requestSeq) {
      loading.value = false
    }
  }
}

async function loadStats(listQuery: string) {
  // 统计失败不拖垮列表：卡片保持上一批值即可。
  try {
    const response = await request(`${ENDPOINT}/stats?${listQuery}`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as Record<string, number>
    stats.value = [
      { label: '在测点位（去重）', value: payload.active_points ?? 0 },
      { label: '压力越限点位（去重）', value: payload.abnormal_points ?? 0 },
      { label: '今日越限次数', value: payload.today_alarms ?? 0 },
    ]
  } catch {
    // 静默保留旧统计
  }
}

onMounted(() => {
  restoreFilters()
  persistQuery()
  void reload()
  void loadPoints()
})

async function loadPoints() {
  try {
    const response = await request(`${ENDPOINT}/points`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as { items?: Array<Record<string, string>> }
    pointOptions.value = (payload.items ?? []).map((item) => item['监测点位']).filter(Boolean)
  } catch {
    // 点位候选只是辅助输入，拉不到时保留可手输的空列表。
  }
}
</script>
