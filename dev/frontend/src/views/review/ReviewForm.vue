<template>
  <div class="review-form-page">
    <!-- 任务信息 -->
    <el-card shadow="never" class="mb-16">
      <div class="flex-between">
        <div>
          <h3>{{ taskInfo.title }}</h3>
          <p class="text-muted text-sm mt-8">
            编号：{{ taskInfo.task_id }} | 学科：{{ taskInfo.subject_area || '-' }} | 截止：{{ formatDate(taskInfo.deadline) }}
          </p>
        </div>
        <div class="auto-save-status">
          <el-tag v-if="autoSaveStatus === 'saving'" type="warning" size="small">保存中...</el-tag>
          <el-tag v-else-if="autoSaveStatus === 'saved'" type="success" size="small">已自动保存</el-tag>
          <el-tag v-else-if="autoSaveStatus === 'error'" type="danger" size="small">保存失败</el-tag>
        </div>
      </div>
    </el-card>

    <div v-loading="loading">
      <!-- V1.2 一般#28：已提交意见回填后切只读，防止误改与自动保存每 60 秒报 400 -->
      <el-alert
        v-if="submitted"
        type="success"
        title="审稿意见已提交，以下内容为只读查看"
        :closable="false"
        show-icon
        class="mb-16"
      />

      <!-- AI 辅助审稿 -->
      <el-card shadow="never" class="mb-16">
        <div class="flex-between">
          <div>
            <el-icon size="20" color="#6f42c1"><MagicStick /></el-icon>
            <span class="ml-8" style="font-weight: 600;">AI 辅助审稿</span>
            <span class="text-muted text-sm ml-12">调用 AI 自动分析稿件，生成评分和评语草稿，审稿人可在基础上修改</span>
          </div>
          <!-- V1.2 一般#28：已提交后禁用 AI 重新生成 -->
          <el-button type="primary" plain :loading="aiLoading" @click="handleAIReview" :disabled="aiDone || submitted">
            <el-icon><MagicStick /></el-icon>
            {{ aiDone ? '已生成' : 'AI 生成审稿意见' }}
          </el-button>
        </div>
        <el-alert v-if="aiError" type="error" :title="aiError" :closable="true" show-icon class="mt-8" />
        <el-alert v-if="aiDone" type="success" title="AI 审稿意见已生成，请检查并修改后提交" :closable="false" show-icon class="mt-8" />
      </el-card>

      <!-- 维度评分表单 -->
      <el-card shadow="never" class="mb-16">
        <template #header>
          <span>审稿评分（共 {{ dimensions.length }} 个维度）</span>
        </template>

        <div v-for="(dim, index) in dimensions" :key="dim.dimensionId" class="dimension-block">
          <div class="dimension-header">
            <div>
              <span class="dim-code">{{ index + 1 }}. {{ dim.dimensionName }}</span>
              <el-tooltip v-if="dim.description" :content="dim.description" placement="top">
                <el-icon class="cursor-pointer ml-4"><InfoFilled /></el-icon>
              </el-tooltip>
            </div>
          </div>

          <el-form label-position="top" class="dim-form">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="评分（1-5分）" required>
                  <el-radio-group v-model="formData.scores[dim.dimensionId]" :disabled="submitted" @change="onFormChange">
                    <el-radio-button v-for="n in 5" :key="n" :value="n">
                      {{ n }}分
                    </el-radio-button>
                  </el-radio-group>
                  <span v-if="formData.scores[dim.dimensionId]" class="score-hint">
                    {{ scoreLabels[formData.scores[dim.dimensionId]] }}
                  </span>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item :label="`评语（不少于${dim.minWords || 50}字）`" required>
                  <el-input
                    v-model="formData.comments[dim.dimensionId]"
                    type="textarea"
                    :rows="3"
                    :maxlength="500"
                    show-word-limit
                    placeholder="请针对此维度撰写具体评审意见..."
                    :disabled="submitted"
                    @input="onFormChange"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
          <el-divider v-if="index < dimensions.length - 1" />
        </div>
      </el-card>

      <!-- 综合评价 -->
      <el-card shadow="never" class="mb-16">
        <template #header><span>综合评价</span></template>
        <el-form label-position="top">
          <el-form-item label="总体推荐意见" required>
            <el-radio-group v-model="formData.recommendation" :disabled="submitted" @change="onFormChange">
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

          <el-form-item label="综合评语（不少于100字）" required>
            <el-input
              v-model="formData.overall_comment"
              type="textarea"
              :rows="5"
              :maxlength="2000"
              show-word-limit
              placeholder="请对论文进行总体评价，包括主要贡献、存在的问题及修改建议..."
              :disabled="submitted"
              @input="onFormChange"
            />
          </el-form-item>

          <el-form-item label="修改建议（选填）">
            <el-input
              v-model="formData.suggestions"
              type="textarea"
              :rows="3"
              :maxlength="1000"
              show-word-limit
              placeholder="具体修改建议（按条目列出）"
              :disabled="submitted"
              @input="onFormChange"
            />
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 操作按钮 -->
      <div class="form-actions">
        <el-button text @click="$router.push(`/refs/${taskId}`)">
          <el-icon><Search /></el-icon> 参考文献验证
        </el-button>
        <el-button text @click="$router.push(`/opinions/${taskId}`)">查看已有意见</el-button>
        <!-- V1.2 一般#28：已提交后隐藏保存/提交入口，仅保留只读查看 -->
        <template v-if="!submitted">
          <el-button @click="handleSaveDraft" :loading="savingDraft">保存草稿</el-button>
          <el-button type="primary" @click="handleSubmit" :loading="submitting">提交审稿意见</el-button>
        </template>
      </div>
    </div>

    <!-- 提交确认对话框 -->
    <el-dialog v-model="submitDialog" title="确认提交" width="500">
      <el-alert type="warning" :closable="false" show-icon class="mb-16">
        提交后审稿意见将不可修改，请确认所有信息填写完整。
      </el-alert>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="推荐意见">
          <el-tag :type="recommendationTag.type">{{ recommendationTag.label }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="维度评分">
          <span v-for="dim in dimensions" :key="dim.dimensionId">
            {{ dim.dimensionName }}: {{ formData.scores[dim.dimensionId] || '-' }}分；
          </span>
        </el-descriptions-item>
        <!-- V1.2 一般#27：展示口径与校验口径一致（trim 后长度） -->
        <el-descriptions-item label="综合评语字数">{{ formData.overall_comment?.trim().length || 0 }} 字</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="submitDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmSubmit" :loading="submitting">确认提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { formApi, taskApi } from '@/api/modules'
import { formatDate, RECOMMENDATION } from '@/utils/status'
import { ElMessage } from 'element-plus'
import { InfoFilled, MagicStick } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.taskId

const loading = ref(true)
// V1.2 一般#28：意见已提交（my_opinion 返回 SUBMITTED）时整表切只读
const submitted = ref(false)
const savingDraft = ref(false)
const submitting = ref(false)
const submitDialog = ref(false)
const autoSaveStatus = ref('') // '', 'saving', 'saved', 'error'

// AI 审稿相关状态
const aiLoading = ref(false)
const aiDone = ref(false)
const aiError = ref('')

const taskInfo = ref({})
const dimensions = ref([])

const scoreLabels = {
  1: '极差', 2: '较差', 3: '一般', 4: '良好', 5: '优秀'
}

const formData = reactive({
  scores: {},
  comments: {},
  recommendation: '',
  overall_comment: '',
  suggestions: '',
})

let autoSaveTimer = null
let hasChanges = false

const recommendationTag = computed(() => {
  return RECOMMENDATION[formData.recommendation] || { label: '-', type: 'info' }
})

const onFormChange = () => {
  hasChanges = true
  autoSaveStatus.value = ''
}

// 组装提交/草稿载荷：scores/comments 映射 -> 后端 dimension_scores 数组
const buildPayload = () => ({
  task_id: taskId,
  dimension_scores: dimensions.value
    .map(dim => ({
      dimensionId: dim.dimensionId,
      score: formData.scores[dim.dimensionId] || null,
      comment: formData.comments[dim.dimensionId] || '',
    }))
    .filter(ds => ds.score !== null || ds.comment),
  recommendation: formData.recommendation || '',
  overall_comment: formData.overall_comment || '',
  // 修改建议文本按行拆分为数组（后端 revision_suggestions: [str]）
  revision_suggestions: (formData.suggestions || '')
    .split('\n')
    .map(s => s.trim())
    .filter(Boolean),
})

// 自动保存（60秒间隔）
const startAutoSave = () => {
  autoSaveTimer = setInterval(async () => {
    // V1.2 一般#28：已提交意见不再自动保存（save_draft 对 SUBMITTED 状态报 400）
    if (hasChanges && !submitted.value && formData.recommendation) {
      await saveDraft(true)
    }
  }, 60000)
}

// 页面关闭/刷新前保存
const beforeUnloadHandler = (e) => {
  if (hasChanges) {
    e.preventDefault()
    e.returnValue = ''
  }
}

const saveDraft = async (isAuto = false) => {
  if (isAuto) autoSaveStatus.value = 'saving'
  try {
    await formApi.saveDraft(buildPayload())
    hasChanges = false
    if (isAuto) autoSaveStatus.value = 'saved'
    return true
  } catch (e) {
    if (isAuto) autoSaveStatus.value = 'error'
    return false
  }
}

const handleSaveDraft = async () => {
  savingDraft.value = true
  const ok = await saveDraft(false)
  savingDraft.value = false
  if (ok) ElMessage.success('草稿已保存')
}

const validateForm = () => {
  // 检查所有维度评分（字数下限取模板 minWords，与后端校验同口径）
  for (const dim of dimensions.value) {
    if (!formData.scores[dim.dimensionId] || formData.scores[dim.dimensionId] < 1) {
      ElMessage.warning(`请为「${dim.dimensionName}」评分`)
      return false
    }
    const minWords = dim.minWords || 50
    // V1.2 一般#27：与后端 strip 后长度同口径（apps/forms/services.py），
    // 空格凑字数前端不再放行（原按原始 length 校验，后端 400 被吞成笼统提示）
    const commentLen = (formData.comments[dim.dimensionId] || '').trim().length
    if (commentLen < minWords) {
      ElMessage.warning(`「${dim.dimensionName}」评语不少于${minWords}字`)
      return false
    }
  }
  if (!formData.recommendation) {
    ElMessage.warning('请选择总体推荐意见')
    return false
  }
  // V1.2 一般#27：综合评语同口径按 trim 后长度校验
  if (!formData.overall_comment || formData.overall_comment.trim().length < 100) {
    ElMessage.warning('综合评语不少于100字')
    return false
  }
  return true
}

const handleSubmit = () => {
  if (!validateForm()) return
  submitDialog.value = true
}

const confirmSubmit = async () => {
  submitting.value = true
  try {
    // 评审意见 V1.2 致命#1：api/modules 只有 submitOpinion，原 formApi.submit
    // 调用不存在的方法抛 TypeError 被 catch 静默吞掉，提交 UI 100% 失效
    await formApi.submitOpinion(buildPayload())
    ElMessage.success('审稿意见提交成功')
    submitDialog.value = false
    router.push('/my-tasks')
  } catch (e) {
    // HTTP 错误已由拦截器提示；此处兜底记录非 HTTP 异常，避免再次静默吞错
    console.error('审稿意见提交失败:', e)
  } finally {
    submitting.value = false
  }
}

// AI 辅助审稿
const handleAIReview = async () => {
  aiLoading.value = true
  aiError.value = ''
  try {
    const result = await formApi.aiReview(taskId)

    // 自动填充维度评分和评语
    if (result.dimension_scores) {
      for (const ds of result.dimension_scores) {
        const dimId = ds.dimensionId || ds.dimension_id
        formData.scores[dimId] = ds.score
        formData.comments[dimId] = ds.comment || ''
      }
    }

    // 填充推荐意见
    if (result.recommendation) {
      formData.recommendation = result.recommendation
    }

    // 填充综合评语
    if (result.overall_comment) {
      formData.overall_comment = result.overall_comment
    }

    // 填充修改建议
    if (result.suggestions && result.suggestions.length) {
      formData.suggestions = Array.isArray(result.suggestions)
        ? result.suggestions.join('\n')
        : result.suggestions
    }

    aiDone.value = true
    hasChanges = true
    ElMessage.success('AI 审稿意见已生成，请检查并修改')
  } catch (e) {
    aiError.value = e.response?.data?.error || e.message || 'AI 审稿调用失败'
    ElMessage.error('AI 审稿失败，请手动填写或稍后重试')
  } finally {
    aiLoading.value = false
  }
}

const fetchData = async () => {
  loading.value = true
  try {
    // 获取任务信息
    const task = await taskApi.retrieve(taskId)
    taskInfo.value = task

    // 获取审稿表单（模板快照，维度结构 {dimensionId, dimensionName, description, minWords}）
    const formRes = await formApi.getForm(taskId)
    dimensions.value = formRes.dimensions || formRes.template_snapshot?.dimensions || []

    // 初始化分数对象
    dimensions.value.forEach(dim => {
      if (!formData.scores[dim.dimensionId]) formData.scores[dim.dimensionId] = null
    })

    // 尝试加载已有草稿（dimension_scores 数组回填为映射）
    try {
      const draft = await formApi.myOpinion(taskId)
      // V1.2 一般#28：SUBMITTED 意见同样回填并切只读——原先只回填 DRAFT，
      // 已提交审稿人重进得到空白可编辑表单，自动保存每 60 秒报一次 400
      if (draft && (draft.status === 'DRAFT' || draft.status === 'SUBMITTED')) {
        for (const ds of (draft.dimension_scores || [])) {
          const dimId = ds.dimensionId || ds.dimension_id
          if (ds.score !== null && ds.score !== undefined) {
            formData.scores[dimId] = ds.score
          }
          formData.comments[dimId] = ds.comment || ''
        }
        formData.recommendation = draft.recommendation || ''
        formData.overall_comment = draft.overall_comment || ''
        formData.suggestions = (draft.revision_suggestions || []).join('\n')
        hasChanges = false
        if (draft.status === 'SUBMITTED') {
          submitted.value = true
        }
      }
    } catch (e) { /* no draft yet */ }
  } catch (e) {
    console.error('Failed to load form:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
  startAutoSave()
  window.addEventListener('beforeunload', beforeUnloadHandler)
})

onUnmounted(() => {
  if (autoSaveTimer) clearInterval(autoSaveTimer)
  window.removeEventListener('beforeunload', beforeUnloadHandler)
})
</script>

<style scoped>
.dimension-block { padding: 8px 0; }
.dim-code { font-size: 15px; font-weight: 600; color: #303133; }
.ml-4 { margin-left: 4px; }
.score-hint { margin-left: 12px; font-size: 13px; color: #909399; }
.form-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  padding: 16px 0;
}
.auto-save-status { min-width: 80px; text-align: right; }
</style>
