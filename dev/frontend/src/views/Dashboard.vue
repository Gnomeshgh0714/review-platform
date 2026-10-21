<template>
  <div class="dashboard">
    <!-- 欢迎区 -->
    <el-card class="welcome-card mb-16" shadow="never">
      <div class="flex-between">
        <div>
          <h2>欢迎回来，{{ auth.displayName }}</h2>
          <p class="text-muted mt-8">{{ auth.roleLabel }} · {{ auth.user?.email }}</p>
        </div>
        <el-icon size="48" color="#409eff"><Reading /></el-icon>
      </div>
    </el-card>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="mb-16">
      <el-col :span="6" v-for="card in statCards" :key="card.label">
        <el-card shadow="hover" class="stat-card">
          <div class="flex-between">
            <div>
              <div class="stat-label">{{ card.label }}</div>
              <div class="stat-value" :style="{ color: card.color }">{{ card.value }}</div>
            </div>
            <el-icon :size="36" :color="card.color">
              <component :is="card.icon" />
            </el-icon>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷入口 -->
    <el-card shadow="never">
      <template #header>
        <span>快捷操作</span>
      </template>
      <el-row :gutter="16">
        <el-col :span="4" v-for="action in quickActions" :key="action.path">
          <div class="quick-action" @click="router.push(action.path)">
            <el-icon :size="28" :color="action.color">
              <component :is="action.icon" />
            </el-icon>
            <span class="action-text">{{ action.title }}</span>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 最近通知 -->
    <el-card shadow="never" class="mt-16">
      <template #header>
        <div class="flex-between">
          <span>最近通知</span>
          <el-button text @click="showNotif = true">查看全部</el-button>
        </div>
      </template>
      <el-timeline>
        <el-timeline-item
          v-for="n in recentNotifs"
          :key="n.notification_id"
          :timestamp="formatDate(n.created_at)"
          :type="n.is_read ? '' : 'primary'"
        >
          <div class="notif-item">
            <strong>{{ n.title }}</strong>
            <p class="text-muted text-sm">{{ n.content }}</p>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="recentNotifs.length === 0" description="暂无通知" :image-size="60" />
    </el-card>

    <!-- 通知抽屉 -->
    <el-drawer v-model="showNotif" title="通知消息" size="400px" direction="rtl">
      <NotificationList />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { taskApi, notificationApi } from '@/api/modules'
import { formatDate } from '@/utils/status'
import NotificationList from '@/components/NotificationList.vue'
import { Reading } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()

const stats = ref({})
const recentNotifs = ref([])
const showNotif = ref(false)

const statCards = computed(() => {
  const role = auth.primaryRole || auth.user?.roles?.[0] || auth.user?.role
  if (role === 'EDITOR') {
    return [
      { label: '待分配任务', value: stats.value.pending || 0, icon: 'Clock', color: '#909399' },
      { label: '审稿中', value: stats.value.reviewing || 0, icon: 'EditPen', color: '#e6a23c' },
      { label: '待汇总', value: stats.value.submitted || 0, icon: 'CircleCheck', color: '#67c23a' },
      { label: '已决策', value: stats.value.decided || 0, icon: 'Select', color: '#20c997' },
    ]
  }
  if (role === 'REVIEWER') {
    return [
      { label: '待响应邀请', value: stats.value.assigned || 0, icon: 'User', color: '#409eff' },
      { label: '审稿中', value: stats.value.reviewing || 0, icon: 'EditPen', color: '#e6a23c' },
      { label: '已提交', value: stats.value.submitted || 0, icon: 'CircleCheck', color: '#67c23a' },
      { label: '总任务', value: stats.value.total || 0, icon: 'List', color: '#6f42c1' },
    ]
  }
  return [
    { label: '我的稿件', value: stats.value.total || 0, icon: 'Document', color: '#409eff' },
    { label: '审稿中', value: stats.value.reviewing || 0, icon: 'EditPen', color: '#e6a23c' },
    { label: '已决策', value: stats.value.decided || 0, icon: 'Select', color: '#20c997' },
    { label: '已归档', value: stats.value.archived || 0, icon: 'FolderOpened', color: '#909399' },
  ]
})

