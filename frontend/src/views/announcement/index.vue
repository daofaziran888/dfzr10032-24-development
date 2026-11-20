<template>
  <section class="page" data-module="announcement">
    <header class="page-head">
      <div>
        <h2>公告办事台</h2>
        <p class="page-desc">
          只发布去重后的有效公告。正文缺失或被隔离的样本不会进入公告；
          已发布公告保留正文原文与指纹，可随时独立核对。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出公告清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>公告编号</span>
        <input v-model="filters.keyword" placeholder="按公告编号检索" />
      </label>
      <label class="filter-item">
        <span>公告状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section class="panel">
      <h3>按日期追溯</h3>
      <div class="filter-bar">
        <label class="filter-item">
          <span>停办日期</span>
          <input v-model="dateQuery" placeholder="YYYY-MM-DD" />
        </label>
        <button class="btn primary" type="button" @click="loadDay">查这一天采用哪份公告</button>
        <label class="filter-item">
          <span>从去重结果发布（去重结果 id）</span>
          <input v-model="publishId" placeholder="dedup 有效内容 id" />
        </label>
        <button class="btn" type="button" @click="publish">发布公告</button>
      </div>
      <p v-if="message" class="hint-text">{{ message }}</p>
      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

      <template v-if="day">
        <p class="hint-text">{{ day.说明 }}</p>
        <table class="data-table">
          <tbody>
            <tr>
              <th>采用公告</th>
              <td>{{ day.采用公告 ? `${day.采用公告.公告编号} · ${day.采用公告.标题}` : '无' }}</td>
              <th>停办日期</th>
              <td>{{ day.采用公告 ? day.采用公告.停办日期 : '—' }}</td>
            </tr>
            <tr>
              <th>来源响应</th>
              <td>{{ day.采用公告 ? day.采用公告.来源响应 : '—' }}</td>
              <th>来源样本</th>
              <td>{{ day.采用公告 ? day.采用公告.来源样本 : '—' }}</td>
            </tr>
            <tr>
              <th>正文核对</th>
              <td colspan="3">
                {{ day.核对 ? `${day.核对.一致 ? '一致' : '不一致'}（${day.核对.正文指纹.slice(0, 16)}…）` : '—' }}
              </td>
            </tr>
            <tr>
              <th>隔离记录</th>
              <td colspan="3">
                <span v-for="record in day.隔离记录" :key="record.隔离编号">
                  {{ record.隔离编号 }}（{{ record.错误模板 }}，{{ record.分类 }}，响应 {{ record.响应列表.join('、') }}）
                </span>
                <span v-if="!day.隔离记录.length">无</span>
              </td>
            </tr>
            <tr>
              <th>追问响应</th>
              <td colspan="3">
                <span v-for="item in day.追问" :key="item.追问编号">
                  {{ item.追问编号 }} → {{ item.响应ID }}（{{ item.status }}）
                </span>
                <span v-if="!day.追问.length">无</span>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>核对</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(column, row) }}</td>
          <td>
            <button class="link" type="button" @click="verify(row)">重新核对正文</button>
          </td>
          <td class="row-actions">
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无公告记录，可从去重结果发布</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条公告</span>
      <span v-if="verifyResult" class="hint-text">
        核对 {{ verifyResult.公告编号 }}：{{ verifyResult.一致 ? '一致' : '不一致' }}，指纹 {{ verifyResult.正文指纹.slice(0, 16) }}…
      </span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, unknown>
type DaySummary = {
  说明: string
  采用公告: { 公告编号: string; 标题: string; 停办日期: string; 来源响应: string; 来源样本: string } | null
  核对: { 一致: boolean; 正文指纹: string } | null
  隔离记录: { 隔离编号: string; 错误模板: string; 分类: string; 响应列表: string[] }[]
  追问: { 追问编号: string; 响应ID: string; status: string }[]
}

const ENDPOINT = '/api/announcement'
const columns = ['公告编号', '来源站点', '标题', '停办日期', '样本编号', '响应ID', '核对状态', 'status']
const actions = ['发布公告', '撤回公告']
const statuses = ['待发布', '已发布', '已撤回']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const message = ref('')
const filters = ref({ keyword: '', status: '' })
const dateQuery = ref('2026-11-20')
const day = ref<DaySummary | null>(null)
const publishId = ref('')
const verifyResult = ref<{ 公告编号: string; 一致: boolean; 正文指纹: string } | null>(null)
const stats = ref([
  { label: '公告总数', value: 0 },
  { label: '已发布', value: 0 },
  { label: '待发布', value: 0 },
])

function formatCell(column: string, row: Row) {
  const value = row[column]
  if (column === '正文指纹' && value) return `${String(value).slice(0, 12)}…`
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function updateStats() {
  stats.value[0].value = total.value
  stats.value[1].value = rows.value.filter((row) => row.status === '已发布').length
  stats.value[2].value = rows.value.filter((row) => row.status === '待发布').length
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function loadDay() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/day?date=${encodeURIComponent(dateQuery.value)}`)
    if (!response.ok) throw new Error('按日期追溯失败')
    day.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '按日期追溯失败'
  }
}

async function publish() {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/publish`, {
      method: 'POST',
      body: JSON.stringify({ values: { dedup_id: Number(publishId.value) } }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '发布失败')
    message.value = data.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布失败'
  }
}

async function verify(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/verify`)
    if (!response.ok) throw new Error('正文核对失败')
    verifyResult.value = await response.json()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '正文核对失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '公告动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '公告操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('公告列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '公告列表读取失败'
  }
}

onMounted(async () => {
  await reload()
  await loadDay()
})
</script>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; }
.panel h3 { margin: 0 0 8px; font-size: 15px; }
.hint-text { color: var(--muted); font-size: 12px; }
</style>
