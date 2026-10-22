<template>
  <div class="task-list-page">
    <el-card shadow="never">
      <template #header>
        <div class="flex-between">
          <span>审稿任务看板</span>
          <el-button type="primary" @click="$router.push('/tasks/create')">
            <el-icon><Plus /></el-icon> 创建任务
          </el-button>
        </div>
      </template>

      <!-- 筛选栏 -->
      <div class="filter-bar mb-16">
        <el-input v-model="filters.keyword" placeholder="搜索标题/编号" clearable style="width: 200px" @keyup.enter="handleSearch" />
        <el-select v-model="filters.status" placeholder="状态" clearable @change="handleSearch" style="width: 140px">
          <el-option v-for="(v, k) in TASK_STATUS" :key="k" :label="v.label" :value="k" />
        </el-select>
        <el-select v-model="filters.subject" placeholder="学科" clearable filterable @change="handleSearch" style="width: 160px">
          <el-option v-for="s in subjectOptions" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
      </div>

      <!-- 统计概览（基于看板数据现算） -->
      <el-row :gutter="8" class="mb-16">
        <el-col :span="6" v-for="stat in statCards" :key="stat.key">
          <el-statistic :title="stat.label" :value="statusCounts[stat.key] || 0" />
        </el-col>
      </el-row>

      <!-- 任务表格 -->
      <el-table :data="list" v-loading="loading" border @row-click="handleRowClick">
        <el-table-column prop="task_id" label="编号" width="150" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="TASK_STATUS[row.status]?.color || 'info'" size="small">
              {{ TASK_STATUS[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="subject_area" label="学科" width="120" show-overflow-tooltip />
        <el-table-column label="审稿人" width="100" align="center">
          <template #default="{ row }">
            {{ submittedCount(row) }}/{{ (row.assignments || []).length }}
          </template>
        </el-table-column>
        <el-table-column label="截止日期" width="140">
          <template #default="{ row }">
            <span v-if="row.deadline" :class="deadlineClass(row.deadline, row.status)">
              {{ formatDateOnly(row.deadline) }}
              <el-icon v-if="isOverdue(row.deadline, row.status)" color="#f56c6c"><Warning /></el-icon>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="140">
          <template #default="{ row }">{{ formatDateOnly(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click.stop="$router.push(`/tasks/${row.task_id}`)">详情</el-button>
            <el-button v-if="row.status === 'PENDING'" text type="warning"
              @click.stop="$router.push(`/tasks/${row.task_id}/assign`)">分配</el-button>
            <el-button v-if="['REVIEWING', 'SUBMITTED', 'SUMMARIZED', 'DECIDED'].includes(row.status)" text type="info"
              @click.stop="$router.push(`/opinions/${row.task_id}`)">审稿意见</el-button>
            <el-button v-if="['REVIEWING', 'SUBMITTED', 'SUMMARIZED', 'DECIDED'].includes(row.status)" text
              @click.stop="$router.push(`/refs/${row.task_id}`)">参考文献</el-button>
            <el-button v-if="['SUMMARIZED', 'DECIDED'].includes(row.status)" text type="success"
              @click.stop="$router.push(`/summaries/${row.task_id}`)">汇总</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > PAGE_SIZE"
        class="mt-16"
        :total="total"
        :page-size="PAGE_SIZE"
        layout="total, prev, pager, next"
        v-model:current-page="page"
        @current-change="fetchList"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { taskApi } from '@/api/modules'
import { TASK_STATUS, formatDateOnly, daysRemaining } from '@/utils/status'
import { Plus, Warning } from '@element-plus/icons-vue'

const router = useRouter()

const loading = ref(false)
const list = ref([])
const total = ref(0)
const page = ref(1)
// V1.2 一般#5：当前筛选条件下的全量结果集——统一驱动列表分页、total 与统计卡片
const filteredAll = ref([])

const PAGE_SIZE = 20

const filters = reactive({ keyword: '', status: '', subject: '' })

const subjectOptions = [
  '经济学', '金融学', '管理学', '气候经济学', '环境经济学',
  '劳动经济学', '宏观经济学', '发展经济学', '应用计量', '政策评估',
]

const statCards = [
  { key: 'PENDING', label: '待分配' },
  { key: 'REVIEWING', label: '审稿中' },
  { key: 'SUBMITTED', label: '待汇总' },
  { key: 'DECIDED', label: '已决策' },
]

// 统计从看板数据现算（dashboard 端点返回任务列表而非统计对象）
// V1.2 一般#5：统计基于当前筛选条件下的全量结果（filteredAll），与 total 同口径，
// 不再只统计当前页，避免列表/total/统计三者描述不同集合
const statusCounts = computed(() => {
  const counts = {}
  for (const t of filteredAll.value) {
    counts[t.status] = (counts[t.status] || 0) + 1
  }
  return counts
})

const submittedCount = (row) =>
  (row.assignments || []).filter(a => a.assignment_status === 'SUBMITTED').length

const isOverdue = (deadline, status) => {
  if (!deadline) return false
  // V1.2 一般#3：任务终态只有 DECIDED（ARCHIVED/REJECTED 为前端死键，已从词表删除）
  if (status === 'DECIDED') return false
  return daysRemaining(deadline) < 0
}

const deadlineClass = (deadline, status) => {
  if (isOverdue(deadline, status)) return 'text-danger'
  const days = daysRemaining(deadline)
  // V1.2 一般#3：终态判断去除 ARCHIVED 死键
  if (days !== null && days <= 3 && status !== 'DECIDED') return 'text-warning'
  return ''
}

const handleSearch = () => { page.value = 1; fetchList() }

const fetchList = async () => {
  loading.value = true
  try {
    // V1.2 一般#5：keyword 为前端过滤，原先只过滤当前页 20 条，导致列表/total/统计
    // 三口径互相矛盾——改为按筛选条件翻页取全量后统一过滤，列表分页、total、
    // 统计卡片全部基于同一结果集；status/subject 仍走服务端筛选减少传输
    const params = { page_size: 100 }
    if (filters.status) params.status = filters.status
    if (filters.subject) params.subject = filters.subject
    const all = []
    let p = 1
    for (;;) {
      const res = await taskApi.dashboard({ ...params, page: p })
      const rows = res.results || res || []
      all.push(...rows)
      const cnt = res.count ?? all.length
      if (all.length >= cnt || rows.length === 0) break
      p += 1
    }
    if (filters.keyword) {
      const kw = filters.keyword.toLowerCase()
      filteredAll.value = all.filter(t =>
        (t.title || '').toLowerCase().includes(kw) ||
        (t.task_id || '').toLowerCase().includes(kw),
      )
    } else {
      filteredAll.value = all
    }
    // 客户端分页：列表展示当前页切片，total 为过滤后全量长度
    list.value = filteredAll.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE)
    total.value = filteredAll.value.length
  } catch (e) { console.error(e) } finally { loading.value = false }
}

const handleRowClick = (row) => {
  router.push(`/tasks/${row.task_id}`)
}

onMounted(fetchList)
</script>

<style scoped>
.filter-bar { display: flex; gap: 12px; align-items: center; }
</style>
