// 代表性组件测试：OpinionView 的 #015 遗留1 角色分流（编辑部 > 作者 > 审稿人）
// 与 opinionTitle 归属标注。api 模块与路由按依赖 mock，Pinia 走真实实现，
// Element Plus 用真实插件挂载，断言落在渲染出的 DOM 上。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'

vi.mock('@/api/modules', () => ({
  userApi: {},
  taskApi: { retrieve: vi.fn() },
  formApi: { myOpinion: vi.fn(), taskOpinions: vi.fn() },
}))
vi.mock('vue-router', () => ({
  // OpinionView 仅用到 useRoute；模板里的 $router 只在按钮点击时求值，不触达
  useRoute: () => ({ params: { taskId: 'T1' } }),
}))

import OpinionView from '@/views/review/OpinionView.vue'
import { formApi, taskApi } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'

const TASK = { task_id: 'T1', title: '气候风险论文', subject_area: '经济学', status: 'REVIEWING' }

function opinion(overrides = {}) {
  return {
    opinion_id: 'o1',
    recommendation: 'ACCEPT',
    submitted_at: '2026-10-01T10:00:00Z',
    dimension_scores: [{ dimensionId: 'D1', score: 5, comment: '论证扎实' }],
    overall_comment: '整体质量较高。',
    revision_suggestions: ['补充稳健性检验'],
    ...overrides,
  }
}

async function mountView() {
  const wrapper = mount(OpinionView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  taskApi.retrieve.mockResolvedValue({ ...TASK })
})

describe('OpinionView 角色分流与意见标题', () => {
  it('审稿人视角：走 my_opinion，标题为「我的审稿意见」，DRAFT 草稿有标记', async () => {
    useAuthStore().user = { roles: ['REVIEWER'], name: 'R1' }
    formApi.myOpinion.mockResolvedValue(opinion({ opinion_id: 'mine', status: 'DRAFT' }))

    const wrapper = await mountView()

    expect(formApi.myOpinion).toHaveBeenCalledWith('T1')
    expect(formApi.taskOpinions).not.toHaveBeenCalled()
    const labels = wrapper.findAll('.reviewer-label').map((n) => n.text())
    expect(labels).toEqual(['我的审稿意见'])
    expect(wrapper.text()).toContain('草稿')
  })

  it('编辑部视角：走 task_opinions，标题带序号，有姓名时显示实名', async () => {
    useAuthStore().user = { roles: ['EDITOR'], name: 'E1' }
    formApi.taskOpinions.mockResolvedValue({
      results: [opinion({ reviewer_name: '张三' }), opinion({ opinion_id: 'o2', reviewer_name: '' })],
    })

    const wrapper = await mountView()

    expect(formApi.taskOpinions).toHaveBeenCalledWith('T1')
    expect(formApi.myOpinion).not.toHaveBeenCalled()
    const labels = wrapper.findAll('.reviewer-label').map((n) => n.text())
    expect(labels).toEqual(['审稿人 1（张三）', '审稿人 2'])
    expect(wrapper.text()).not.toContain('草稿')
  })

  it('作者视角：同样走 task_opinions（分流优先级 编辑部 > 作者 > 审稿人），匿名无姓名', async () => {
    useAuthStore().user = { roles: ['AUTHOR'], name: 'A1' }
    formApi.taskOpinions.mockResolvedValue({
      results: [opinion({ reviewer_name: undefined })],
    })

    const wrapper = await mountView()

    expect(formApi.taskOpinions).toHaveBeenCalledWith('T1')
    expect(formApi.myOpinion).not.toHaveBeenCalled()
    const labels = wrapper.findAll('.reviewer-label').map((n) => n.text())
    expect(labels).toEqual(['审稿人 1'])
  })

  it('审稿人视角无草稿（my_opinion 抛错）时渲染空态，不整页失败', async () => {
    useAuthStore().user = { roles: ['REVIEWER'], name: 'R1' }
    formApi.myOpinion.mockRejectedValue(new Error('404'))
    // 组件预期行为是捕获后 console.error，静音以免污染测试输出
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const wrapper = await mountView()

    consoleSpy.mockRestore()
    // 任务信息仍渲染，意见区为空态
    expect(wrapper.text()).toContain(TASK.title)
    expect(wrapper.text()).toContain('暂无审稿意见')
  })
})
