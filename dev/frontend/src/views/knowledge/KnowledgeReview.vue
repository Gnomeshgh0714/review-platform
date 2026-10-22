<template>
  <div class="knowledge-review-page">
    <el-card shadow="never">
      <template #header>
        <div class="flex-between">
          <span>匿名化审核队列（待审核 / 已退回）</span>
          <el-button text @click="fetchList">刷新</el-button>
        </div>
      </template>

      <!-- 字段与 KnowledgeItemSerializer 对齐 -->
      <el-table :data="list" v-loading="loading" border>
        <el-table-column prop="source_task_id" label="来源任务" min-width="160" show-overflow-tooltip />
        <el-table-column prop="subject_area" label="学科" width="110" show-overflow-tooltip />
        <el-table-column prop="manuscript_type" label="稿件类型" width="100" />
        <el-table-column label="匿名化状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.anonymization_status === 'REJECTED' ? 'danger' : 'warning'" size="small">
              {{ row.anonymization_status_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="待审核段" width="100" align="center">
          <template #default="{ row }">
            <el-badge v-if="(row.pending_review_segments || []).length" :value="row.pending_review_segments.length" type="danger" />
            <span v-else class="text-muted">无</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="归档时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="handleReview(row)">审核</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > 20"
        class="mt-16"
        :total="total"
        :page-size="20"
        layout="total, prev, pager, next"
        v-model:current-page="page"
        @current-change="fetchList"
      />
    </el-card>

    <!-- 审核对话框 -->
    <el-dialog v-model="reviewDialog" title="匿名化审核" width="800" top="5vh">
      <div v-if="currentItem">
        <el-alert type="info" :closable="false" show-icon class="mb-16">
          <template #title>审核说明</template>
          <span>请逐段检查内容中是否含有作者身份信息（指代词、自引、机构名、基金编号等）。通过后内容将不可逆归档到知识库。</span>
        </el-alert>

        <el-descriptions :column="2" border class="mb-16">
          <el-descriptions-item label="来源任务">{{ currentItem.source_task_id }}</el-descriptions-item>
          <el-descriptions-item label="学科">{{ currentItem.subject_area || '-' }}</el-descriptions-item>
          <el-descriptions-item label="稿件类型">{{ currentItem.manuscript_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="终审决策">{{ currentItem.final_decision || '-' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 待审核段落（{type, label, matched, context, line}） -->
        <div v-if="(currentItem.pending_review_segments || []).length">
          <h4 class="mb-16">疑似身份信息段落（{{ currentItem.pending_review_segments.length }}）</h4>
          <div v-for="(seg, idx) in currentItem.pending_review_segments" :key="idx" class="segment-block">
            <div class="seg-header">
              <el-tag size="small" type="danger">{{ seg.label }}</el-tag>
              <span class="text-muted text-sm">第 {{ seg.line }} 行 · 命中：{{ seg.matched }}</span>
            </div>
            <div class="seg-content">{{ seg.context }}</div>
          </div>
        </div>
        <el-alert v-else type="success" :closable="false" show-icon class="mb-16"
          title="未检出疑似身份信息段落，可直接审核通过" />

        <!-- 全文预览 -->
        <el-divider />
        <h4 class="mb-16">匿名化摘要全文预览</h4>
        <div class="full-content">{{ currentItem.anonymized_summary || '（无摘要）' }}</div>

        <!-- 审核意见 -->
        <el-divider />
        <el-form>
          <el-form-item label="审核意见">
            <el-input v-model="reviewNote" type="textarea" :rows="3" placeholder="填写审核意见（退回修改时必填）" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="info" plain @click="handleExclude" :loading="submitting">永久不归档</el-button>
        <el-button type="danger" @click="handleReject" :loading="submitting">退回修改</el-button>
        <el-button type="success" @click="handleApprove" :loading="submitting">审核通过</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { knowledgeApi } from '@/api/modules'
import { formatDate } from '@/utils/status'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const submitting = ref(false)
const list = ref([])
const total = ref(0)
const page = ref(1)

const reviewDialog = ref(false)
const currentItem = ref(null)
const reviewNote = ref('')

const fetchList = async () => {
  loading.value = true
  try {
    const res = await knowledgeApi.pendingReviews({ page: page.value })
    list.value = res.results || []
    total.value = res.count || list.value.length
  } catch (e) {
    console.error('Failed to fetch pending reviews:', e)
  } finally {
    loading.value = false
  }
}

const handleReview = async (item) => {
  try {
    const detail = await knowledgeApi.detail(item.knowledge_id)
    currentItem.value = detail
    reviewNote.value = ''
    reviewDialog.value = true
  } catch (e) { /* handled */ }
}

// 审核接口入参：{decision: APPROVED/REJECTED/PERMANENTLY_EXCLUDED, notes}
// V1.2 一般#29：提交结果以布尔返回——接口失败时（拦截器已弹错）
// 调用方不得再无条件弹成功提示，否则条目仍在待审队列却显示「已归档」造成漏审假象
const submitReview = async (decision) => {
  if (!currentItem.value) return false
  submitting.value = true
  try {
    await knowledgeApi.reviewAnonymization(currentItem.value.knowledge_id, {
      decision,
      notes: reviewNote.value,
    })
    reviewDialog.value = false
    fetchList()
    return true
  } catch (e) {
    return false
  } finally {
    submitting.value = false
  }
}

const handleApprove = async () => {
  try {
    await ElMessageBox.confirm(
      '审核通过后内容将不可逆归档到知识库，确认通过？',
      '确认归档',
      { confirmButtonText: '确认通过', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  // V1.2 一般#29：仅在提交成功时提示
  const ok = await submitReview('APPROVED')
  if (ok) ElMessage.success('审核通过，已归档到知识库')
}

const handleReject = async () => {
  if (!reviewNote.value.trim()) {
    ElMessage.warning('退回修改时需填写审核意见')
    return
  }
  // V1.2 一般#29：仅在提交成功时提示
  const ok = await submitReview('REJECTED')
  if (ok) ElMessage.success('已退回修改')
}

const handleExclude = async () => {
  try {
    await ElMessageBox.confirm(
      '永久不归档后该条目将不再进入知识库，确认操作？',
      '确认排除',
      { confirmButtonText: '确认排除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  // V1.2 一般#29：仅在提交成功时提示
  const ok = await submitReview('PERMANENTLY_EXCLUDED')
  if (ok) ElMessage.success('已标记为永久不归档')
}

onMounted(fetchList)
</script>

<style scoped>
.segment-block {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  margin-bottom: 12px;
}
.seg-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.seg-content {
  padding: 8px 12px;
  background: #fef0f0;
  border-radius: 4px;
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
  line-height: 1.6;
}
.full-content {
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  max-height: 300px;
  overflow-y: auto;
}
</style>
