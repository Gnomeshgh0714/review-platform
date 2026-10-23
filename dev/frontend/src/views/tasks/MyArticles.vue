<template>
  <div class="my-articles">
    <!-- 页面头部 -->
    <el-card class="mb-16" shadow="never">
      <div class="flex-between">
        <div>
          <h2>我的稿件</h2>
          <p class="text-muted text-sm mt-8">查看您提交的稿件状态及审稿进度</p>
        </div>
        <el-button type="primary" :icon="Refresh" plain @click="fetchArticles">刷新</el-button>
      </div>
    </el-card>

    <!-- 稿件表格 -->
    <el-card shadow="never">
      <el-table
        v-loading="loading"
        :data="articles"
        style="width: 100%"
        stripe
        empty-text="暂无稿件"
      >
        <!-- 稿件标题 -->
        <el-table-column label="稿件标题" min-width="220">
          <template #default="{ row }">
            <div class="article-title-cell">
              <span class="article-title" @click="goToProgress(row)">{{ row.title }}</span>
              <span class="text-muted text-sm">编号：{{ row.task_id }}</span>
            </div>
          </template>
        </el-table-column>

        <!-- 状态 -->
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag
              :type="getStatusTag(TASK_STATUS, row.status).color"
              effect="light"
              size="small"
            >
              {{ getStatusTag(TASK_STATUS, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>

        <!-- 审稿进度 -->
        <el-table-column label="审稿进度" width="200" align="center">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="getProgressPercent(row)"
                :color="getProgressColor(row)"
                :stroke-width="14"
                :text-inside="true"
                :status="getProgressStatus(row)"
              />
              <span class="text-muted text-sm mt-8">
                {{ submittedCount(row) }} / {{ (row.assignments || []).length }} 已提交意见
              </span>
            </div>
          </template>
        </el-table-column>

        <!-- 截止日期 -->
        <el-table-column label="截止日期" width="160" align="center">
          <template #default="{ row }">
            <div class="flex-center" style="flex-direction: column; gap: 4px;">
              <span class="text-sm">{{ formatDateOnly(row.deadline) }}</span>
              <el-tag
                :type="deadlineStatus(row.deadline).color"
                effect="plain"
                size="small"
              >
                {{ deadlineStatus(row.deadline).text }}
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <!-- 创建时间 -->
        <el-table-column label="创建时间" width="160" align="center">
          <template #default="{ row }">
            <span class="text-sm text-muted">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>

        <!-- 操作 -->
        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="goToProgress(row)">
              <el-icon style="margin-right: 4px"><View /></el-icon>
              查看进度
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper mt-16" v-if="total > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          background
          @current-change="fetchArticles"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, View } from '@element-plus/icons-vue'
import { taskApi } from '@/api/modules'
import { TASK_STATUS, getStatusTag, formatDate, formatDateOnly, deadlineStatus } from '@/utils/status'

const router = useRouter()

// ============ 状态 ============
const loading = ref(false)
const articles = ref([])
// V1.2 建议#9：my_articles 端点不消费 page/page_size（全量返回），
// 此前翻页控件点击后仍渲染全量列表（假分页）；改为客户端切片分页
const allArticles = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

// ============ 获取数据 ============
const fetchArticles = async () => {
  loading.value = true
  try {
    const res = await taskApi.myArticles({
      page: currentPage.value,
      page_size: pageSize.value,
    })
    allArticles.value = res.results || res || []
    total.value = allArticles.value.length
    if (currentPage.value > 1 && (currentPage.value - 1) * pageSize.value >= total.value) {
      currentPage.value = 1
    }
    articles.value = allArticles.value.slice(
      (currentPage.value - 1) * pageSize.value,
      currentPage.value * pageSize.value,
    )
  } catch (e) {
    console.error('获取稿件列表失败:', e)
  } finally {
    loading.value = false
  }
}

// ============ 进度计算 ============
// 审稿进度从 assignments 现算（作者视角下 assignments 仍含 assignment_status，仅隐去身份）
const submittedCount = (row) =>
  (row.assignments || []).filter(a => a.assignment_status === 'SUBMITTED').length

const getProgressPercent = (row) => {
  const total = (row.assignments || []).length
  if (total === 0) return 0
  return Math.round((submittedCount(row) / total) * 100)
}

const getProgressColor = (row) => {
  const percent = getProgressPercent(row)
  if (percent === 100) return '#67c23a'
  if (percent >= 50) return '#409eff'
  return '#e6a23c'
}

const getProgressStatus = (row) => {
  const percent = getProgressPercent(row)
  if (percent === 100) return 'success'
  return undefined
}

// ============ 跳转 ============
const goToProgress = (row) => {
  router.push(`/articles/${row.task_id}/progress`)
}

// ============ 初始化 ============
onMounted(() => {
  fetchArticles()
})
</script>

<style scoped>
.my-articles h2 {
  font-size: 20px;
  color: #303133;
}
.article-title-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.article-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  cursor: pointer;
  transition: color 0.2s;
}
.article-title:hover {
  color: #409eff;
}
.progress-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.pagination-wrapper {
  display: flex;
  justify-content: center;
}
</style>
