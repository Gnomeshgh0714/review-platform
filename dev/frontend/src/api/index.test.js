// api 层拦截器单测：不起真后端，用自定义 axios adapter 控制每个 url 的响应序列，
// 用 vi.spyOn(axios, 'post') 充当刷新接口。覆盖两段此前仅有手工验证的逻辑：
//   #016 安全项3：401 单飞静默刷新重放；#015 遗留2：silent404 跳过全局 404 toast
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError } from 'axios'
import { createPinia, setActivePinia } from 'pinia'

// 拦截器依赖的三方模块全部 mock：不弹真 toast、不加载完整路由树（避免牵入全部 views）。
// stores/auth 不 mock：走真实 Pinia，可同时验证「store 与 localStorage 一并重置」。
const { elMessageError, routerPush } = vi.hoisted(() => ({
  elMessageError: vi.fn(),
  routerPush: vi.fn(),
}))
vi.mock('element-plus', () => ({
  ElMessage: { error: elMessageError },
}))
vi.mock('@/router', () => ({
  default: { push: routerPush },
}))

import api from '@/api'
import { useAuthStore } from '@/stores/auth'

// 每个 url 的响应脚本：数组按请求次序出队，如 [401, 200] 表示首次 401、重放后 200；
// 单元素数组表示该 url 恒定返回同一响应。adapter 须自行构造 AxiosError（axios 不代劳）。
let routeScripts = new Map()
let requests = []
let refreshSpy

function installAdapter() {
  api.defaults.adapter = (config) => {
    requests.push(config)
    const queue = routeScripts.get(config.url) || [{ status: 200, data: {} }]
    const r = queue.length > 1 ? queue.shift() : queue[0]
    const response = { status: r.status, data: r.data, headers: {}, config }
    if (r.status >= 400) {
      return Promise.reject(new AxiosError(
        `Request failed with status code ${r.status}`,
        AxiosError.ERR_BAD_REQUEST,
        config,
        null,
        response,
      ))
    }
    return Promise.resolve(response)
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  localStorage.setItem('access_token', 'old-access')
  localStorage.setItem('refresh_token', 'old-refresh')
  elMessageError.mockClear()
  routerPush.mockClear()
  routeScripts = new Map()
  requests = []
  // 刷新接口默认成功下发新 token，个别用例按需覆盖返回值
  refreshSpy = vi
    .spyOn(axios, 'post')
    .mockResolvedValue({ data: { access: 'new-access', refresh: 'new-refresh' } })
  installAdapter()
})

afterEach(() => {
  refreshSpy.mockRestore()
  api.defaults.adapter = undefined
})

