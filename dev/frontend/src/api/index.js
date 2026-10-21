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

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const { response, config } = error
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
