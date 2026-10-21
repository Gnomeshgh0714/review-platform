<template>
  <div class="summary-list-page">
    <el-card shadow="never">
      <template #header>
        <div class="flex-between">
          <span>汇总报告列表</span>
          <el-button type="primary" @click="showGenerate = true">生成汇总报告</el-button>
        </div>
      </template>

      <!-- 表格字段与 SummaryReportBriefSerializer 对齐：task_title/task_id/system_recommendation/generated_at -->
      <el-table :data="list" v-loading="loading" border>
        <el-table-column prop="task_title" label="稿件标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="task_id" label="任务编号" width="160" />
        <el-table-column label="系统建议" min-width="280">
          <template #default="{ row }">
            <template v-if="row.system_recommendation">
              <el-tag v-if="row.system_recommendation.matchedRuleId" size="small" class="mr-8">
                {{ row.system_recommendation.matchedRuleId }}
              </el-tag>
              <span class="text-sm">{{ row.system_recommendation.conclusion || '-' }}</span>
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="generated_at" label="生成时间" width="160">
          <template #default="{ row }">{{ formatDate(row.generated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="$router.push(`/summaries/${row.task_id}`)">查看详情</el-button>
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

    <!-- 生成报告对话框 -->
    <el-dialog v-model="showGenerate" title="生成汇总报告" width="450">
      <el-form label-position="top">
        <el-form-item label="选择任务（需为待汇总状态）">
          <el-select v-model="selectedTask" placeholder="选择任务" filterable style="width: 100%">
            <el-option
              v-for="t in pendingTasks"
              :key="t.task_id"
              :label="`${t.task_id} - ${t.title}`"
              :value="t.task_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGenerate = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="handleGenerate">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { summaryApi, taskApi } from '@/api/modules'
import { formatDate } from '@/utils/status'
import { ElMessage } from 'element-plus'

const router = useRouter()

const loading = ref(true)
const list = ref([])
const total = ref(0)
const page = ref(1)

const showGenerate = ref(false)
const generating = ref(false)
const selectedTask = ref('')
const pendingTasks = ref([])

const fetchList = async () => {
  loading.value = true
  try {
    const res = await summaryApi.list({ page: page.value })
    list.value = res.results || res
    total.value = res.count || list.value.length
  } catch (e) {
    console.error('Failed to fetch summaries:', e)
  } finally {
    loading.value = false
  }
}

const fetchPendingTasks = async () => {
  try {
    // /tasks/ 列表不支持状态筛选，编辑部用 dashboard 端点按 SUBMITTED 过滤
    const res = await taskApi.dashboard({ status: 'SUBMITTED' })
    pendingTasks.value = res.results || res || []
  } catch (e) { /* ignore */ }
}

const handleGenerate = async () => {
  if (!selectedTask.value) {
    ElMessage.warning('请选择任务')
    return
  }
  generating.value = true
  try {
    await summaryApi.generate(selectedTask.value)
    ElMessage.success('汇总报告生成成功')
    showGenerate.value = false
    fetchList()
    router.push(`/summaries/${selectedTask.value}`)
  } catch (e) {
    // 错误提示由 axios 拦截器统一处理
  } finally {
    generating.value = false
  }
}

onMounted(() => {
  fetchList()
  fetchPendingTasks()
})
</script>

<style scoped>
.mr-8 { margin-right: 8px; }
</style>
