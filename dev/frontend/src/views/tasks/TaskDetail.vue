<template>
  <div class="task-detail-page">
    <div v-loading="loading">
      <!-- 任务信息 -->
      <el-card shadow="never" class="mb-16">
        <template #header>
          <div class="flex-between">
            <div class="flex-center gap-12">
              <span>{{ task.title }}</span>
              <el-tag :type="statusTag.color">{{ statusTag.label }}</el-tag>
            </div>
            <el-button text @click="$router.back()">返回</el-button>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务编号">{{ task.task_id }}</el-descriptions-item>
          <el-descriptions-item label="学科">{{ task.subject_area || '-' }}</el-descriptions-item>
          <el-descriptions-item label="作者">{{ task.author_name || task.author_email }}</el-descriptions-item>
          <el-descriptions-item label="截止日期">{{ formatDate(task.deadline) }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(task.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="审稿模板">{{ task.template_name || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="task.abstract" label="摘要" :span="2">{{ task.abstract }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 操作按钮区 -->
      <div class="action-bar mb-16">
        <el-button @click="$router.push('/tasks')">
          <el-icon><Back /></el-icon> 返回看板
        </el-button>
        <el-button v-if="task.status === 'PENDING'" type="primary" @click="$router.push(`/tasks/${task.task_id}/assign`)">
          分配审稿人
        </el-button>
        <el-button v-if="task.status === 'REVIEWING'" type="warning" @click="handleForceSummarize">
          强制汇总
        </el-button>
        <el-button v-if="task.status === 'SUBMITTED'" type="primary" @click="handleGenerateSummary">
          生成汇总报告
        </el-button>
        <el-button v-if="task.status === 'SUMMARIZED'" type="success" @click="$router.push(`/tasks/${task.task_id}/decision`)">
          终审决策
        </el-button>
        <el-button v-if="['REVIEWING', 'SUBMITTED', 'SUMMARIZED', 'DECIDED'].includes(task.status)" @click="$router.push(`/opinions/${task.task_id}`)">
          查看审稿意见
        </el-button>
        <el-button v-if="['SUMMARIZED', 'DECIDED', 'ARCHIVED'].includes(task.status)" @click="$router.push(`/summaries/${task.task_id}`)">
          查看汇总报告
        </el-button>
        <el-button @click="$router.push(`/refs/${task.task_id}`)">
          <el-icon><Search /></el-icon> 参考文献验证
        </el-button>
      </div>

      <el-row :gutter="16">
        <!-- 审稿人列表 -->
        <el-col :span="14">
          <el-card shadow="never">
            <template #header><span>审稿人列表</span></template>
            <el-table :data="assignments" border size="small">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column prop="reviewer_name" label="审稿人" width="120" />
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag :type="ASSIGNMENT_STATUS[row.assignment_status]?.color || 'info'" size="small">
                    {{ ASSIGNMENT_STATUS[row.assignment_status]?.label || row.assignment_status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="截止日期" width="120" align="center">
                <template #default="{ row }">{{ row.deadline || '-' }}</template>
              </el-table-column>
              <el-table-column prop="submitted_at" label="提交时间" width="160">
                <template #default="{ row }">{{ formatDate(row.submitted_at) }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>

        <!-- 状态流转时间线 -->
        <el-col :span="10">
          <el-card shadow="never">
            <template #header><span>状态流转</span></template>
            <el-timeline>
              <el-timeline-item
                v-for="log in stateLogs"
                :key="log.log_id"
                :timestamp="formatDate(log.created_at)"
                :type="log.to_state === 'REJECTED' ? 'danger' : 'primary'"
              >
                <div>
                  <el-tag :type="TASK_STATUS[log.to_state]?.color || 'info'" size="small">
                    {{ TASK_STATUS[log.to_state]?.label || log.to_state }}
                  </el-tag>
                </div>
                <div v-if="log.operator_name" class="text-muted text-sm mt-8">
                  操作人：{{ log.operator_name }}
                </div>
                <div v-if="log.trigger_reason" class="text-muted text-sm">{{ log.trigger_reason }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { taskApi, summaryApi } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import { TASK_STATUS, ASSIGNMENT_STATUS, formatDate } from '@/utils/status'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Back } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const task = ref({})
const assignments = ref([])
const stateLogs = ref([])

const statusTag = computed(() => TASK_STATUS[task.value.status] || { label: '-', color: 'info' })

const fetchData = async () => {
  loading.value = true
  try {
    const [t, logs] = await Promise.all([
      taskApi.retrieve(route.params.id),
      taskApi.stateLogs(route.params.id),
    ])
    task.value = t
    assignments.value = t.assignments || []
    stateLogs.value = logs.results || logs || []
  } catch (e) { console.error(e) } finally { loading.value = false }
}

// 强制汇总：仅审稿中（REVIEWING）且已有已提交意见时可用，需填写原因
const handleForceSummarize = () => {
  ElMessageBox.prompt('强制汇总将把未提交的审稿人标记为过期，并基于已提交意见汇总。请填写原因：', '强制汇总', {
    type: 'warning',
    inputPlaceholder: '必填：强制汇总原因',
    inputValidator: (v) => (v && v.trim() ? true : '必须填写强制汇总原因'),
  }).then(async ({ value }) => {
    try {
      await taskApi.forceSummarize(route.params.id, { reason: value.trim() })
      ElMessage.success('已强制汇总')
      fetchData()
    } catch (e) { /* handled */ }
  }).catch(() => {})
}

// 生成汇总报告：已提交（SUBMITTED）状态触发
const handleGenerateSummary = () => {
  ElMessageBox.confirm('确认基于全部已提交意见生成汇总报告？', '提示', {
    type: 'info',
  }).then(async () => {
    try {
      await summaryApi.generate(route.params.id)
      ElMessage.success('汇总报告已生成')
      fetchData()
    } catch (e) { /* handled */ }
  }).catch(() => {})
}

onMounted(fetchData)
</script>

<style scoped>
.action-bar { display: flex; gap: 12px; }
</style>
