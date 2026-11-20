<template>
  <section class="page" data-module="dedup">
    <header class="page-head">
      <div>
        <h2>采集去重管理</h2>
        <p class="page-desc">
          维护去重策略，并用软错误隔离结果把采集内容分成“有效内容”和“拦截样本”：
          有效内容按去重键合并后进入公告，拦截样本按错误模板单独合并，不改写已保留的公告正文。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记去重策略</button>
        <button class="btn" type="button" @click="exportRows">导出采集去重清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="panel">
      <header class="panel-head">
        <div>
          <h3>有效内容 / 拦截样本分流</h3>
          <p class="hint-text">
            有效内容按「站点 + 标题 + 正文指纹」去重；拦截样本按「站点 + 错误模板」合并，只记录条数与证据。
          </p>
        </div>
        <div class="page-actions">
          <button class="btn" type="button" @click="loadSplit">刷新分流预览</button>
          <button class="btn primary" type="button" @click="runDedup">执行去重分流</button>
        </div>
      </header>
      <p v-if="dedupMessage" class="hint-text">{{ dedupMessage }}</p>

      <h4>去重后的有效内容（{{ validItems.length }} 条）</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th>样本编号</th>
            <th>来源站点</th>
            <th>标题</th>
            <th>停办日期</th>
            <th>正文长度</th>
            <th>结论</th>
            <th>重复</th>
            <th>正文</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in validItems" :key="item.样本编号">
            <td>{{ item.样本编号 }}</td>
            <td>{{ item.来源站点 }}</td>
            <td>{{ item.标题 }}</td>
            <td>{{ item.停办日期 || '—' }}</td>
            <td>{{ item.正文长度 }}</td>
            <td>{{ item.结论 }}</td>
            <td>{{ item.重复 ? '重复命中' : '保留' }}</td>
            <td class="clamp">{{ item.正文 }}</td>
          </tr>
          <tr v-if="!validItems.length">
            <td colspan="8" class="empty-state">当前没有有效内容</td>
          </tr>
        </tbody>
      </table>

      <h4>拦截样本（{{ blockedItems.length }} 组）</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th>来源站点</th>
            <th>错误模板</th>
            <th>分类</th>
            <th>记录数</th>
            <th>样本编号</th>
            <th>响应ID</th>
            <th>冲突响应</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in blockedItems" :key="`${item.来源站点}-${item.错误模板}`">
            <td>{{ item.来源站点 }}</td>
            <td>{{ item.错误模板 }}</td>
            <td>{{ item.分类列表.join('、') }}</td>
            <td>{{ item.记录数 }}</td>
            <td>{{ item.样本列表.join('、') }}</td>
            <td>{{ item.响应列表.join('、') }}</td>
            <td class="error-text">{{ item.冲突响应.join('、') || '—' }}</td>
          </tr>
          <tr v-if="!blockedItems.length">
            <td colspan="7" class="empty-state">当前没有拦截样本</td>
          </tr>
        </tbody>
      </table>
    </section>

    <h3>去重策略</h3>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
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
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集去重数据，可先登记去重策略</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集去重记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记去重策略</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type ValidItem = {
  去重键: string
  重复: boolean
  样本编号: string
  来源站点: string
  标题: string
  正文: string
  停办日期: string
  正文长度: number
  短正文: boolean
  结论: string
  分类: string
}
type BlockedItem = {
  来源站点: string
  错误模板: string
  分类: string
  分类标签: string
  分类列表: string[]
  隔离编号: string
  记录数: number
  样本列表: string[]
  响应列表: string[]
  冲突响应: string[]
}

const ENDPOINT = '/api/dedup'
const columns = ['策略编号', '输入来源', '去重键', '排序字段', '保留策略', '时间窗口', '重复阈值', '策略状态']
const actions = ['提交配置', '启用策略', '停用策略']
const statuses = ['草稿', '已配置', '生效中', '已停用']
const stats = [
  { label: '有效内容', value: 0 },
  { label: '拦截样本组', value: 0 },
  { label: '策略总数', value: 0 },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})
const validItems = ref<ValidItem[]>([])
const blockedItems = ref<BlockedItem[]>([])
const dedupMessage = ref('')

function updateStats() {
  stats[0].value = validItems.value.filter((item) => !item.重复).length
  stats[1].value = blockedItems.value.length
  stats[2].value = total.value
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function loadSplit() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/split`)
    if (!response.ok) throw new Error('分流预览读取失败')
    const payload = await response.json()
    validItems.value = payload.valid ?? []
    blockedItems.value = payload.blocked ?? []
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分流预览读取失败'
  }
}

async function runDedup() {
  errorMessage.value = ''
  dedupMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/run`, { method: 'POST', body: JSON.stringify({}) })
    if (!response.ok) throw new Error('去重分流执行失败')
    const payload = await response.json()
    dedupMessage.value = payload.message ?? '去重分流已执行'
    await loadSplit()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '去重分流执行失败'
  }
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('采集去重动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集去重操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('去重策略列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集去重列表读取失败'
  }
}

onMounted(async () => {
  await reload()
  await loadSplit()
})
</script>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.panel h3 { margin: 0 0 4px; font-size: 15px; }
.panel h4 { margin: 12px 0 6px; font-size: 14px; }
.hint-text { color: var(--muted); font-size: 12px; margin: 0; }
.clamp { max-width: 320px; }
</style>
