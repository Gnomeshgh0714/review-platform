import { defineStore } from 'pinia'
import { userApi } from '@/api/modules'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('access_token') || '',
    user: JSON.parse(localStorage.getItem('user_info') || 'null'),
  }),

  getters: {
    isLoggedIn: (state) => !!state.token,
    isEditor: (state) => (state.user?.roles || []).includes('EDITOR') || state.user?.role === 'EDITOR',
    isReviewer: (state) => (state.user?.roles || []).includes('REVIEWER') || state.user?.role === 'REVIEWER',
    isAuthor: (state) => (state.user?.roles || []).includes('AUTHOR') || state.user?.role === 'AUTHOR',
    displayName: (state) => state.user?.name || state.user?.email || '',
    roleLabel: (state) => {
      const roles = state.user?.roles || (state.user?.role ? [state.user.role] : [])
      const labels = { EDITOR: '编辑部', REVIEWER: '审稿人', AUTHOR: '作者' }
      return roles.map(r => labels[r]).filter(Boolean).join('/') || ''
    },
    primaryRole: (state) => {
      const roles = state.user?.roles || (state.user?.role ? [state.user.role] : [])
      return roles[0] || ''
    },
  },

  actions: {
    async login(email, password) {
      const res = await userApi.login({ email, password })
      this.token = res.access
      localStorage.setItem('access_token', res.access)
      if (res.refresh) {
        localStorage.setItem('refresh_token', res.refresh)
      }
      await this.fetchUser()
      return res
    },

    async fetchUser() {
      try {
        const res = await userApi.getMe()
        this.user = res
        localStorage.setItem('user_info', JSON.stringify(res))
        return res
      } catch (e) {
        console.error('Failed to fetch user:', e)
      }
    },

    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user_info')
    },
  },
})

// V1.2 一般#31：多标签页登出同步——storage 事件仅在「其他」标签页修改 localStorage 时触发，
// A 标签登出（access_token 被移除）后 B 标签同步清空登录态，避免 B 标签凭旧 token
// 持续 401 并陷入弹回循环（严重#11 修复依赖 store 与 localStorage 同步重置）；
// 本标签页自身的 logout 不触发该事件，无重复处理；B 标签登出时
// store.isLoggedIn 已为 false，重复触发亦为无操作
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === 'access_token' && !e.newValue) {
      const store = useAuthStore()
      if (store.isLoggedIn) store.logout()
    }
  })
}