const quickActions = computed(() => {
  const role = auth.primaryRole || auth.user?.roles?.[0] || auth.user?.role
  const actions = {
    EDITOR: [
      { title: '创建任务', path: '/tasks/create', icon: 'Plus', color: '#409eff' },
      { title: '任务看板', path: '/tasks', icon: 'List', color: '#67c23a' },
      { title: '汇总报告', path: '/summaries', icon: 'DataAnalysis', color: '#6f42c1' },
      { title: '知识库', path: '/knowledge', icon: 'Search', color: '#e6a23c' },
      { title: '模板管理', path: '/templates', icon: 'Files', color: '#20c997' },
      { title: '匿名化审核', path: '/knowledge/review', icon: 'CircleCheck', color: '#f56c6c' },
    ],
    REVIEWER: [
      { title: '我的任务', path: '/my-tasks', icon: 'EditPen', color: '#409eff' },
      { title: '知识库', path: '/knowledge', icon: 'Search', color: '#67c23a' },
      { title: '个人中心', path: '/profile', icon: 'User', color: '#909399' },
    ],
    AUTHOR: [
      { title: '我的稿件', path: '/my-articles', icon: 'Document', color: '#409eff' },
      { title: '个人中心', path: '/profile', icon: 'User', color: '#909399' },
    ],
  }
  return actions[role] || []
})

const fetchDashboard = async () => {
  try {
    const role = auth.primaryRole || auth.user?.roles?.[0] || auth.user?.role
    if (role === 'EDITOR') {
      // dashboard 端点返回任务列表（每页20），翻页取全后按状态现算
      const all = []
      let page = 1
      for (;;) {
        const res = await taskApi.dashboard({ page })
        const rows = res.results || res || []
        all.push(...rows)
        const total = res.count || all.length
        if (all.length >= total || rows.length === 0) break
        page += 1
      }
      const countBy = (s) => all.filter(t => t.status === s).length
      stats.value = {
        pending: countBy('PENDING'),
        reviewing: countBy('REVIEWING'),
        submitted: countBy('SUBMITTED'),
        decided: countBy('DECIDED'),
      }
    } else if (role === 'REVIEWER') {
      // my_tasks 返回分配记录（assignment_status），按状态现算
      const res = await taskApi.myTasks()
      const rows = res.results || res || []
      const countBy = (...ss) => rows.filter(a => ss.includes(a.assignment_status)).length
      stats.value = {
        assigned: countBy('INVITED'),
        reviewing: countBy('ACCEPTED', 'REVIEWING'),
        submitted: countBy('SUBMITTED'),
        total: rows.length,
      }
    } else if (role === 'AUTHOR') {
      // my_articles 返回稿件列表，按状态现算
      const res = await taskApi.myArticles()
      const rows = res.results || res || []
      const countBy = (s) => rows.filter(t => t.status === s).length
      stats.value = {
        total: rows.length,
        reviewing: countBy('REVIEWING'),
        decided: countBy('DECIDED'),
        archived: countBy('ARCHIVED'),
      }
    }
  } catch (e) {
    console.error('Dashboard fetch error:', e)
  }
}

const fetchNotifs = async () => {
  try {
    const res = await notificationApi.list({ page_size: 5 })
    recentNotifs.value = res.results || res
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  fetchDashboard()
  fetchNotifs()
})
</script>

<style scoped>
.welcome-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border: none;
}
:deep(.welcome-card .el-card__body) { padding: 24px; }
.welcome-card h2 { color: #fff; }
.welcome-card p { color: rgba(255,255,255,0.8); }
.stat-card { text-align: left; }
.stat-label { font-size: 13px; color: #909399; }
.stat-value { font-size: 32px; font-weight: 700; margin-top: 4px; }
.quick-action {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.quick-action:hover { background: #f5f7fa; }
.action-text { font-size: 13px; color: #606266; }
.notif-item p { margin-top: 4px; }
</style>
