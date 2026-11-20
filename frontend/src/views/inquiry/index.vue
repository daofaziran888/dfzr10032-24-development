<template>
  <section class="page" data-module="inquiry">
    <header class="page-head">
      <div>
        <h2>站点追问</h2>
        <p class="page-desc">
          从隔离记录发起追问，必须指明针对哪个响应。追问证据带着状态码、正文片段与命中标记，站点侧可以复现同一页面。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出追问清单</button>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="raiseInquiry">
      <label class="filter-item">
        <span>隔离编号</span>
        <input v-model="form.isolation_code" placeholder="如 ISO-0001" />
      </label>
      <label class="filter-item">
        <span>响应ID</span>
        <input v-model="form.response_id" placeholder="要追问的响应" />
      </label>
      <label class="filter-item grow">
        <span>追问说明（可选）</span>
        <input v-model="form.note" placeholder="不填则使用默认问题" />
      </label>
      <button class="btn primary" type="submit">发起追问</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>追问编号</span>
        <input v-model="filters.keyword" placeholder="按追问编号检索" />
      </label>
      <label class="filter-item">
        <span>追问状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column" :class="column === '正文片段' ? 'clamp' : ''">
            {{ formatCell(column, row) }}
          </td>
          <td class="row-actions">
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无追问记录，可从隔离记录发起</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条追问</span>
      <span v-if="message" class="hint-text">{{ message }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, unknown>

const ENDPOINT = '/api/inquiry'
const columns = ['追问编号', '隔离编号', '来源站点', '错误模板', '响应ID', '页面地址', '采集状态码', '正文片段', '命中标记', 'status']
const actions = ['发出追问', '记录回复', '关闭追问']
const statuses = ['待追问', '已发出', '已回复', '已关闭']

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '' })
const form = ref({ isolation_code: '', response_id: '', note: '' })

function formatCell(column: string, row: Row) {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function raiseInquiry() {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/raise`, {
      method: 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '追问发起失败')
    message.value = data.message
    form.value = { isolation_code: '', response_id: '', note: '' }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '追问发起失败'
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
    if (!response.ok || !data.ok) throw new Error(data.message || '追问动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '追问操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('追问列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '追问列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.filter-item.grow { flex: 1; min-width: 220px; }
.clamp { max-width: 280px; }
.hint-text { color: var(--muted); font-size: 12px; }
</style>
