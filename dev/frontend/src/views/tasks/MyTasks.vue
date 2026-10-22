<template>
  <div class="my-tasks">
    <!-- 页面头部 -->
    <el-card class="mb-16" shadow="never">
      <div class="flex-between">
        <div>
          <h2>我的审稿任务</h2>
          <p class="text-muted text-sm mt-8">管理您收到的审稿邀请及进行中的任务</p>
        </div>
        <el-button type="primary" :icon="Refresh" plain @click="fetchTasks">刷新</el-button>
      </div>
    </el-card>

    <!-- Tab 分类 -->
    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- 待响应邀请 -->
        <el-tab-pane name="invited">
          <template #label>
            <span class="flex-center gap-8">
              待响应邀请
              <el-badge v-if="counts.invited" :value="counts.invited" :max="99" type="primary" />
            </span>
          </template>
        </el-tab-pane>

        <!-- 审稿中 -->
        <el-tab-pane name="reviewing">
          <template #label>
            <span class="flex-center gap-8">
              审稿中
              <el-badge v-if="counts.reviewing" :value="counts.reviewing" :max="99" type="warning" />
            </span>
          </template>
        </el-tab-pane>

        <!-- 已提交 -->
        <el-tab-pane name="submitted">
          <template #label>
            <span class="flex-center gap-8">
              已提交
              <el-badge v-if="counts.submitted" :value="counts.submitted" :max="99" type="success" />
            </span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <!-- 加载状态 -->
      <div v-loading="loading" class="task-list-wrapper">
        <!-- 任务卡片列表（数据为分配记录，键位与 ReviewAssignmentSerializer 对齐） -->
        <div v-if="filteredAssignments.length > 0" class="task-card-list">
          <div v-for="a in filteredAssignments" :key="a.assignment_id" class="task-card">
            <!-- 卡片头部：标题 + 状态标签 -->
            <div class="task-card-header flex-between">
              <div class="task-title-block flex-1">
                <h3 class="task-title" @click="goToReview(a)">{{ a.task_title }}</h3>
                <span class="task-number text-muted text-sm">编号：{{ a.task }}</span>
              </div>
              <el-tag
                :type="getStatusTag(ASSIGNMENT_STATUS, a.assignment_status).color"
                size="large"
                effect="light"
              >
                {{ getStatusTag(ASSIGNMENT_STATUS, a.assignment_status).label }}
              </el-tag>
            </div>

            <!-- 卡片信息 -->
            <div class="task-card-body">
              <div class="task-info-row flex gap-24">
                <div class="task-info-item">
                  <span class="text-muted text-sm">审稿截止日期</span>
                  <div class="mt-8">
                    <el-tag
                      :type="deadlineStatus(a.deadline).color"
                      effect="plain"
                      size="small"
                    >
                      <el-icon style="margin-right: 4px"><Calendar /></el-icon>
                      {{ deadlineStatus(a.deadline).text }}
                    </el-tag>
                  </div>
                </div>
                <div class="task-info-item" v-if="a.assigned_at">
                  <span class="text-muted text-sm">分配时间</span>
                  <div class="mt-8 text-sm">{{ formatDate(a.assigned_at) }}</div>
                </div>
                <div class="task-info-item" v-if="a.submitted_at">
                  <span class="text-muted text-sm">提交时间</span>
                  <div class="mt-8 text-sm">{{ formatDate(a.submitted_at) }}</div>
                </div>
              </div>
            </div>

            <!-- 卡片操作 -->
            <div class="task-card-footer flex-between">
              <span class="text-muted text-sm">{{ a.invitation_note || '暂无邀请说明' }}</span>
              <div class="flex gap-12">
                <!-- INVITED 状态：接受 / 拒绝 -->
                <template v-if="a.assignment_status === 'INVITED'">
                  <el-button type="success" :loading="actionLoading[a.assignment_id]" @click="handleAccept(a)">
                    接受邀请
                  </el-button>
                  <!-- V1.2 一般#30：接受请求进行中禁用拒绝入口，防止接受/拒绝并发发出、
                       UI 先后弹出两个互相矛盾的成功提示 -->
                  <el-button type="danger" plain :disabled="actionLoading[a.assignment_id]" @click="openRejectDialog(a)">
                    拒绝
                  </el-button>
                </template>

                <!-- ACCEPTED/REVIEWING 状态：进入审稿 -->
                <template v-if="['ACCEPTED', 'REVIEWING'].includes(a.assignment_status)">
                  <el-button type="primary" @click="goToReview(a)">
                    进入审稿
                    <el-icon style="margin-left: 4px"><Right /></el-icon>
                  </el-button>
                </template>

                <!-- 已提交状态：查看意见 -->
                <template v-if="a.assignment_status === 'SUBMITTED'">
                  <el-button type="info" plain @click="goToOpinion(a)">查看意见</el-button>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <el-empty v-else-if="!loading" description="暂无任务">
          <template #image>
            <el-icon :size="64" color="#dcdfe6"><DocumentRemove /></el-icon>
          </template>
        </el-empty>
      </div>
    </el-card>

    <!-- 拒绝邀请对话框 -->
    <el-dialog v-model="rejectDialog.visible" title="拒绝审稿邀请" width="480px">
      <el-form>
        <el-form-item label="任务" label-width="80px">
          <span>{{ rejectDialog.assignment?.task_title }}</span>
        </el-form-item>
        <el-form-item label="拒绝原因" label-width="80px">
          <el-input
            v-model="rejectDialog.reason"
            type="textarea"
            :rows="4"
            placeholder="请简要说明拒绝原因（选填）"
            maxlength="500"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectDialog.visible = false">取消</el-button>
        <el-button type="danger" :loading="rejectDialog.loading" @click="handleReject">确认拒绝</el-button>
    </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Calendar, Right, DocumentRemove } from '@element-plus/icons-vue'
