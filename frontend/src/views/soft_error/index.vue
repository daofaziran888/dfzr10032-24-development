<template>
  <section class="page" data-module="soft_error">
    <header class="page-head">
      <div>
        <h2>软错误页面隔离</h2>
        <p class="page-desc">
          状态码正常、实际显示为站点报错页的样本集中隔离；同一站点同一错误模板的响应合并为一条记录，
          公告正文记录不受影响。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="runScan">扫描页面样本</button>
        <button class="btn" type="button" @click="exportRows">导出隔离结果</button>
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
        <span>隔离编号</span>
        <input v-model="filters.keyword" placeholder="按隔离编号检索" />
      </label>
      <label class="filter-item">
        <span>处理状态</span>
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
          <th>隔离编号</th>
          <th>来源站点</th>
          <th>错误模板</th>
          <th>分类</th>
          <th>记录数</th>
          <th>响应ID</th>
          <th>命中标记</th>
          <th>状态码</th>
          <th>status</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['隔离编号'] }}</td>
          <td>{{ row['来源站点'] }}</td>
          <td>{{ row['错误模板'] }}</td>
          <td>{{ row['分类标签'] }}</td>
          <td>{{ row['记录数'] }}</td>
          <td>{{ row['响应ID'] }}</td>
          <td>{{ row['命中标记'] }}</td>
          <td>{{ row['状态码'] }}</td>
          <td>{{ row['status'] }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看证据</button>
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="10" class="empty-state">暂无隔离记录，可先扫描页面样本</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条隔离记录</span>
      <span v-if="message" class="hint-text">{{ message }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="detail" class="modal-overlay" @click.self="detail = null">
        <div class="modal-card modal-wide">
          <header class="modal-head">
            <h3>隔离证据 · {{ detail['隔离编号'] }}</h3>
            <button class="btn ghost" type="button" @click="detail = null">&times;</button>
          </header>
          <div class="modal-body">
            <table class="data-table">
              <tbody>
                <tr><th>来源站点</th><td>{{ detail['来源站点'] }}</td><th>错误模板</th><td>{{ detail['错误模板'] }}</td></tr>
                <tr><th>分类</th><td>{{ detail['分类列表'].join('、') }}</td><th>建议</th><td>{{ detail['建议'] }}</td></tr>
                <tr><th>冲突响应</th><td colspan="3">{{ (detail['冲突响应'] || []).join('、') || '无' }}</td></tr>
              </tbody>
            </table>
            <h4>样本明细</h4>
            <table class="data-table">
              <thead>
                <tr><th>样本编号</th><th>响应ID</th><th>分类</th><th>状态码</th><th>正文片段</th><th>命中标记</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in detail['样本明细']" :key="item.样本编号">
                  <td>{{ item.样本编号 }}</td>
                  <td>{{ item.响应ID }}</td>
                  <td>{{ item.分类标签 }}</td>
                  <td>{{ item.采集状态码 }}</td>
                  <td>{{ item.正文片段 || '（空）' }}</td>
                  <td>{{ item.命中标记 }}</td>
                </tr>
              </tbody>
            </table>
            <h4>可回查证据（逐响应）</h4>
            <table class="data-table">
              <thead>
                <tr><th>响应ID</th><th>页面地址</th><th>状态码</th><th>正文片段</th><th>命中标记</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in detail['证据']" :key="item.响应ID">
                  <td>{{ item.响应ID }}</td>
                  <td>{{ item.页面地址 }}</td>
                  <td>{{ item.采集状态码.value }}</td>
                  <td>{{ item.正文片段.snippet || '（空）' }}</td>
                  <td>{{ formatMarkers(item.命中标记) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, unknown>
type Detail = Record<string, unknown> & {
  分类列表: string[]
  冲突响应: string[]
  样本明细: { 样本编号: string; 响应ID: string; 分类标签: string; 采集状态码: string; 正文片段: string; 命中标记: string }[]
  证据: { 响应ID: string; 页面地址: string; 采集状态码: { value: string }; 正文片段: { snippet: string }; 命中标记: { field: string; marker: string }[] }[]
}

const ENDPOINT = '/api/soft_error'
const actions = ['发起核实', '标记已追问', '确认占位页', '关闭隔离']
const statuses = ['待处理', '已追问', '已确认', '已关闭']

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '' })
const detail = ref<Detail | null>(null)
const stats = ref([
  { label: '隔离记录', value: 0 },
  { label: '待处理', value: 0 },
  { label: '证据冲突', value: 0 },
])

function formatMarkers(markers: { field: string; marker: string }[]) {
  return markers.map((hit) => `${hit.field}:${hit.marker}`).join('；') || '—'
}

function updateStats() {
  stats.value[0].value = total.value
  stats.value[1].value = rows.value.filter((row) => row.status === '待处理').length
  stats.value[2].value = rows.value.filter((row) => row['分类'] === 'conflict').length
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('隔离详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '隔离详情读取失败'
  }
}

async function runScan() {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/scan`, {
      method: 'POST',
      body: JSON.stringify({ values: {} }),
    })
    if (!response.ok) throw new Error('隔离扫描失败')
    const data = await response.json()
    message.value = data.message ?? '隔离扫描完成'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '隔离扫描失败'
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
    if (!response.ok || !data.ok) throw new Error(data.message || '隔离记录动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '隔离记录操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('隔离结果读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '隔离结果读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-wide { width: min(900px, 94vw); }
.hint-text { color: var(--muted); font-size: 12px; }
</style>
