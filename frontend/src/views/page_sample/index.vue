<template>
  <section class="page" data-module="page_sample">
    <header class="page-head">
      <div>
        <h2>页面样本</h2>
        <p class="page-desc">
          留存解析成功返回的原始页面：状态码、正文片段与命中的站点标记都留在样本里，
          正文完整性与软错误检测都基于这些原始字段。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新样本</button>
        <button class="btn" type="button" @click="exportRows">导出页面样本</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>样本编号</span>
        <input v-model="filters.keyword" placeholder="按样本编号检索" />
      </label>
      <label class="filter-item">
        <span>样本状态</span>
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
          <th>证据</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span :class="cellClass(column, row)">{{ formatCell(column, row) }}</span>
          </td>
          <td><button class="link" type="button" @click="openEvidence(row)">查看证据</button></td>
          <td class="row-actions">
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无页面样本，可先通过接口登记采集结果</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条页面样本</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="evidence" class="modal-overlay" @click.self="evidence = null">
        <div class="modal-card modal-wide">
          <header class="modal-head">
            <h3>证据核对 · {{ evidence.evidence.样本编号 }}</h3>
            <button class="btn ghost" type="button" @click="evidence = null">&times;</button>
          </header>
          <div class="modal-body">
            <p class="hint-text">
              证据全部取自原页面样本：状态码来自「采集状态码」，正文片段来自「正文」，标记来自页面标题/正文/页尾字段。
            </p>
            <table class="data-table">
              <tbody>
                <tr>
                  <th>采集状态码</th>
                  <td>{{ evidence.evidence.采集状态码.value }}</td>
                  <th>检测结论</th>
                  <td>{{ evidence.analysis.label }}</td>
                </tr>
                <tr>
                  <th>正文选择器</th>
                  <td>{{ evidence.evidence.正文片段.selector || '—' }}</td>
                  <th>正文长度</th>
                  <td>{{ evidence.evidence.正文片段.length }}</td>
                </tr>
                <tr>
                  <th>正文片段</th>
                  <td colspan="3">{{ evidence.evidence.正文片段.snippet || '（空）' }}</td>
                </tr>
                <tr>
                  <th>内容信号</th>
                  <td colspan="3">
                    日期：{{ evidence.evidence.内容信号.dates.join('、') || '无' }}；
                    停办措辞：{{ evidence.evidence.内容信号.keywords.join('、') || '无' }}
                  </td>
                </tr>
              </tbody>
            </table>
            <h4>命中的站点标记</h4>
            <table class="data-table">
              <thead>
                <tr><th>来源字段</th><th>标记</th><th>原文片段</th></tr>
              </thead>
              <tbody>
                <tr v-for="(hit, index) in evidence.evidence.命中标记" :key="index">
                  <td>{{ hit.field }}</td>
                  <td>{{ hit.marker }}</td>
                  <td>{{ hit.snippet }}</td>
                </tr>
                <tr v-if="!evidence.evidence.命中标记.length">
                  <td colspan="3" class="empty-state">没有命中站点标记</td>
                </tr>
              </tbody>
            </table>
            <p class="hint-text">
              可核对：状态码 {{ evidence.evidence.可核对.状态码 ? '有' : '缺' }}、
              正文 {{ evidence.evidence.可核对.正文 ? '有' : '缺' }}、
              标记 {{ evidence.evidence.可核对.标记 ? '全部可回查' : '存在无法回查的标记' }}
            </p>
            <p v-if="evidence.analysis.missingReasons.length" class="error-text">
              正文缺失原因：{{ evidence.analysis.missingReasonLabels.join('、') }}（不能生成公告）
            </p>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | undefined | Record<string, unknown>>

const ENDPOINT = '/api/page_sample'
const columns = ['样本编号', '来源站点', '采集状态码', '正文选择器', '正文长度', '短正文', '检测结论', '命中标记', '错误模板', 'status']
const actions = ['标记解析成功', '标记解析失败', '归档样本']
const statuses = ['待解析', '解析成功', '解析失败', '已归档']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '' })
const analysis = ref<{ counts: Record<string, number> }>({ counts: {} })
const evidence = ref<{
  evidence: {
    样本编号: string
    采集状态码: { field: string; value: string }
    正文片段: { field: string; selector: string; snippet: string; length: number }
    内容信号: { dates: string[]; keywords: string[] }
    命中标记: { field: string; marker: string; snippet: string }[]
    可核对: Record<string, boolean>
  }
  analysis: { label: string; missingReasons: string[]; missingReasonLabels: string[] }
} | null>(null)

const statCards = computed(() => [
  { label: '有效公告', value: analysis.value.counts.valid ?? 0 },
  { label: '软错误页面', value: analysis.value.counts.soft_error ?? 0 },
  { label: '证据冲突', value: analysis.value.counts.conflict ?? 0 },
  { label: '正文缺失', value: analysis.value.counts.missing_body ?? 0 },
  { label: 'HTTP异常', value: analysis.value.counts.http_error ?? 0 },
])

function formatCell(column: string, row: Row) {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  if (column === '正文') {
    const text = String(value)
    return text.length > 40 ? `${text.slice(0, 40)}…` : text
  }
  return String(value)
}

function cellClass(column: string, row: Row) {
  if (column === '检测结论' && row['证据冲突']) return 'error-text'
  if (column === '检测结论' && row['软错误']) return 'error-text'
  return ''
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openEvidence(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/evidence`)
    if (!response.ok) throw new Error('证据读取失败')
    evidence.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证据读取失败'
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
    if (!response.ok || !data.ok) throw new Error(data.message || '页面样本动作未生效')
    if (data.message && data.message.includes('正文不完整')) errorMessage.value = data.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '页面样本操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const [listResponse, analysisResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/analysis`),
    ])
    if (!listResponse.ok) throw new Error('页面样本列表读取失败')
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (analysisResponse.ok) analysis.value = await analysisResponse.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '页面样本列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-wide { width: min(860px, 92vw); }
.hint-text { color: var(--muted); font-size: 12px; margin: 0; }
</style>
