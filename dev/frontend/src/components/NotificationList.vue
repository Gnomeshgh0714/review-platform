<template>
  <div class="notification-list">
    <div class="notification-header">
      <el-button size="small" @click="markAllRead" :disabled="loading || list.length === 0">
        全部已读
      </el-button>
    </div>
    <el-scrollbar height="calc(100vh - 180px)">
      <div v-if="loading" class="loading-area">
        <el-skeleton :rows="3" animated />
      </div>
      <div v-else-if="list.length === 0" class="empty-area">
        <el-empty description="暂无通知" />
      </div>
      <div v-else>
        <div
          v-for="item in list"
          :key="item.notification_id"
          class="notification-item"
          :class="{ unread: !item.is_read }"
          @click="handleClick(item)"
        >
          <div class="notif-icon">
            <el-icon :size="20" :color="getIconColor(item.type)">
              <component :is="getIconName(item.type)" />
            </el-icon>
          </div>
          <div class="notif-content">
            <div class="notif-title">{{ item.title }}</div>
            <div class="notif-body">{{ item.content }}</div>
            <div class="notif-time">{{ formatTime(item.created_at) }}</div>
          </div>
          <el-tag v-if="!item.is_read" type="danger" size="small" effect="dark">新</el-tag>
        </div>
      </div>
    </el-scrollbar>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { notificationApi } from '@/api/modules'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const emit = defineEmits(['read'])

const list = ref([])
const loading = ref(true)

const getIconName = (type) => {
  const map = {
    ASSIGN: 'UserFilled',
    ACCEPT: 'CircleCheck',
    REJECT: 'CircleClose',
    SUBMIT: 'EditPen',
    SUMMARIZE: 'DataAnalysis',
    DECISION: 'Select',
    OVERDUE: 'Warning',
    SYSTEM: 'InfoFilled',
  }
  return map[type] || 'Bell'
}

const getIconColor = (type) => {
  const map = {
    ASSIGN: '#409eff',
    ACCEPT: '#67c23a',
    REJECT: '#f56c6c',
    SUBMIT: '#e6a23c',
    SUMMARIZE: '#6f42c1',
    DECISION: '#20c997',
    OVERDUE: '#f56c6c',
    SYSTEM: '#909399',
  }
  return map[type] || '#909399'
}

const formatTime = (time) => {
  return dayjs(time).fromNow()
}

const fetchList = async () => {
  loading.value = true
  try {
    const res = await notificationApi.list({ page_size: 50 })
    list.value = res.results || res
  } catch (e) {
    console.error('Failed to fetch notifications:', e)
  } finally {
    loading.value = false
  }
}

const handleClick = async (item) => {
  if (!item.is_read) {
    try {
      await notificationApi.markRead({ notification_ids: [item.notification_id] })
      item.is_read = true
      emit('read')
    } catch (e) { /* ignore */ }
  }
}

const markAllRead = async () => {
  try {
    await notificationApi.markAllRead()
    list.value.forEach(n => n.is_read = true)
    emit('read')
  } catch (e) { /* ignore */ }
}

onMounted(fetchList)
</script>

<style scoped>
.notification-list { padding: 0 8px; }
.notification-header { padding: 8px 0; text-align: right; }
.notification-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 8px;
  transition: background 0.2s;
}
.notification-item:hover { background: #f5f7fa; }
.notification-item.unread { background: #ecf5ff; }
.notif-icon { flex-shrink: 0; }
.notif-content { flex: 1; min-width: 0; }
.notif-title { font-size: 14px; font-weight: 500; color: #303133; }
.notif-body { font-size: 13px; color: #606266; margin-top: 4px; }
.notif-time { font-size: 12px; color: #909399; margin-top: 4px; }
.loading-area, .empty-area { padding: 20px; }
</style>
