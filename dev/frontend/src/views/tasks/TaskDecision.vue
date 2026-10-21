<template>
  <div class="task-decision-page">
    <!-- 任务汇总信息 -->
    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="flex-between">
          <span>任务汇总信息</span>
          <el-button text @click="$router.back()">返回</el-button>
        </div>
      </template>
      <div v-loading="loading">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="稿件标题">{{ taskInfo.title }}</el-descriptions-item>
          <el-descriptions-item label="任务编号">{{ taskInfo.task_id }}</el-descriptions-item>
          <el-descriptions-item label="学科">{{ taskInfo.subject_area || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">
            <el-tag :type="statusTag.color">{{ statusTag.label }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 汇总报告信息 -->
        <template v-if="summary">
          <el-divider content-position="left">审稿意见汇总</el-divider>

          <!-- 推荐分布 -->
          <el-row :gutter="16" class="mb-16">
            <el-col :span="6" v-for="rec in recommendationStats" :key="rec.key">
              <div class="rec-stat-card">
                <div class="rec-label">
                  <el-tag :type="rec.color" size="small" effect="dark">{{ rec.label }}</el-tag>
                </div>
                <div class="rec-count">{{ rec.count }} 票</div>
                <div class="rec-percent text-muted text-sm">{{ rec.percent }}%</div>
              </div>
            </el-col>
          </el-row>

          <!-- 系统建议 -->
          <el-alert
            v-if="summary.system_recommendation"
            :type="suggestionAlertType"
            show-icon
            :closable="false"
            class="mb-16"
          >
            <template #title>
              系统建议：
              <el-tag v-if="suggestedDecision" :type="suggestionAlertType" size="small" effect="dark" class="ml-8">
                {{ suggestedDecisionLabel }}
              </el-tag>
              <span v-else class="ml-8">{{ summary.system_recommendation.conclusion }}</span>
            </template>
            <div class="text-sm mt-8">
              <div v-if="averageScore !== null" class="mb-8">
                平均评分：
                <strong>{{ averageScore }}</strong> / 5
              </div>
              <div v-if="matchedRules.length" class="mb-8">
                匹配规则：
                <el-tag
                  v-for="rule in matchedRules"
                  :key="rule"
                  size="small"
                  type="info"
                  effect="plain"
                  class="tag-gap"
                >{{ rule }}</el-tag>
              </div>
              <div v-if="summary.system_recommendation.advisoryOnly" class="text-muted">
                （1-2 位审稿人时系统建议仅供参考，请人工判断）
              </div>
            </div>
          </el-alert>

          <!-- 分歧与一致点 -->
          <template v-if="(summary.conflict_points || []).length">
            <el-divider content-position="left">分歧点</el-divider>
            <div class="summary-text">
              <div v-for="(cp, i) in summary.conflict_points" :key="i">
                {{ cp.dimensionName }}：{{ cp.distributionText }}
              </div>
            </div>
          </template>
        </template>

        <el-empty v-else description="暂无汇总报告" :image-size="60" />
      </div>
    </el-card>

    <!-- 决策表单 -->
    <el-card shadow="never">
      <template #header><span>终审决策</span></template>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="终审结果" prop="decision" required>
          <el-radio-group v-model="form.decision">
            <el-radio value="ACCEPT">
              <el-tag type="success" size="small">接收</el-tag>
            </el-radio>
            <el-radio value="MINOR_REVISION">
              <el-tag type="warning" size="small">小修</el-tag>
            </el-radio>
            <el-radio value="MAJOR_REVISION">
              <el-tag type="warning" size="small">大修</el-tag>
            </el-radio>
            <el-radio value="REJECT">
              <el-tag type="danger" size="small">拒稿</el-tag>
            </el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="编辑部说明" prop="notes" required>
          <el-input
            v-model="form.notes"
            type="textarea"
            :rows="5"
            :maxlength="2000"
            show-word-limit
            placeholder="请输入编辑部终审说明（至少100字）..."
          />
        </el-form-item>

        <el-form-item label="向作者公开意见">
          <el-switch v-model="form.publish" />
          <span class="text-muted text-sm ml-12">开启后作者可查看已提交的审稿意见（双盲口径匿名化）</span>
        </el-form-item>

        <!-- 不一致说明（条件显示） -->
        <el-form-item v-if="needJustification" label="不一致理由" prop="justification" required>
          <div style="width: 100%">
            <el-alert type="warning" :closable="false" show-icon class="mb-16">
              您的决策（{{ currentDecisionLabel }}）与系统建议（{{ suggestedDecisionLabel }}）不一致，请说明理由。
            </el-alert>
            <el-input
              v-model="form.justification"
              type="textarea"
              :rows="4"
              :maxlength="1000"
              show-word-limit
              placeholder="请详细说明与系统建议不一致的理由..."
            />
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" size="large" @click="handleSubmit" :loading="submitting">
            提交终审决策
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 决策结果对话框 -->
    <el-dialog v-model="resultDialog" title="决策已提交" width="480" :close-on-click-modal="false">
      <el-result :icon="decisionResultIcon" :title="decisionResultTitle" sub-title="终审决策已成功提交">
        <template #extra>
          <el-button type="primary" @click="goToDetail">查看任务详情</el-button>
        </template>
      </el-result>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { taskApi, summaryApi } from '@/api/modules'
import { TASK_STATUS, RECOMMENDATION } from '@/utils/status'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const loading = ref(true)
const submitting = ref(false)
const resultDialog = ref(false)

const formRef = ref()
const taskInfo = ref({})
const summary = ref(null)

const form = reactive({
  decision: '',
  notes: '',
  justification: '',
  publish: true,
})

// 动态验证规则（justification 仅在不一致时必填；notes 后端要求≥100字）
const rules = computed(() => {
  const base = {
    decision: [{ required: true, message: '请选择终审结果', trigger: 'change' }],
    notes: [
      { required: true, message: '请输入编辑部说明', trigger: 'blur' },
      { min: 100, message: '决策说明至少100字', trigger: 'blur' },
    ],
  }
  if (needJustification.value) {
    base.justification = [{ required: true, message: '请说明不一致理由', trigger: 'blur' }]
  }
  return base
})

// ============ 计算属性 ============
const statusTag = computed(() => TASK_STATUS[taskInfo.value.status] || { label: '-', color: 'info' })

// 推荐分布统计（后端 dist 含 total 键，需剔除后再算占比）
const recommendationStats = computed(() => {
  const dist = summary.value?.recommendation_distribution || {}
  const total = (['ACCEPT', 'MINOR_REVISION', 'MAJOR_REVISION', 'REJECT'])
    .reduce((sum, k) => sum + (dist[k] || 0), 0) || 1
  return [
    { key: 'ACCEPT', label: '接收', count: dist.ACCEPT || 0, percent: Math.round((dist.ACCEPT || 0) / total * 100), color: 'success' },
    { key: 'MINOR_REVISION', label: '小修', count: dist.MINOR_REVISION || 0, percent: Math.round((dist.MINOR_REVISION || 0) / total * 100), color: 'warning' },
    { key: 'MAJOR_REVISION', label: '大修', count: dist.MAJOR_REVISION || 0, percent: Math.round((dist.MAJOR_REVISION || 0) / total * 100), color: 'warning' },
    { key: 'REJECT', label: '拒稿', count: dist.REJECT || 0, percent: Math.round((dist.REJECT || 0) / total * 100), color: 'danger' },
  ]
})

// 规则编号 -> 建议决策码（Rule-4/Rule-7 为分歧类，无直接建议）
const RULE_TO_DECISION = {
  'Rule-1': 'ACCEPT',
  'Rule-2': 'ACCEPT',
  'Rule-3': 'MINOR_REVISION',
  'Rule-5': 'MAJOR_REVISION',
  'Rule-6': 'REJECT',
}

// 系统建议决策
const suggestedDecision = computed(() => {
  const ruleId = summary.value?.system_recommendation?.matchedRuleId
  return RULE_TO_DECISION[ruleId] || ''
})

const suggestedDecisionLabel = computed(() => {
  return RECOMMENDATION[suggestedDecision.value]?.label || suggestedDecision.value || '-'
})

// 匹配规则列表
const matchedRules = computed(() => {
  const ruleId = summary.value?.system_recommendation?.matchedRuleId
  return ruleId ? [ruleId] : []
})

// 平均评分（从 dimension_comparison 现算）
const averageScore = computed(() => {
  const dims = summary.value?.dimension_comparison || []
  const scores = dims.flatMap(d => (d.scores || []))
    .map(s => s.score)
    .filter(s => typeof s === 'number')
  if (scores.length === 0) return null
  return (scores.reduce((sum, s) => sum + s, 0) / scores.length).toFixed(2)
})

// 是否需要不一致说明
const needJustification = computed(() => {
  if (!form.decision || !suggestedDecision.value) return false
  return form.decision !== suggestedDecision.value
})

const suggestionAlertType = computed(() => {
  return RECOMMENDATION[suggestedDecision.value]?.color || 'info'
})

// 当前决策标签
const currentDecisionLabel = computed(() => {
  return RECOMMENDATION[form.decision]?.label || form.decision || '-'
})

// 决策结果展示
const decisionResultIcon = computed(() => {
  const map = {
    ACCEPT: 'success',
    MINOR_REVISION: 'warning',
    MAJOR_REVISION: 'warning',
    REJECT: 'error',
  }
  return map[form.decision] || 'info'
})

const decisionResultTitle = computed(() => {
  return `终审结果：${RECOMMENDATION[form.decision]?.label || form.decision}`
})

// ============ 提交 ============
const handleSubmit = () => {
  formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      let notes = form.notes
      // 如果决策与建议不一致，附加不一致理由
      if (needJustification.value && form.justification) {
        notes = `${form.notes}\n\n【与系统建议不一致的理由】\n${form.justification}`
      }
      await taskApi.makeDecision(taskId, {
        decision: form.decision,
        notes,
        publish: form.publish,
      })
      ElMessage.success('终审决策提交成功')
      resultDialog.value = true
    } catch (e) {
      // 错误由拦截器处理
    } finally {
      submitting.value = false
    }
  })
}

const goToDetail = () => {
  resultDialog.value = false
  router.push({ name: 'TaskDetail', params: { id: taskId } })
}

// ============ 初始化 ============
const fetchData = async () => {
  loading.value = true
  try {
    const task = await taskApi.retrieve(taskId)
    taskInfo.value = task

    // 尝试获取汇总报告
    try {
      const summaryRes = await summaryApi.detail(taskId)
      summary.value = summaryRes
    } catch (e) {
      // 可能还没有汇总报告
      summary.value = null
    }
  } catch (e) {
    console.error('Failed to fetch task:', e)
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.rec-stat-card {
  text-align: center;
  padding: 16px 8px;
  background: #f5f7fa;
  border-radius: 8px;
  transition: transform 0.2s;
}
.rec-stat-card:hover { transform: translateY(-2px); }
.rec-label { margin-bottom: 8px; }
.rec-count { font-size: 24px; font-weight: 700; color: #303133; }
.rec-percent { margin-top: 4px; }
.summary-text {
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.8;
  color: #606266;
  white-space: pre-wrap;
}
.tag-gap { margin-right: 6px; margin-bottom: 4px; }
.ml-8 { margin-left: 8px; }
.mb-8 { margin-bottom: 8px; }
</style>