describe('#016 安全项3：401 单飞静默刷新重放', () => {
  it('401 → 调一次刷新接口 → 用新 access 重放原请求，业务层无感', async () => {
    routeScripts.set('/tasks/1/', [
      { status: 401, data: { detail: 'token 已过期' } },
      { status: 200, data: { task_id: 1, title: 'ok' } },
    ])

    const res = await api.get('/tasks/1/')

    expect(res).toEqual({ task_id: 1, title: 'ok' })
    expect(refreshSpy).toHaveBeenCalledTimes(1)
    expect(refreshSpy).toHaveBeenCalledWith('/api/users/token/refresh/', { refresh: 'old-refresh' })
    // 新 access 与新 refresh（轮换下发）都写入 localStorage
    expect(localStorage.getItem('access_token')).toBe('new-access')
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh')
    // store 同步更新，路由守卫不会再拿旧 token 误判已登录
    expect(useAuthStore().token).toBe('new-access')
    // 重放请求带新 Authorization（requests[1] 为重放）
    expect(requests).toHaveLength(2)
    expect(String(requests[1].headers.Authorization)).toBe('Bearer new-access')
    // 静默成功：不弹 toast、不跳登录页
    expect(elMessageError).not.toHaveBeenCalled()
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('并发多个 401 请求单飞：刷新接口只打一次，全部重放成功', async () => {
    const urls = ['/tasks/a/', '/tasks/b/', '/tasks/c/']
    urls.forEach((u) => routeScripts.set(u, [{ status: 401, data: {} }, { status: 200, data: { ok: u } }]))

    const results = await Promise.all(urls.map((u) => api.get(u)))

    expect(refreshSpy).toHaveBeenCalledTimes(1)
    expect(results).toEqual(urls.map((u) => ({ ok: u })))
    // 3 个原始请求 + 3 个重放请求，全部带新 token
    expect(requests).toHaveLength(6)
    requests.forEach((c) => expect(String(c.headers.Authorization)).toBe('Bearer new-access'))
  })

  it('刷新响应不带新 refresh 字段时保留旧 refresh（防御旧后端未开轮换）', async () => {
    routeScripts.set('/tasks/1/', [{ status: 401, data: {} }, { status: 200, data: { ok: 1 } }])
    refreshSpy.mockResolvedValue({ data: { access: 'new-access-2' } })

    await api.get('/tasks/1/')

    expect(localStorage.getItem('access_token')).toBe('new-access-2')
    expect(localStorage.getItem('refresh_token')).toBe('old-refresh')
  })

  it('刷新失败回落登出：toast + 跳登录页 + store 与 localStorage 一并重置', async () => {
    routeScripts.set('/tasks/1/', [{ status: 401, data: {} }])
    refreshSpy.mockRejectedValue(new Error('refresh token expired'))

    await expect(api.get('/tasks/1/')).rejects.toMatchObject({ response: { status: 401 } })

    expect(refreshSpy).toHaveBeenCalledTimes(1)
    expect(elMessageError).toHaveBeenCalledWith('登录已过期，请重新登录')
    expect(routerPush).toHaveBeenCalledWith('/login')
    const store = useAuthStore()
    expect(store.token).toBe('')
    expect(store.user).toBeNull()
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })

  it('登录接口自身的 401 不触发刷新（凭据错误属正常业务结果）', async () => {
    routeScripts.set('/users/login/', [{ status: 401, data: { detail: '账号或密码错误' } }])

    await expect(api.post('/users/login/', {})).rejects.toMatchObject({ response: { status: 401 } })

    expect(refreshSpy).not.toHaveBeenCalled()
    expect(elMessageError).toHaveBeenCalledWith('登录已过期，请重新登录')
  })

  it('刷新接口自身的 401 不再触发刷新（避免递归）', async () => {
    routeScripts.set('/users/token/refresh/', [{ status: 401, data: { detail: 'refresh 失效' } }])

    await expect(api.post('/users/token/refresh/', {})).rejects.toMatchObject({ response: { status: 401 } })

    expect(refreshSpy).not.toHaveBeenCalled()
  })

  it('本地无 refresh_token 时 401 直接走登出，不调刷新接口', async () => {
    localStorage.removeItem('refresh_token')
    routeScripts.set('/tasks/1/', [{ status: 401, data: {} }])

    await expect(api.get('/tasks/1/')).rejects.toMatchObject({ response: { status: 401 } })

    expect(refreshSpy).not.toHaveBeenCalled()
    expect(elMessageError).toHaveBeenCalledWith('登录已过期，请重新登录')
    expect(routerPush).toHaveBeenCalledWith('/login')
  })

  it('已重放过的请求再次 401 不再二次刷新，回落登出', async () => {
    routeScripts.set('/tasks/1/', [{ status: 401, data: {} }, { status: 401, data: {} }])

    await expect(api.get('/tasks/1/')).rejects.toMatchObject({ response: { status: 401 } })

    expect(refreshSpy).toHaveBeenCalledTimes(1)
    expect(elMessageError).toHaveBeenCalledWith('登录已过期，请重新登录')
    expect(routerPush).toHaveBeenCalledWith('/login')
  })
})

describe('#015 遗留2：silent404 请求标记', () => {
  it('带 silent404: true 的 404 静默拒绝，不弹全局 toast（my_opinion 空态场景）', async () => {
    routeScripts.set('/opinions/my_opinion/', [{ status: 404, data: { detail: '未找到' } }])

    await expect(
      api.get('/opinions/my_opinion/', { params: { task_id: 1 }, silent404: true }),
    ).rejects.toMatchObject({ response: { status: 404 } })

    expect(elMessageError).not.toHaveBeenCalled()
  })

  it('不带标记的 404 照常弹「请求的资源不存在」toast', async () => {
    routeScripts.set('/opinions/task_opinions/', [{ status: 404, data: {} }])

    await expect(api.get('/opinions/task_opinions/')).rejects.toMatchObject({ response: { status: 404 } })

    expect(elMessageError).toHaveBeenCalledWith('请求的资源不存在')
  })
})
