<template>
  <div class="task-assign-page">
    <!-- 任务基本信息 -->
    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="flex-between">
          <span>任务信息</span>
          <el-button text @click="$router.back()">返回</el-button>
        </div>
      </template>
      <el-descriptions :column="3" border v-loading="taskLoading">
        <el-descriptions-item label="稿件标题">{{ taskInfo.title }}</el-descriptions-item>
        <el-descriptions-item label="任务编号">{{ taskInfo.task_id }}</el-descriptions-item>
        <el-descriptions-item label="学科">{{ taskInfo.subject_area || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 审稿人搜索 -->
    <el-card shadow="never" class="mb-16">
      <template #header><span>搜索审稿人</span></template>
      <el-form :inline="true" :model="searchForm" @submit.prevent>
        <el-form-item label="学科筛选">
          <el-select v-model="searchForm.subject" placeholder="全部学科" clearable filterable style="width: 180px">
            <el-option v-for="s in subjectOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input
            v-model="searchForm.keyword"
            placeholder="姓名 / 邮箱 / 专长"
            clearable
            style="width: 240px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch" :loading="searching">
            <el-icon class="mr-4"><Search /></el-icon>搜索
          </el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 审稿人列表 -->
    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="flex-between">
          <span>
            审稿人列表
            <el-tag type="primary" size="small" class="ml-8">已选 {{ selectedReviewers.length }} / 5</el-tag>
          </span>
          <el-button text @click="handleSearch">刷新</el-button>
        </div>
      </template>
      <el-table
        ref="tableRef"
        :data="reviewers"
        v-loading="searching"
        :max-height="520"
        :default-sort="{ prop: 'match', order: 'descending' }"
        @select="handleSelect"
        @select-all="handleSelectAll"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" />
        <el-table-column prop="name" label="姓名" width="120" />
        <el-table-column prop="email" label="邮箱" width="220" show-overflow-tooltip />
        <el-table-column label="机构" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.institution || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="专长标签" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="tag in (row.research_areas || [])"
              :key="tag"
              size="small"
              type="info"
              effect="plain"
              class="tag-gap"
            >{{ tag }}</el-tag>
            <span v-if="!row.research_areas || row.research_areas.length === 0" class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="match" label="匹配度" width="150" align="center" sortable :sort-method="sortByMatch">
          <template #default="{ row }">
            <div class="match-cell">
              <el-progress
                :percentage="matchScore(row)"
                :color="matchColor(matchScore(row))"
                :show-text="false"
                :stroke-width="8"
              />
              <span class="match-text" :style="{ color: matchColor(matchScore(row)) }">{{ matchScore(row) }}%</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!searching && reviewers.length === 0" description="暂无匹配的审稿人" :image-size="60" />
    </el-card>

    <!-- 分配设置 -->
    <el-card shadow="never">
      <template #header><span>分配设置</span></template>
      <el-form label-width="120px">
        <el-form-item label="审稿截止日期" required>
          <el-date-picker
            v-model="deadline"
            type="date"
            placeholder="选择截止日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            :disabled-date="disabledDate"
            style="width: 220px"
          />
          <span class="text-muted text-sm ml-12">默认 14 天后</span>
        </el-form-item>
        <el-form-item label="已选审稿人">
          <div v-if="selectedReviewers.length === 0" class="text-muted">尚未选择审稿人</div>
          <div v-else class="selected-list">
            <el-tag
              v-for="(r, i) in selectedReviewers"
              :key="r.user_id"
              closable
              @close="removeReviewer(r)"
              class="tag-gap"
            >
              {{ i + 1 }}. {{ r.name }}
            </el-tag>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            @click="handleAssign"
            :disabled="selectedReviewers.length === 0"
          >
            确认分配（{{ selectedReviewers.length }} 人）
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 确认对话框 -->
    <el-dialog v-model="confirmDialog" title="确认分配审稿人" width="560">
      <el-alert type="info" :closable="false" show-icon class="mb-16">
        分配后将向审稿人发送邀请通知，请确认以下信息。
      </el-alert>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="任务">
          {{ taskInfo.title }}（{{ taskInfo.task_id }}）
        </el-descriptions-item>
        <el-descriptions-item label="审稿人">
          <div v-for="(r, i) in selectedReviewers" :key="r.user_id" class="reviewer-line">
            {{ i + 1 }}. {{ r.name }} - {{ r.email }}
            <el-tag size="small" type="info" class="ml-8">{{ (r.research_areas || []).join(' / ') || '-' }}</el-tag>
          </div>
        </el-descriptions-item>
        <el-descriptions-item label="审稿截止日期">{{ deadline }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="confirmDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmAssign" :loading="assigning">确认分配</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { taskApi, userApi } from '@/api/modules'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const tableRef = ref()
const taskLoading = ref(true)
const searching = ref(false)
const assigning = ref(false)
const confirmDialog = ref(false)

const taskInfo = ref({})
const reviewers = ref([])
const selectedReviewers = ref([])

const searchForm = reactive({
  subject: '',
  keyword: '',
})

// 学科选项：与后端 research_areas 取值口径一致（演示数据为中文专长名）
const subjectOptions = [
  '气候经济学', '劳动经济学', '应用计量',
  '环境经济学', '政策评估', '宏观经济学', '发展经济学',
]

// 默认 14 天后
const deadline = ref(dayjs().add(14, 'day').format('YYYY-MM-DD'))

// 禁用今天之前的日期
const disabledDate = (date) => {
  return date.getTime() < Date.now() - 86400000
}

// ============ 匹配度计算 ============
const matchScore = (reviewer) => {
  if (!reviewer) return 0
  let score = 50 // 基础分
  // 学科匹配 +30（任务学科出现在审稿人专长中）
  const subject = (taskInfo.value.subject_area || '').toLowerCase()
  if (subject && (reviewer.research_areas || []).some(
    t => (t || '').toLowerCase().includes(subject) || subject.includes((t || '').toLowerCase()),
  )) {
    score += 30
  }
  // 专长标签匹配（与标题关键词匹配，每个 +10，最多 +20）
  const title = (taskInfo.value.title || '').toLowerCase()
  const titleKeywords = title.split(/[\s,，、;；:：]+/).filter(k => k.length > 1)
  const reviewerTags = (reviewer.research_areas || []).map(t => t.toLowerCase())
  let tagMatches = 0
  for (const tag of reviewerTags) {
    // 标签直接出现在标题中
    if (title.includes(tag)) {
      tagMatches++
      continue
    }
    // 标签与标题关键词有包含关系
    for (const kw of titleKeywords) {
      if (tag.includes(kw) || kw.includes(tag)) {
        tagMatches++
        break
      }
    }
  }
  score += Math.min(tagMatches * 10, 20)
  return Math.min(score, 100)
}

const matchColor = (score) => {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#409eff'
  if (score >= 40) return '#e6a23c'
  return '#909399'
}

// 按匹配度排序（降序）
const sortByMatch = (a, b) => matchScore(b) - matchScore(a)

// ============ 多选控制（最多 5 人）============
const handleSelect = (selection, row) => {
  if (selection.length > 5) {
    ElMessage.warning('最多只能选择 5 位审稿人')
    tableRef.value.toggleRowSelection(row, false)
  }
}

const handleSelectAll = (selection) => {
  if (selection.length > 5) {
    ElMessage.warning('最多只能选择 5 位审稿人，已取消全选')
    tableRef.value.clearSelection()
  }
}

const handleSelectionChange = (val) => {
  selectedReviewers.value = val
}

// 移除已选审稿人
const removeReviewer = (reviewer) => {
  tableRef.value.toggleRowSelection(reviewer, false)
}

// ============ 搜索 ============
const handleSearch = async () => {
  searching.value = true
  try {
    const params = {}
    if (searchForm.subject) params.subject = searchForm.subject
    if (searchForm.keyword) params.keyword = searchForm.keyword
    const res = await userApi.getReviewers(params)
    reviewers.value = res.results || res || []
    // 数据加载后重新按匹配度排序
    nextTick(() => {
      tableRef.value?.sort('match', 'descending')
    })
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    searching.value = false
  }
}

const handleReset = () => {
  searchForm.subject = ''
  searchForm.keyword = ''
  handleSearch()
}

// ============ 分配 ============
const handleAssign = () => {
  if (selectedReviewers.value.length === 0) {
    ElMessage.warning('请至少选择一位审稿人')
    return
  }
  if (!deadline.value) {
    ElMessage.warning('请选择审稿截止日期')
    return
  }
  confirmDialog.value = true
}

const confirmAssign = async () => {
  assigning.value = true
  try {
    await taskApi.assignReviewers(taskId, {
      reviewer_user_ids: selectedReviewers.value.map(r => r.user_id),
      deadline: deadline.value,
    })
    ElMessage.success('审稿人分配成功')
    confirmDialog.value = false
    router.push({ name: 'TaskDetail', params: { id: taskId } })
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    assigning.value = false
  }
}

// ============ 初始化 ============
const fetchTask = async () => {
  taskLoading.value = true
  try {
    const res = await taskApi.retrieve(taskId)
    taskInfo.value = res
    // 预填学科筛选为任务学科
    if (res.subject_area) {
      searchForm.subject = res.subject_area
    }
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    taskLoading.value = false
  }
}

onMounted(async () => {
  await fetchTask()
  await handleSearch()
})
</script>

<style scoped>
.tag-gap { margin-right: 6px; margin-bottom: 4px; }
.ml-8 { margin-left: 8px; }
.ml-12 { margin-left: 12px; }
.mr-4 { margin-right: 4px; }
.match-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.match-cell .el-progress { flex: 1; }
.match-text { font-size: 13px; font-weight: 600; min-width: 36px; text-align: right; }
.selected-list { display: flex; flex-wrap: wrap; gap: 4px; }
.reviewer-line { margin-bottom: 4px; }
</style>
