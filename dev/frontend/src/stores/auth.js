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
