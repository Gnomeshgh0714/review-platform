// 代表性组件测试：ReviewForm 的 AI 审稿异步化（决策 #026，F-3）——
// 提交秒回 job_id 后 3s 轮询，SUCCEEDED 填充表单 / FAILED 展示错误 /
// 提交本身失败展示错误。api 模块与路由按依赖 mock，Pinia 走真实实现，
// Element Plus 用真实插件挂载，定时器用 vitest fake timers 推进轮询。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'

vi.mock('@/api/modules', () => ({
  userApi: {},
  taskApi: { retrieve: vi.fn() },
  formApi: {
    getForm: vi.fn(),
    myOpinion: vi.fn(),
    saveDraft: vi.fn(),
    submitOpinion: vi.fn(),
    aiReview: vi.fn(),
    aiReviewStatus: vi.fn(),
  },
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { taskId: 'T1' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

import ReviewForm from '@/views/review/ReviewForm.vue'
import { formApi, taskApi } from '@/api/modules'

const TASK = { task_id: 'T1', title: '气候风险论文', subject_area: '经济学', deadline: '2026-11-01' }
const DIMENSIONS = [
  { dimensionId: 'D1', dimensionName: '研究意义', minWords: 5, description: '' },
]
const AI_RESULT = {
  dimension_scores: [{ dimensionId: 'D1', score: 4, comment: '研究意义评语' }],
  recommendation: 'MINOR_REVISION',
  overall_comment: '综合评语：整体质量较高。',
  suggestions: ['补充稳健性检验', '明确数据来源'],
}

async function mountView() {
  const wrapper = mount(ReviewForm, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

function findAIButton(wrapper) {
  return wrapper.findAll('button').find((b) => b.text().includes('AI 生成审稿意见'))
}

async function clickAI(wrapper) {
  const btn = findAIButton(wrapper)
  await btn.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.useFakeTimers()
  taskApi.retrieve.mockResolvedValue({ ...TASK })
  formApi.getForm.mockResolvedValue({ dimensions: DIMENSIONS })
  formApi.myOpinion.mockRejectedValue(new Error('404 无草稿'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ReviewForm AI 审稿异步轮询（决策 #026）', () => {
  it('提交秒回 job_id，轮询到 SUCCEEDED 后填充表单', async () => {
    formApi.aiReview.mockResolvedValue({ job_id: 'AIR-20261028-0001', status: 'PENDING' })
    // 第一次轮询 RUNNING（继续等待），第二次 SUCCEEDED 带结果
    formApi.aiReviewStatus
      .mockResolvedValueOnce({ job_id: 'AIR-20261028-0001', status: 'RUNNING' })
      .mockResolvedValueOnce({ job_id: 'AIR-20261028-0001', status: 'SUCCEEDED', result: AI_RESULT })

    const wrapper = await mountView()
    await clickAI(wrapper)

    // 提交口径：不再带 180s 超时的同步等待，直接拿 job_id 发起轮询
    expect(formApi.aiReview).toHaveBeenCalledWith('T1')
    // 等待期间展示等待文案
    expect(wrapper.text()).toContain('AI 审稿进行中（约 1-2 分钟）')

    // 第 3s：RUNNING，继续轮询
    await vi.advanceTimersByTimeAsync(3000)
    expect(formApi.aiReviewStatus).toHaveBeenCalledWith('AIR-20261028-0001')
    expect(wrapper.text()).toContain('AI 审稿进行中（约 1-2 分钟）')

    // 第 6s：SUCCEEDED，填充并停止轮询
    await vi.advanceTimersByTimeAsync(3000)
    expect(formApi.aiReviewStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('AI 审稿意见已生成，请检查并修改后提交')
    expect(wrapper.text()).not.toContain('AI 审稿进行中')

    // 填充断言：维度评语 / 综合评语 / 修改建议落入对应 textarea
    const textareas = wrapper.findAll('textarea')
    expect(textareas.at(0).element.value).toBe('研究意义评语')
    expect(textareas.at(1).element.value).toBe('综合评语：整体质量较高。')
    expect(textareas.at(2).element.value).toBe('补充稳健性检验\n明确数据来源')
    // 按钮切「已生成」
    expect(wrapper.findAll('button').some((b) => b.text().includes('已生成'))).toBe(true)

    // 轮询已停止：再推进 9s 不发起新请求
    await vi.advanceTimersByTimeAsync(9000)
    expect(formApi.aiReviewStatus).toHaveBeenCalledTimes(2)
  })

  it('轮询到 FAILED 展示后端 error，不填充表单', async () => {
    formApi.aiReview.mockResolvedValue({ job_id: 'AIR-20261028-0002', status: 'PENDING' })
    formApi.aiReviewStatus.mockResolvedValue({
      job_id: 'AIR-20261028-0002',
      status: 'FAILED',
      error: '未配置 REVIEWER_LLM_API_KEY 环境变量，AI 审稿功能不可用',
    })

    const wrapper = await mountView()
    await clickAI(wrapper)

    await vi.advanceTimersByTimeAsync(3000)

    // 错误透传展示，等待文案消失，成功态不出现
    expect(wrapper.text()).toContain('未配置 REVIEWER_LLM_API_KEY')
    expect(wrapper.text()).not.toContain('AI 审稿进行中')
    expect(wrapper.text()).not.toContain('AI 审稿意见已生成')
    // 表单未被填充
    expect(wrapper.findAll('textarea').at(0).element.value).toBe('')

    // 轮询已停止
    await vi.advanceTimersByTimeAsync(9000)
    expect(formApi.aiReviewStatus).toHaveBeenCalledTimes(1)
  })

  it('提交本身失败（如权限被拒）展示错误并复位状态', async () => {
    const err = new Error('403')
    err.response = { data: { error: '仅审稿人可使用 AI 审稿功能' } }
    formApi.aiReview.mockRejectedValue(err)

    const wrapper = await mountView()
    await clickAI(wrapper)

    expect(wrapper.text()).toContain('仅审稿人可使用 AI 审稿功能')
    expect(wrapper.text()).not.toContain('AI 审稿进行中')
    // 未提交成功则不发起任何轮询
    expect(formApi.aiReviewStatus).not.toHaveBeenCalled()
  })
})
