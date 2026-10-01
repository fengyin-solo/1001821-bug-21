<template>
  <section class="page" data-module="pressure-detail">
    <header class="page-head">
      <div>
        <h2>压力监测记录详情</h2>
        <p class="page-desc">单条记录明细，并按列表同一口径回看同范围记录；点位归属变更后，历史记录仍保留登记时的归属。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="backToList">返回列表（保留条件）</button>
      </div>
    </header>

    <p v-if="scopeText" class="scope-text">来自列表的范围：{{ scopeText }}</p>
    <p v-if="errorMessage" class="error-text">
      {{ errorMessage }}
      <button class="link" type="button" @click="loadAll">重新取数</button>
    </p>

    <article v-if="entry" class="detail-card">
      <h3>记录 {{ entry['监测编号'] }}</h3>
      <dl class="detail-grid">
        <template v-for="field in detailFields" :key="field">
          <dt>{{ field }}</dt>
          <dd>{{ entry[field] ?? '—' }}</dd>
        </template>
      </dl>
      <div class="row-actions detail-actions">
        <button
          v-for="action in actions"
          :key="action"
          class="btn"
          type="button"
          :disabled="loading"
          @click="runAction(action)"
        >
          {{ action }}
        </button>
      </div>
    </article>

    <section class="detail-block">
      <h3>当前范围记录（与列表、另存清单同口径，共 {{ scopeTotal }} 条）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in scopeColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in scopeRows" :key="String(row.id)" :class="{ 'row-current': row.id === entryId }">
            <td v-for="column in scopeColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!scopeRows.length">
            <td :colspan="scopeColumns.length" class="empty-state">当前范围没有匹配记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="detail-block">
      <h3>
        同点位全部历史记录（共 {{ pointRows.length }} 条；当前归属：{{ currentOwner }}）
      </h3>
      <form class="filter-bar" @submit.prevent="reassign">
        <label class="filter-item">
          <span>变更点位当前归属为</span>
          <input v-model="newOwner" placeholder="例如：江南片区" />
        </label>
        <button class="btn primary" type="submit" :disabled="loading || !newOwner.trim()">提交归属变更</button>
        <span v-if="reassignMessage" class="scope-text">{{ reassignMessage }}</span>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in pointColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in pointRows" :key="String(row.id)" :class="{ 'row-current': row.id === entryId }">
            <td v-for="column in pointColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="page-desc">说明：归属变更只更新点位当前归属与之后新登记的记录，本页历史记录的归属保持不变。</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/pressure'
const actions = ['启动采集', '标记越限', '停止监测']
const detailFields = [
  '监测编号', '监测点位', '监测时段', '平均压力', '峰值压力', '越限次数',
  '采集人员', '监测状态', '归属片区', '判定口径',
]
const scopeColumns = ['监测编号', '监测点位', '监测时段', '平均压力', '峰值压力', '越限次数', '监测状态', '归属片区', '判定口径']
const pointColumns = ['监测编号', '监测时段', '监测状态', '归属片区', '判定口径']

const route = useRoute()
const router = useRouter()

const entryId = computed(() => Number(route.params.id))
const entry = ref<Row | null>(null)
const scopeRows = ref<Row[]>([])
const scopeTotal = ref(0)
const pointRows = ref<Row[]>([])
const currentOwner = ref('')
const newOwner = ref('')
const loading = ref(false)
const errorMessage = ref('')
const reassignMessage = ref('')

const SCOPE_KEYS = ['keyword', 'point', 'period', 'period_start', 'period_end', 'status']

const scopeQuery = computed(() => {
  const query: Record<string, string> = {}
  for (const key of SCOPE_KEYS) {
    const value = route.query[key]
    if (typeof value === 'string' && value) {
      query[key] = value
    }
  }
  return query
})

const scopeText = computed(() =>
  Object.entries(scopeQuery.value)
    .map(([key, value]) => `${key}=${value}`)
    .join('，'),
)

function backToList() {
  // 列表页会从地址栏恢复全部条件与页码。
  void router.push({ name: 'pressure', query: route.query })
}

async function loadAll() {
  loading.value = true
  errorMessage.value = ''
  try {
    const scopeString = new URLSearchParams({ ...scopeQuery.value, page: '1', size: '10000' }).toString()
    const [entryRes, scopeRes] = await Promise.all([
      request(`${ENDPOINT}/${entryId.value}`),
      request(`${ENDPOINT}?${scopeString}`),
    ])
    if (!entryRes.ok) {
      throw new Error(`压力记录明细读取失败（HTTP ${entryRes.status}）`)
    }
    if (!scopeRes.ok) {
      throw new Error(`当前范围记录读取失败（HTTP ${scopeRes.status}）`)
    }
    entry.value = (await entryRes.json()) as Row
    const scopePayload = (await scopeRes.json()) as { items?: Row[]; total?: number }
    scopeRows.value = scopePayload.items ?? []
    scopeTotal.value = scopePayload.total ?? scopeRows.value.length
    await loadPointHistory()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力监测详情读取失败'
  } finally {
    loading.value = false
  }
}

async function loadPointHistory() {
  if (!entry.value) {
    return
  }
  const point = String(entry.value['监测点位'] ?? '')
  const response = await request(`${ENDPOINT}/point?${new URLSearchParams({ point }).toString()}`)
  if (!response.ok) {
    return
  }
  const payload = (await response.json()) as { owner?: string; items?: Row[] }
  pointRows.value = payload.items ?? []
  currentOwner.value = payload.owner ?? ''
}

async function runAction(action: string) {
  if (!entry.value) {
    return
  }
  errorMessage.value = ''
  reassignMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${entry.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = (await response.json().catch(() => null)) as { message?: string } | null
    if (!response.ok || !payload) {
      throw new Error('压力监测动作未生效，请稍后重试')
    }
    await loadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力监测操作失败'
  }
}

async function reassign() {
  if (!entry.value || !newOwner.value.trim()) {
    return
  }
  errorMessage.value = ''
  reassignMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/point/reassign`, {
      method: 'POST',
      body: JSON.stringify({
        values: { 监测点位: String(entry.value['监测点位'] ?? ''), 归属片区: newOwner.value.trim() },
      }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload || payload.ok === false) {
      throw new Error(payload?.message || '归属变更未生效，请稍后重试')
    }
    reassignMessage.value = payload.message ?? '归属变更已生效'
    newOwner.value = ''
    await loadPointHistory()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归属变更失败'
  }
}

onMounted(loadAll)
</script>
