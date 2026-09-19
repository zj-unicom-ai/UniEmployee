// 认证状态管理（Pinia）：登录/登出、token 持久化、管理员判断
import { defineStore } from 'pinia'
import api from '../api.js'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: JSON.parse(localStorage.getItem('user') || 'null'),
  }),
  getters: {
    isLoggedIn: (state) => !!state.user,
    isAdmin: (state) => state.user?.role === 'admin',
    username: (state) => state.user?.username || '',
  },
  actions: {
    async login(username, password) {
      const { data } = await api.post('/auth/login', { username, password })
      this.token = data.token
      this.user = data.user
      localStorage.setItem('token', data.token)
      localStorage.setItem('user', JSON.stringify(data.user))
      return data
    },
    async completeSso() {
      const { data } = await api.get('/auth/me')
      this.token = ''
      this.user = data
      localStorage.removeItem('token')
      localStorage.setItem('user', JSON.stringify(data))
      return data
    },
    async logout() {
      try { await api.post('/auth/logout') } catch (_) { /* 本地 token 仍应可退出 */ }
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
      localStorage.removeItem('user')
    },
  },
})
