import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '工作台概览', icon: 'HomeFilled' },
      },
      // 编辑部
      {
        path: 'tasks',
        name: 'TaskList',
        component: () => import('@/views/tasks/TaskList.vue'),
        meta: { title: '任务看板', icon: 'List', roles: ['EDITOR'] },
      },
      {
        path: 'tasks/create',
        name: 'TaskCreate',
        component: () => import('@/views/tasks/TaskCreate.vue'),
        meta: { title: '创建审稿任务', roles: ['EDITOR'] },
      },
      {
        path: 'tasks/:id',
        name: 'TaskDetail',
        component: () => import('@/views/tasks/TaskDetail.vue'),
        meta: { title: '任务详情' },
      },
      {
        path: 'tasks/:id/assign',
        name: 'TaskAssign',
        component: () => import('@/views/tasks/TaskAssign.vue'),
        meta: { title: '分配审稿人', roles: ['EDITOR'] },
      },
      {
        path: 'tasks/:id/decision',
        name: 'TaskDecision',
        component: () => import('@/views/tasks/TaskDecision.vue'),
        meta: { title: '终审决策', roles: ['EDITOR'] },
      },
      // 审稿人
      {
        path: 'my-tasks',
        name: 'MyTasks',
        component: () => import('@/views/tasks/MyTasks.vue'),
        meta: { title: '我的审稿任务', icon: 'EditPen', roles: ['REVIEWER'] },
      },
      {
        path: 'review/:taskId',
        name: 'ReviewForm',
        component: () => import('@/views/review/ReviewForm.vue'),
        meta: { title: '审稿工作台', roles: ['REVIEWER'] },
      },
      {
        path: 'opinions/:taskId',
        name: 'OpinionView',
        component: () => import('@/views/review/OpinionView.vue'),
        meta: { title: '审稿意见' },
      },
      {
        path: 'refs/:taskId',
        name: 'RefValidation',
        component: () => import('@/views/review/RefValidation.vue'),
        meta: { title: '参考文献验证', roles: ['EDITOR', 'REVIEWER'] },
      },
      // 作者
      {
        path: 'my-articles',
        name: 'MyArticles',
        component: () => import('@/views/tasks/MyArticles.vue'),
        meta: { title: '我的稿件', icon: 'Document', roles: ['AUTHOR'] },
      },
      {
        path: 'articles/:id/progress',
        name: 'ArticleProgress',
        component: () => import('@/views/tasks/ArticleProgress.vue'),
        meta: { title: '稿件进度', roles: ['AUTHOR'] },
      },
      // 汇总报告
      {
        path: 'summaries',
        name: 'SummaryList',
        component: () => import('@/views/summaries/SummaryList.vue'),
        meta: { title: '汇总报告', icon: 'DataAnalysis', roles: ['EDITOR'] },
      },
      {
        path: 'summaries/:taskId',
        name: 'SummaryDetail',
        component: () => import('@/views/summaries/SummaryDetail.vue'),
        meta: { title: '报告详情' },
      },
      // 知识库
      {
        path: 'knowledge',
        name: 'KnowledgeSearch',
        component: () => import('@/views/knowledge/KnowledgeSearch.vue'),
        meta: { title: '知识库检索', icon: 'Search', roles: ['EDITOR', 'REVIEWER'] },
      },
      {
        path: 'knowledge/review',
        name: 'KnowledgeReview',
        component: () => import('@/views/knowledge/KnowledgeReview.vue'),
        meta: { title: '匿名化审核', icon: 'CircleCheck', roles: ['EDITOR'] },
      },
      // 模板管理
      {
        path: 'templates',
        name: 'TemplateList',
        component: () => import('@/views/templates/TemplateList.vue'),
        meta: { title: '模板管理', icon: 'Files', roles: ['EDITOR'] },
      },
      // 用户管理（#024：后端 UserViewSet 五端点仅编辑部，F-2 前端落地）
      {
        path: 'users',
        name: 'UserManage',
        component: () => import('@/views/users/UserManage.vue'),
        meta: { title: '用户管理', icon: 'User', roles: ['EDITOR'] },
      },
      // 个人中心
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/Profile.vue'),
        meta: { title: '个人中心', icon: 'User' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
    meta: { public: true, title: '404' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  document.title = `${to.meta.title || ''} - 审稿协作平台`

  if (to.meta.public) {
    if (to.name === 'Login' && auth.isLoggedIn) {
      next({ name: 'Dashboard' })
    } else {
      next()
    }
    return
  }

  if (!auth.isLoggedIn) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  // 角色权限检查
  if (to.meta.roles && !to.meta.roles.some(r => (auth.user?.roles || []).includes(r) || auth.user?.role === r)) {
    next({ name: 'Dashboard' })
    return
  }

  next()
})

export default router
