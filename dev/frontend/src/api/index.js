import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动附加 JWT
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// #016 安全项3：401 → 用 refresh_token 静默换新 token 并重放原请求
// 后端已开 ROTATE_REFRESH_TOKENS：刷新响应会同时下发新 refresh，必须一并
// 更新 localStorage（旧 refresh 已被拉黑，若只更新 access，第二次刷新必失败）；
// 刷新不可用/失败时回落到原有 401 登出流程。
// 登录接口与刷新接口自身的 401 不触发重放（凭据错误/refresh 失效属正常业务结果）
let refreshing = null // 在途刷新 Promise：并发 401 只触发一次刷新请求

async function tryRefreshAndRetry(config) {
  const refreshToken = localStorage.getItem('refresh_token')
  const excluded = ['/users/login/', '/users/token/refresh/']
  if (!refreshToken || config?._retried || excluded.some((u) => (config?.url || '').includes(u))) {
    return null
  }
  if (!refreshing) {
    refreshing = axios
      .post('/api/users/token/refresh/', { refresh: refreshToken })
      .then(({ data }) => {
        localStorage.setItem('access_token', data.access)
        // 轮换开启：响应携带新 refresh，同步更新存储，否则旧值下次刷新即 401
        if (data.refresh) localStorage.setItem('refresh_token', data.refresh)
        useAuthStore().token = data.access
        return data
      })
      .finally(() => { refreshing = null })
  }
  const data = await refreshing.catch(() => null)
  if (!data) return null
  config._retried = true
  config.headers = config.headers || {}
  config.headers.Authorization = `Bearer ${data.access}`
  return api(config)
}

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const { response, config } = error
    // #016 安全项3：先尝试静默刷新重放（成功则业务层无感）；
    // 不可刷新（无 token/已重试过/刷新失败）时走原有 401 登出流程
    if (response?.status === 401) {
      const retried = await tryRefreshAndRetry(config)
      if (retried) return retried
    }
    // #015 遗留2：部分接口的 404 属正常业务空态（如 my_opinion 无草稿），
    // 调用处可在请求 config 传 silent404: true 跳过全局「请求的资源不存在」toast；
    // 其余状态码与其他页面的 404 提示均不受影响
    if (config?.silent404 && response?.status === 404) {
      return Promise.reject(error)
    }
    if (response) {
      switch (response.status) {
        case 401:
          ElMessage.error('登录已过期，请重新登录')
          // 评审意见 V1.2 严重#11：只清 localStorage 不清 Pinia store 时，
          // 路由守卫按 store 里的旧 token 判定「已登录」把登录页弹回
          // Dashboard，会话过期陷入跳转死结——store 与 localStorage 一并重置
          useAuthStore().logout()
          router.push('/login')
          break
        case 403:
          ElMessage.error('没有权限执行此操作')
          break
        case 404:
          ElMessage.error('请求的资源不存在')
          break
        case 400:
          ElMessage.error(response.data?.detail || response.data?.error || '请求参数错误')
          break
        case 500:
          ElMessage.error('服务器内部错误，请稍后重试')
          break
        default:
          ElMessage.error(response.data?.detail || response.data?.error || `请求失败 (${response.status})`)
      }
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请检查网络连接')
    } else {
      ElMessage.error('网络异常，请检查后端服务是否启动')
    }
    return Promise.reject(error)
  }
)

export default api
