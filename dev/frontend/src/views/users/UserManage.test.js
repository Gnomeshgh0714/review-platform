// #024 前端用户管理测试：EDITOR 路由可达 / 非 EDITOR 守卫重定向 /
// 列表渲染（StandardPagination）/ 页内权限防御。设施沿用 #017：
// happy-dom + 真实 Pinia + ElementPlus 真实插件挂载，api 模块按依赖 mock，
// 守卫用例走真实 router（懒加载组件仅 resolve 不挂载，echarts 重型 Dashboard stub 掉）。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'

vi.mock('@/api/modules', () => ({
  userApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
  notificationApi: { unreadCount: vi.fn().mockResolvedValue({ unread_count: 0 }) },
}))
vi.mock('@/views/Dashboard.vue', () => ({ default: { name: 'DashboardStub', render: () => null } }))

import UserManage from '@/views/users/UserManage.vue'
import router from '@/router'
import { userApi } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'

function loginAs(roles) {
  const auth = useAuthStore()
  auth.token = 'test-token'
  auth.user = { user_id: 'u0', name: '当前用户', email: 'me@review.local', roles }
}

// 后端 StandardPagination 返回结构（count/next/previous/results）
const PAGE = {
  count: 3,
  next: null,
  previous: null,
  results: [
    { user_id: 'u1', name: '张三', email: 'zhang@review.local', roles: ['EDITOR'], institution: '中山大学', research_areas: ['宏观经济学'], created_at: '2026-10-01T10:00:00Z' },
    { user_id: 'u2', name: '李四', email: 'li@review.local', roles: ['REVIEWER', 'AUTHOR'], institution: '', research_areas: [], created_at: '2026-10-02T10:00:00Z' },
    { user_id: 'u3', name: '王五', email: 'wang@review.local', roles: ['AUTHOR'], institution: '北京大学', research_areas: ['气候经济学'], created_at: '2026-10-03T10:00:00Z' },
  ],
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  userApi.list.mockResolvedValue({ ...PAGE })
})

describe('UserManage 路由权限（真实 router 守卫）', () => {
  it('EDITOR 访问 /users 可达用户管理页', async () => {
    loginAs(['EDITOR'])
    await router.push('/users')
    expect(router.currentRoute.value.name).toBe('UserManage')
  })

  it('非 EDITOR（审稿人）访问 /users 被守卫重定向回工作台概览', async () => {
    loginAs(['REVIEWER'])
    // 先离开 /users（上一用例抵达过），确保守卫真实执行而非同路径幂等跳过
    await router.push('/dashboard')
    await router.push('/users')
    expect(router.currentRoute.value.name).toBe('Dashboard')
  })
})

describe('UserManage 列表渲染与页内权限', () => {
  it('EDITOR 挂载后按分页参数请求列表并渲染用户行、多角色标签与研究方向', async () => {
    loginAs(['EDITOR'])
    const wrapper = mount(UserManage, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(userApi.list).toHaveBeenCalledWith({ page: 1, page_size: 20 })
    const rows = wrapper.findAll('.el-table__row')
    expect(rows.length).toBe(3)
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('li@review.local')
    // 双角色（REVIEWER + AUTHOR）渲染两个 el-tag，三个用户共 4 个角色标签
    expect(wrapper.findAll('.el-tag').length).toBe(4)
    expect(wrapper.text()).toContain('编辑部')
    expect(wrapper.text()).toContain('审稿人')
    expect(wrapper.text()).toContain('作者')
    // 研究方向数组拼接展示
    expect(wrapper.text()).toContain('宏观经济学')
    // 后端 count 接入分页 total（zh-cn locale 未注入时 ElementPlus 输出 Total N）
    expect(wrapper.find('.el-pagination').text()).toContain('3')
  })

  it('非 EDITOR 直接挂载时仅渲染无权限空态，不请求列表（页内防御层）', async () => {
    loginAs(['AUTHOR'])
    const wrapper = mount(UserManage, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('仅编辑部可访问用户管理')
    expect(userApi.list).not.toHaveBeenCalled()
  })
})
