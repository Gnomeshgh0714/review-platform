<template>
  <div class="opinion-view-page">
    <div v-loading="loading">
      <!-- 任务信息 -->
      <el-card shadow="never" class="mb-16">
        <template #header>
          <div class="flex-between">
            <span>审稿意见详情</span>
            <div class="gap-12 flex">
              <el-button text @click="$router.push(`/tasks/${taskId}`)">任务详情</el-button>
              <el-button text @click="$router.push(`/refs/${taskId}`)">参考文献</el-button>
              <el-button v-if="['SUMMARIZED', 'DECIDED'].includes(taskInfo.status)" text @click="$router.push(`/summaries/${taskId}`)">汇总报告</el-button>
              <el-button text @click="$router.back()">返回</el-button>
            </div>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="稿件标题">{{ taskInfo.title }}</el-descriptions-item>
          <el-descriptions-item label="任务编号">{{ taskInfo.task_id }}</el-descriptions-item>
          <el-descriptions-item label="学科">{{ taskInfo.subject_area }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag.color">{{ statusTag.label }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 审稿意见列表 -->
      <el-card v-for="(opinion, idx) in opinions" :key="opinion.opinion_id" shadow="never" class="mb-16">
        <template #header>
          <div class="flex-between">
            <div class="flex-center gap-12">
              <span class="reviewer-label">
                {{ isEditor && opinion.reviewer_name ? `审稿人 ${idx + 1}（${opinion.reviewer_name}）` : `审稿人 ${idx + 1}` }}
              </span>
              <el-tag v-if="opinion.recommendation" :type="getRecTag(opinion.recommendation).color" size="small">
                {{ getRecTag(opinion.recommendation).label }}
              </el-tag>
            </div>
            <span class="text-muted text-sm">{{ formatDate(opinion.submitted_at) }}</span>
          </div>
        </template>

        <!-- 维度评分 -->
        <el-table :data="formatDimensionScores(opinion)" border size="small" class="mb-16">
          <el-table-column prop="name" label="维度" width="150" />
          <el-table-column prop="score" label="评分" width="80" align="center">
            <template #default="{ row }">
              <el-rate :model-value="row.score" disabled size="small" />
              <span class="text-sm">{{ row.score }}/5</span>
            </template>
          </el-table-column>
          <el-table-column prop="comment" label="评语" show-overflow-tooltip />
        </el-table>

        <!-- 综合评语 -->
        <el-divider content-position="left">综合评语</el-divider>
        <div class="comment-text">{{ opinion.overall_comment }}</div>

        <!-- 修改建议 -->
        <template v-if="(opinion.revision_suggestions || []).length">
          <el-divider content-position="left">修改建议</el-divider>
          <div class="comment-text">{{ opinion.revision_suggestions.join('\n') }}</div>
        </template>
      </el-card>

      <el-empty v-if="!loading && opinions.length === 0" description="暂无审稿意见" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { formApi, taskApi } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import { formatDate, TASK_STATUS, RECOMMENDATION } from '@/utils/status'

const route = useRoute()
const auth = useAuthStore()
const taskId = route.params.taskId

const loading = ref(true)
const taskInfo = ref({})
const opinions = ref([])

const isEditor = computed(() => auth.isEditor)

const statusTag = computed(() => TASK_STATUS[taskInfo.value.status] || { label: '-', color: 'info' })

const getRecTag = (rec) => RECOMMENDATION[rec] || { label: rec, color: 'info' }

// 维度评分：编辑部视角有 dimension_scores_detail（含维度名配置），
// 作者视角为匿名化结果，仅含 dimension_scores 数组
const formatDimensionScores = (opinion) => {
  const items = opinion.dimension_scores_detail || opinion.dimension_scores || []
  return items.map(item => ({
    code: item.dimensionId,
    name: item.dimensionName || item.dimensionId,
    score: item.score,
    comment: item.comment || '-',
  }))
}

const fetchData = async () => {
  loading.value = true
  try {
    const [task, opRes] = await Promise.all([
      taskApi.retrieve(taskId),
      formApi.taskOpinions(taskId),
    ])
    taskInfo.value = task
    opinions.value = opRes.results || opRes || []
  } catch (e) {
    console.error('Failed to fetch opinions:', e)
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.reviewer-label { font-size: 15px; font-weight: 600; }
.comment-text {
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.8;
  color: #606266;
  white-space: pre-wrap;
}
</style>
