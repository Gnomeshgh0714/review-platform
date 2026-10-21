<template>
  <div class="ref-validation-page">
    <!-- 任务信息 -->
    <el-card shadow="never" class="mb-16">
      <div class="flex-between">
        <div>
          <h3>{{ taskInfo.title }}</h3>
          <p class="text-muted text-sm mt-8">编号：{{ taskInfo.task_id }} | 点击下方按钮验证稿件参考文献真实性</p>
        </div>
        <div class="gap-12 flex">
          <el-button text @click="$router.push(`/tasks/${taskId}`)">任务详情</el-button>
          <el-button text @click="$router.push(`/opinions/${taskId}`)">审稿意见</el-button>
          <el-button text @click="$router.back()">返回</el-button>
        </div>
      </div>
    </el-card>

    <!-- 验证操作区 -->
    <el-card shadow="never" class="mb-16">
      <div class="flex-between">
        <div>
          <el-icon size="20" color="#409eff"><Search /></el-icon>
          <span class="ml-8" style="font-weight: 600;">参考文献真实性验证</span>
          <span class="text-muted text-sm ml-12">交叉核对 CrossRef / OpenAlex 数据库，检测虚构引用、错误元数据</span>
        </div>
        <el-button type="primary" :loading="loading" @click="handleValidate" :disabled="done">
          <el-icon><Search /></el-icon>
          {{ done ? '已验证' : '开始验证' }}
        </el-button>
      </div>

      <!-- 进度条 -->
      <el-progress v-if="loading" :percentage="progress" :stroke-width="8" status="active" class="mt-16" />
    </el-card>

    <!-- 错误提示 -->
    <el-alert v-if="error" type="error" :title="error" :closable="true" show-icon class="mb-16" />
    <el-alert v-else-if="result?.error" type="warning" :title="result.error" :closable="false" show-icon class="mb-16" />

    <!-- 验证结果 -->
    <template v-if="result">
      <!-- 统计卡片 -->
      <el-row :gutter="12" class="mb-16">
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">总计</div>
            <div class="stat-value" style="color: #303133;">{{ result.total }}</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label text-success">✅ 已验证</div>
            <div class="stat-value text-success">{{ result.verified }}</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label text-warning">⚠️ 部分匹配</div>
            <div class="stat-value text-warning">{{ result.partial_match }}</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label text-danger">❌ 未找到/不匹配</div>
            <div class="stat-value text-danger">{{ result.mismatch + result.not_found }}</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 筛选栏 -->
      <el-card shadow="never" class="mb-16">
        <el-radio-group v-model="filter" size="small">
          <el-radio-button value="all">全部 ({{ result.results.length }})</el-radio-button>
          <el-radio-button value="verified">已验证 ({{ result.verified }})</el-radio-button>
          <el-radio-button value="partial_match">部分匹配 ({{ result.partial_match }})</el-radio-button>
          <el-radio-button value="mismatch">不匹配 ({{ result.mismatch }})</el-radio-button>
          <el-radio-button value="not_found">未找到 ({{ result.not_found }})</el-radio-button>
        </el-radio-group>
      </el-card>

      <!-- 结果列表 -->
      <el-card shadow="never">
        <template #header><span>参考文献验证结果</span></template>
        <div v-for="(item, idx) in filteredResults" :key="idx" class="ref-item">
          <div class="ref-header">
            <el-tag :type="statusTagType(item.status)" size="small">{{ statusLabel(item.status) }}</el-tag>
            <span class="text-muted text-sm">置信度: {{ item.match_confidence || 0 }}%</span>
            <span v-if="item.source" class="text-muted text-sm">来源: {{ item.source }}</span>
          </div>
          <div class="ref-input text-sm text-muted">{{ item.input }}</div>
          <template v-if="item.exists">
            <div class="ref-detail">
              <strong>{{ item.title }}</strong>
              <p class="text-sm mt-4">
                <span v-if="item.authors">{{ item.authors }}</span>
                <span v-if="item.year"> ({{ item.year }})</span>
                <span v-if="item.journal">. {{ item.journal }}</span>
              </p>
              <div class="ref-meta mt-4">
                <el-tag v-if="item.doi" size="small" effect="plain">DOI: {{ item.doi }}</el-tag>
                <el-tag v-if="item.citations !== undefined" size="small" effect="plain">引用: {{ item.citations }}</el-tag>
                <el-tag v-if="item.retracted" type="danger" size="small" effect="dark">🚨 已撤稿</el-tag>
              </div>
            </div>
          </template>
          <div v-if="item.issues && item.issues.length" class="ref-issues">
            <el-text type="warning" size="small" v-for="(issue, i) in item.issues" :key="i">⚠️ {{ issue }}</el-text>
          </div>
        </div>
        <el-empty v-if="filteredResults.length === 0" description="无匹配结果" />
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { formApi, taskApi } from '@/api/modules'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

const route = useRoute()
const taskId = route.params.taskId

const loading = ref(false)
const done = ref(false)
const error = ref('')
const progress = ref(0)
const result = ref(null)
const taskInfo = ref({})
const filter = ref('all')

const filteredResults = computed(() => {
  if (!result.value) return []
  if (filter.value === 'all') return result.value.results
  return result.value.results.filter(r => r.status === filter.value)
})

const statusTagType = (status) => {
  const map = { verified: 'success', partial_match: 'warning', mismatch: 'danger', not_found: 'info' }
  return map[status] || 'info'
}

const statusLabel = (status) => {
  const map = { verified: '✅ 已验证', partial_match: '⚠️ 部分匹配', mismatch: '❌ 不匹配', not_found: '🔍 未找到' }
  return map[status] || status
}

const handleValidate = async () => {
  loading.value = true
  error.value = ''
  progress.value = 10
  result.value = null

  // 模拟进度更新（实际进度由后端处理时间决定）
  const progressTimer = setInterval(() => {
    if (progress.value < 90) progress.value += 5
  }, 3000)

  try {
    const res = await formApi.validateReferences(taskId)
    result.value = res
    done.value = true
    progress.value = 100
    ElMessage.success(`验证完成：${res.verified}/${res.total} 条参考文献已验证`)
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '参考文献验证失败'
  } finally {
    clearInterval(progressTimer)
    loading.value = false
  }
}

onMounted(async () => {
  try {
    taskInfo.value = await taskApi.retrieve(taskId)
  } catch (e) { /* ignore */ }
})
</script>

<style scoped>
.stat-card { text-align: center; padding: 8px 0; }
.stat-label { font-size: 13px; color: #909399; }
.stat-value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.ref-item {
  padding: 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  margin-bottom: 12px;
}
.ref-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ref-input {
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 8px;
  line-height: 1.6;
}
.ref-detail { padding: 8px 0; }
.ref-detail strong { font-size: 14px; color: #303133; }
.ref-meta { display: flex; gap: 4px; flex-wrap: wrap; }
.ref-issues { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.mt-4 { margin-top: 4px; }
</style>
