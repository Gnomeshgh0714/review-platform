<template>
  <div class="article-progress">
    <!-- 返回按钮 -->
    <div class="mb-16">
      <el-button :icon="ArrowLeft" text @click="router.back()">返回稿件列表</el-button>
    </div>

    <div v-loading="loading">
      <template v-if="task">
        <!-- 稿件基本信息 -->
        <el-card class="mb-16" shadow="never">
          <div class="info-header flex-between">
            <div class="flex-1">
              <h2>{{ task.title }}</h2>
              <div class="info-meta flex gap-24 mt-8">
                <span class="text-muted text-sm">编号：{{ task.task_id }}</span>
                <span class="text-muted text-sm">创建时间：{{ formatDate(task.created_at) }}</span>
                <span class="text-muted text-sm" v-if="task.deadline">
                  截止日期：{{ formatDateOnly(task.deadline) }}
                </span>
              </div>
            </div>
            <el-tag
              :type="getStatusTag(TASK_STATUS, task.status).color"
              size="large"
              effect="light"
            >
              {{ getStatusTag(TASK_STATUS, task.status).label }}
            </el-tag>
          </div>
        </el-card>

        <!-- 终审结果（DECIDED 状态） -->
        <el-card v-if="task.status === 'DECIDED'" class="mb-16 decision-card" shadow="hover">
          <template #header>
            <div class="flex gap-8">
              <el-icon color="#20c997" :size="18"><Select /></el-icon>
              <span style="font-weight: 600;">终审结果</span>
            </div>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="终审决定">
              <el-tag
                :type="decisionTagColor"
                effect="dark"
                size="large"
              >
                {{ decisionLabel }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="决策时间">
              {{ formatDate(task.updated_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="终审说明" :span="2" v-if="task.decision_notes">
              {{ task.decision_notes }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 双盲保护提示 -->
        <el-alert
          class="mb-16"
          title="双盲审稿保护"
          type="info"
          :closable="false"
          show-icon
        >
          <template #default>
            本系统采用双盲审稿机制，审稿人身份信息已严格隐藏，您无法查看审稿人姓名及详细信息。
          </template>
        </el-alert>

        <!-- 审稿进度概览（从 assignments 现算，作者视角仅含状态不含身份） -->
        <el-card class="mb-16" shadow="never" v-if="reviewerTotal > 0">
          <template #header>
            <span style="font-weight: 600;">审稿进度概览</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="8">
              <div class="progress-stat">
                <div class="stat-number text-primary">{{ reviewerTotal }}</div>
                <div class="stat-label text-muted">审稿人总数</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="progress-stat">
                <div class="stat-number text-success">{{ submittedCount }}</div>
                <div class="stat-label text-muted">已提交意见</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="progress-stat">
                <div class="stat-number text-warning">{{ pendingCount }}</div>
                <div class="stat-label text-muted">待提交意见</div>
              </div>
            </el-col>
          </el-row>
          <el-progress
            class="mt-16"
            :percentage="progressPercent"
            :color="'#409eff'"
            :stroke-width="10"
            :text-inside="true"
          />
        </el-card>

        <!-- 状态流转时间线 -->
        <el-card shadow="never">
          <template #header>
            <span style="font-weight: 600;">状态流转记录</span>
          </template>

          <el-timeline v-if="stateLogs.length > 0">
            <el-timeline-item
              v-for="(log, index) in stateLogs"
              :key="log.log_id || index"
              :timestamp="formatDate(log.created_at)"
              :type="getTimelineType(log.to_state)"
              :hollow="index === stateLogs.length - 1"
              placement="top"
            >
              <div class="timeline-content">
                <!-- 状态名 -->
                <div class="timeline-status flex gap-8">
                  <el-tag
                    :type="getStatusTag(TASK_STATUS, log.to_state).color"
                    effect="light"
                    size="small"
                  >
                    {{ getStatusTag(TASK_STATUS, log.to_state).label || log.to_state }}
                  </el-tag>
                  <span v-if="log.from_state" class="text-muted text-sm">
                    （由「{{ getStatusTag(TASK_STATUS, log.from_state).label || log.from_state }}」变更）
                  </span>
                </div>

                <!-- 操作人（后端已按双盲脱敏：审稿人在作者视角显示为「审稿人」） -->
                <div class="timeline-operator text-sm text-muted mt-8" v-if="log.operator_name">
                  <el-icon style="margin-right: 4px; vertical-align: middle;"><User /></el-icon>
                  操作人：{{ log.operator_name }}
                </div>

                <!-- 备注 -->
                <div class="timeline-remark text-sm mt-8" v-if="log.trigger_reason">
                  {{ log.trigger_reason }}
                </div>
              </div>
            </el-timeline-item>
          </el-timeline>

          <el-empty v-else description="暂无状态流转记录" :image-size="80" />
        </el-card>
      </template>

      <!-- 加载失败占位 -->
      <el-empty v-else-if="!loading" description="稿件信息加载失败">
        <el-button type="primary" @click="fetchData">重新加载</el-button>
      </el-empty>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Select, User } from '@element-plus/icons-vue'
import { taskApi } from '@/api/modules'
import { TASK_STATUS, RECOMMENDATION, getStatusTag, formatDate, formatDateOnly } from '@/utils/status'

const router = useRouter()
const route = useRoute()

// ============ 状态 ============
const loading = ref(false)
const task = ref(null)
const stateLogs = ref([])

// ============ 计算属性 ============
// 审稿统计从 assignments 现算（作者视角 assignments 保留 assignment_status，仅隐去身份）
const reviewerTotal = computed(() => (task.value?.assignments || []).length)
const submittedCount = computed(() =>
  (task.value?.assignments || []).filter(a => a.assignment_status === 'SUBMITTED').length)

// 待提交意见数
const pendingCount = computed(() =>
  Math.max(0, reviewerTotal.value - submittedCount.value))

// 进度百分比
const progressPercent = computed(() => {
  if (!reviewerTotal.value) return 0
  return Math.round((submittedCount.value / reviewerTotal.value) * 100)
})

// 终审决定标签（final_decision 与审稿建议共用词表）
const decisionLabel = computed(() => {
  if (!task.value?.final_decision) return '-'
  const rec = RECOMMENDATION[task.value.final_decision]
  return rec?.label || task.value.final_decision
})

const decisionTagColor = computed(() => {
  if (!task.value?.final_decision) return 'info'
  const rec = RECOMMENDATION[task.value.final_decision]
  return rec?.color || 'info'
})

// ============ 方法 ============
// 时间线节点类型
const getTimelineType = (status) => {
  const map = {
    PENDING: 'info',
    ASSIGNED: 'primary',
    REVIEWING: 'warning',
    SUBMITTED: 'success',
    SUMMARIZED: '',
    DECIDED: 'success',
    ARCHIVED: 'info',
    REJECTED: 'danger',
  }
  return map[status] || 'info'
}

// ============ 获取数据 ============
const fetchData = async () => {
  const taskId = route.params.id
  if (!taskId) return

  loading.value = true
  try {
    // 并行请求稿件详情和状态日志
    const [taskRes, logsRes] = await Promise.all([
      taskApi.retrieve(taskId),
      taskApi.stateLogs(taskId).catch(() => []), // 状态日志失败不阻塞
    ])
    task.value = taskRes
    stateLogs.value = Array.isArray(logsRes) ? logsRes : (logsRes.results || [])
  } catch (e) {
    console.error('获取稿件进度失败:', e)
  } finally {
    loading.value = false
  }
}

// ============ 初始化 ============
onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.article-progress h2 {
  font-size: 20px;
  color: #303133;
}
.info-header {
  align-items: flex-start;
}
.info-meta {
  flex-wrap: wrap;
}
.decision-card {
  border-left: 4px solid #20c997;
}
.progress-stat {
  text-align: center;
  padding: 12px 0;
}
.stat-number {
  font-size: 32px;
  font-weight: 700;
}
.stat-label {
  font-size: 13px;
  margin-top: 4px;
}
.timeline-content {
  padding-bottom: 8px;
}
.timeline-status {
  align-items: center;
}
.timeline-operator {
  display: flex;
  align-items: center;
}
.timeline-remark {
  color: #606266;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  line-height: 1.6;
}
</style>
