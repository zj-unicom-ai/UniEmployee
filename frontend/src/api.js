// API 请求封装：Axios 实例，自动注入 Bearer token，401 自动跳登录
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// 请求拦截：注入 token
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：401 自动跳登录
api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      const next = encodeURIComponent(location.pathname + location.search)
      if (!location.pathname.startsWith('/login')) {
        location.href = `/login?next=${next}`
      }
    }
    return Promise.reject(err)
  }
)

export default api
