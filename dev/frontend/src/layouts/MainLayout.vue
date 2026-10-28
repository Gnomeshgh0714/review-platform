<template>
  <el-container class="main-layout">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapse ? '64px' : '220px'" class="sidebar">
      <div class="logo-area" @click="router.push('/dashboard')">
        <el-icon size="24" color="#409eff"><Reading /></el-icon>
        <span v-show="!isCollapse" class="logo-text">审稿协作平台</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        router
        class="sidebar-menu"
      >
        <template v-for="item in menuItems" :key="item.path">
          <el-menu-item :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" :size="20" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="currentTitle">{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <!-- 通知 -->
          <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
            <el-icon class="cursor-pointer" :size="20" @click="showNotifications = true">
              <Bell />
            </el-icon>
          </el-badge>

          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-avatar :size="32" :icon="UserFilled" />
              <span class="user-name">{{ auth.displayName }}</span>
              <el-tag size="small" type="info">{{ auth.roleLabel }}</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile" :icon="User">个人中心</el-dropdown-item>
                <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>

    <!-- 通知抽屉 -->
    <el-drawer v-model="showNotifications" title="通知消息" size="400px" direction="rtl">
      <NotificationList @read="updateUnreadCount" />
    </el-drawer>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { notificationApi } from '@/api/modules'
import { ElMessageBox } from 'element-plus'
import NotificationList from '@/components/NotificationList.vue'
import { UserFilled, User, SwitchButton, Reading, Bell, Fold, Expand } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const isCollapse = ref(false)
const showNotifications = ref(false)
const unreadCount = ref(0)

const currentTitle = computed(() => route.meta.title || '')

const activeMenu = computed(() => {
  // 匹配父级路径
  const path = route.path
  if (path.startsWith('/tasks')) return '/tasks'
  if (path.startsWith('/summaries')) return '/summaries'
  if (path.startsWith('/knowledge')) return '/knowledge'
  if (path.startsWith('/my-tasks')) return '/my-tasks'
  if (path.startsWith('/my-articles')) return '/my-articles'
  return path
})

// 根据角色生成菜单
const allMenus = [
  { path: '/dashboard', title: '工作台概览', icon: 'HomeFilled', roles: ['EDITOR', 'REVIEWER', 'AUTHOR'] },
  { path: '/tasks', title: '任务看板', icon: 'List', roles: ['EDITOR'] },
  { path: '/my-tasks', title: '我的审稿任务', icon: 'EditPen', roles: ['REVIEWER'] },
  { path: '/my-articles', title: '我的稿件', icon: 'Document', roles: ['AUTHOR'] },
  { path: '/summaries', title: '汇总报告', icon: 'DataAnalysis', roles: ['EDITOR'] },
  { path: '/knowledge', title: '知识库检索', icon: 'Search', roles: ['EDITOR', 'REVIEWER'] },
  { path: '/knowledge/review', title: '匿名化审核', icon: 'CircleCheck', roles: ['EDITOR'] },
  { path: '/templates', title: '模板管理', icon: 'Files', roles: ['EDITOR'] },
  // #024 用户管理：icon 用 UserFilled 避免与个人中心（User）重复
  { path: '/users', title: '用户管理', icon: 'UserFilled', roles: ['EDITOR'] },
  { path: '/profile', title: '个人中心', icon: 'User', roles: ['EDITOR', 'REVIEWER', 'AUTHOR'] },
]

const menuItems = computed(() => {
  const role = auth.primaryRole || (auth.user?.roles?.[0]) || auth.user?.role
  if (!role) return []
  return allMenus.filter(m => m.roles.includes(role))
})

const handleCommand = (command) => {
  if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    }).then(() => {
      auth.logout()
      router.push('/login')
    }).catch(() => {})
  }
}

const updateUnreadCount = async () => {
  try {
    const res = await notificationApi.unreadCount()
    unreadCount.value = res.unread_count || 0
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  updateUnreadCount()
  // 每30秒刷新未读数
  setInterval(updateUnreadCount, 30000)
})
</script>

<style scoped>
.main-layout {
  height: 100vh;
}

.sidebar {
  background-color: #304156;
  transition: width 0.3s;
  overflow: hidden;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
}

.logo-text {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
}

.sidebar-menu {
  border-right: none;
  background-color: transparent;
}

:deep(.el-menu) {
  background-color: transparent;
}

:deep(.el-menu-item) {
  color: #bfcbd9;
}

:deep(.el-menu-item:hover) {
  background-color: #263445;
  color: #fff;
}

:deep(.el-menu-item.is-active) {
  color: #409eff;
  background-color: #1f2d3d;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e6e6e6;
  padding: 0 16px;
  height: 56px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn {
  cursor: pointer;
  color: #606266;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.user-name {
  font-size: 14px;
  color: #303133;
}

.main-content {
  background: #f5f7fa;
  padding: 16px;
  overflow-y: auto;
}
</style>