import { taskApi } from '@/api/modules'
import { ASSIGNMENT_STATUS, getStatusTag, formatDate, deadlineStatus } from '@/utils/status'

const router = useRouter()

// ============ 状态 ============
const loading = ref(false)
const activeTab = ref('invited')
const assignments = ref([])
const actionLoading = reactive({}) // 按 assignment_id 记录按钮 loading

// Tab 计数（按 assignment_status 分组）
const counts = computed(() => ({
  invited: assignments.value.filter((a) => a.assignment_status === 'INVITED').length,
  reviewing: assignments.value.filter((a) =>
    ['ACCEPTED', 'REVIEWING'].includes(a.assignment_status)).length,
  submitted: assignments.value.filter((a) => a.assignment_status === 'SUBMITTED').length,
}))

// 按 Tab 过滤
const filteredAssignments = computed(() => {
  switch (activeTab.value) {
    case 'invited':
      return assignments.value.filter((a) => a.assignment_status === 'INVITED')
    case 'reviewing':
      return assignments.value.filter((a) =>
        ['ACCEPTED', 'REVIEWING'].includes(a.assignment_status))
    case 'submitted':
      return assignments.value.filter((a) => a.assignment_status === 'SUBMITTED')
    default:
      return []
  }
})

// 拒绝对话框
const rejectDialog = reactive({
  visible: false,
  loading: false,
  assignment: null,
  reason: '',
})

// ============ 获取数据 ============
const fetchTasks = async () => {
  loading.value = true
  try {
    const res = await taskApi.myTasks()
    assignments.value = res.results || res || []
  } catch (e) {
    console.error('获取任务列表失败:', e)
  } finally {
    loading.value = false
  }
}

// ============ 接受邀请 ============
const handleAccept = async (a) => {
  try {
    await ElMessageBox.confirm(
      `确认接受任务「${a.task_title}」的审稿邀请？`,
      '接受邀请',
      { confirmButtonText: '确认接受', cancelButtonText: '取消', type: 'info' }
    )
  } catch {
    return // 用户取消
  }

  actionLoading[a.assignment_id] = true
  try {
    await taskApi.acceptInvitation(a.task)
    ElMessage.success('已接受邀请')
    await fetchTasks()
  } catch (e) {
    console.error('接受邀请失败:', e)
  } finally {
    actionLoading[a.assignment_id] = false
  }
}

// ============ 拒绝邀请 ============
const openRejectDialog = (a) => {
  rejectDialog.assignment = a
  rejectDialog.reason = ''
  rejectDialog.visible = true
}

const handleReject = async () => {
  if (!rejectDialog.assignment) return
  rejectDialog.loading = true
  try {
    await taskApi.rejectInvitation(rejectDialog.assignment.task, {
      reason: rejectDialog.reason,
    })
    ElMessage.success('已拒绝邀请')
    rejectDialog.visible = false
    await fetchTasks()
  } catch (e) {
    console.error('拒绝邀请失败:', e)
  } finally {
    rejectDialog.loading = false
  }
}

// ============ 跳转 ============
const goToReview = (a) => {
  router.push(`/review/${a.task}`)
}

const goToOpinion = (a) => {
  router.push(`/opinions/${a.task}`)
}

// ============ 初始化 ============
onMounted(fetchTasks)
</script>

<style scoped>
.my-tasks h2 {
  font-size: 20px;
  color: #303133;
}
.task-list-wrapper {
  min-height: 200px;
}
.task-card-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.task-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 20px;
  background: #fff;
  transition: all 0.2s;
}
.task-card:hover {
  border-color: #409eff;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.1);
}
.task-card-header {
  margin-bottom: 16px;
}
.task-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  cursor: pointer;
  transition: color 0.2s;
}
.task-title:hover {
  color: #409eff;
}
.task-number {
  display: inline-block;
  margin-top: 4px;
}
.task-card-body {
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}
.task-info-item {
  min-width: 140px;
}
.task-card-footer {
  padding-top: 16px;
}
</style>
