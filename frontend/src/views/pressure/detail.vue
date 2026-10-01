<template>
  <section class="page" data-module="pressure-detail">
    <header class="page-head">
      <div>
        <h2>压力监测点位明细</h2>
        <p class="page-desc">
          按监测点位与监测时段查看同一口径下的全部记录；历史记录的判定口径与归属班组按登记时快照保留。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="backToList">返回列表</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">当前监测点位</span>
        <strong class="stat-value point-name">{{ point || '—' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">本点位命中记录</span>
        <strong class="stat-value">{{ pointTotal }} 条</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">列表当前口径总记录</span>
        <strong class="stat-value">{{ scopeTotal }} 条</strong>
      </article>
    </div>

    <div class="scope-tip">
      明细与列表使用同一个筛选口径：监测时段 {{ periodStart || '不限' }} ~ {{ periodEnd || '不限' }}、
      状态 {{ status || '全部' }}。在列表按本点位过滤时，两边条数一致（{{ pointTotal }} 条）。
    </div>

    <form class="filter-bar" @submit.prevent="reload">
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
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in detailColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :id="`pressure-row-${String(row.id)}`"
          :key="String(row.id)"
          :class="{ 'row-focus': String(focusId) === String(row.id) }"
        >
          <td v-for="column in detailColumns" :key="column">
            {{ row[column] === '' || row[column] == null ? '—' : row[column] }}
          </td>
        </tr>
        <tr v-if="!loading && !errorMessage && !rows.length">
          <td :colspan="detailColumns.length" class="empty-state">
            该点位在当前监测时段内没有匹配记录；已保留你填写的时段，可调整后再查。
          </td>
        </tr>
        <tr v-if="loading">
          <td :colspan="detailColumns.length" class="empty-state">正在读取点位明细…</td>
        </tr>
        <tr v-if="errorMessage">
          <td :colspan="detailColumns.length" class="empty-state">
            <span class="error-text">{{ errorMessage }}</span>
            <button class="btn" type="button" style="margin-left: 8px" @click="reload">重新取数</button>
          </td>
        </tr>
      </tbody>
    </table>

    <section class="transfer-box">
      <h3>点位归属变更</h3>
      <p class="page-desc">
        变更只对该点位之后新登记的记录生效；上面的历史记录仍保留原归属班组，不会被改写。
      </p>
      <form class="filter-bar" @submit.prevent="transfer">
        <label class="filter-item">
          <span>监测点位</span>
          <input v-model="point" readonly />
        </label>
        <label class="filter-item">
          <span>新归属班组</span>
          <input v-model="newOwner" placeholder="例如：城南抢修班" />
        </label>
        <button class="btn primary" type="submit" :disabled="transferring">确认变更</button>
        <span v-if="transferMessage" :class="transferOk ? 'export-text' : 'error-text'">{{ transferMessage }}</span>
      </form>
      <ul v-if="historyOwners.length" class="history-list">
        <li v-for="item in historyOwners" :key="item['监测编号']">
          {{ item['监测编号'] }}：历史归属保持为「{{ item['归属班组'] }}」
        </li>
      </ul>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/pressure'
const detailColumns = [
  '监测编号', '监测点位', '监测时段', '平均压力', '峰值压力', '越限次数',
  '采集人员', '监测状态', '归属班组', '判定口径', '判定阈值', '判定结论',
]
const statuses = ['待采集', '采集正常', '压力越限', '已停测']

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const pointTotal = ref(0)
const scopeTotal = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const focusId = ref('')

const point = ref('')
const periodStart = ref('')
const periodEnd = ref('')
const status = ref('')

const newOwner = ref('')
const transferring = ref(false)
const transferMessage = ref('')
const transferOk = ref(false)
const historyOwners = ref<Array<Record<string, string>>>([])

function readQuery() {
  point.value = String(route.query.point ?? '')
  periodStart.value = String(route.query.period_start ?? '')
  periodEnd.value = String(route.query.period_end ?? '')
  status.value = String(route.query.status ?? '')
  focusId.value = String(route.query.focus ?? '')
}

function baseQuery(withPoint: boolean): Record<string, string> {
  const query: Record<string, string> = {}
  if (withPoint && point.value.trim()) query.point = point.value.trim()
  if (periodStart.value) query.period_start = periodStart.value
  if (periodEnd.value) query.period_end = periodEnd.value
  if (status.value) query.status = status.value
  return query
}

async function reload() {
  loading.value = true
  errorMessage.value = ''
  const token = Symbol('request')
  ;(reload as unknown as { token?: symbol }).token = token
  try {
    const [pointResp, scopeResp] = await Promise.all([
      request(`${ENDPOINT}?${new URLSearchParams(baseQuery(true)).toString()}`),
      request(`${ENDPOINT}?${new URLSearchParams(baseQuery(false)).toString()}`),
    ])
    if (!pointResp.ok) throw new Error(`点位明细读取失败（HTTP ${pointResp.status}），请重新取数`)
    if (!scopeResp.ok) throw new Error(`列表口径总数读取失败（HTTP ${scopeResp.status}），请重新取数`)
    const pointPayload = (await pointResp.json()) as { items?: Row[]; total?: number }
    const scopePayload = (await scopeResp.json()) as { total?: number }
    if ((reload as unknown as { token?: symbol }).token !== token) return
    rows.value = pointPayload.items ?? []
    pointTotal.value = pointPayload.total ?? rows.value.length
    scopeTotal.value = scopePayload.total ?? pointTotal.value
    if (focusId.value) {
      setTimeout(() => {
        document.getElementById(`pressure-row-${focusId.value}`)?.scrollIntoView({ block: 'center' })
      }, 0)
    }
  } catch (error) {
    if ((reload as unknown as { token?: symbol }).token !== token) return
    rows.value = []
    pointTotal.value = 0
    errorMessage.value = error instanceof Error ? error.message : '点位明细读取失败，请重新取数'
  } finally {
    if ((reload as unknown as { token?: symbol }).token === token) loading.value = false
  }
}

watch(
  () => route.query,
  () => {
    readQuery()
    void reload()
  },
  { immediate: true },
)

// 返回列表时把列表原条件（含编号、时段、状态、focus）完整带回，条件原样恢复
function backToList() {
  const query: Record<string, string> = {}
  if (route.query.keyword) query.keyword = String(route.query.keyword)
  if (periodStart.value) query.period_start = periodStart.value
  if (periodEnd.value) query.period_end = periodEnd.value
  if (status.value) query.status = status.value
  if (focusId.value) query.focus = focusId.value
  query.page = String(route.query.page ?? '1')
  void router.push({ path: '/pressure', query })
}

async function transfer() {
  transferring.value = true
  transferMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/transfer`, {
      method: 'POST',
      body: JSON.stringify({ values: { point: point.value, owner: newOwner.value } }),
    })
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string; entry?: Record<string, unknown> }
      | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '归属变更未生效，请稍后重试')
    }
    transferOk.value = true
    transferMessage.value = payload?.message || '归属已变更'
    const detail = payload?.entry as
      | { 历史归属明细?: Array<Record<string, string>> }
      | undefined
    historyOwners.value = detail?.['历史归属明细'] ?? []
    newOwner.value = ''
    // 重新取数核对：历史记录归属应保持不变
    await reload()
  } catch (error) {
    transferOk.value = false
    transferMessage.value = error instanceof Error ? error.message : '归属变更失败，请重试'
  } finally {
    transferring.value = false
  }
}

onMounted(readQuery)
</script>

<style scoped>
.point-name {
  font-size: 15px;
}
.scope-tip {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 12px;
}
.row-focus {
  background: #fff7e6;
}
.transfer-box {
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.transfer-box h3 {
  margin: 0 0 4px;
  font-size: 15px;
}
.history-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--muted);
}
.export-text {
  color: #1f6feb;
}
.filter-item select,
.filter-item input[readonly] {
  padding: 4px 6px;
}
</style>
