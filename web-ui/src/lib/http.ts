import { useAuth } from '@/composables/useAuth'
import router from '@/router'

interface FetchOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

export async function http(url: string, options: FetchOptions = {}) {
  const { token, logout } = useAuth()

  const headers = new Headers(options.headers)
  if (token.value) {
    headers.set('Authorization', `Bearer ${token.value}`)
  }

  // Handle Query Params
  let fullUrl = url
  if (options.params) {
    const searchParams = new URLSearchParams()
    Object.entries(options.params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.append(key, String(value))
      }
    })
    const queryString = searchParams.toString()
    if (queryString) {
      fullUrl += (url.includes('?') ? '&' : '?') + queryString
    }
  }

  const config: RequestInit = {
    ...options,
    headers,
  }

  const response = await fetch(fullUrl, config)

  if (response.status === 401) {
    // Token 缺失/过期/账号被禁用
    logout()
    throw new Error('登录状态已失效，请重新登录')
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    const detail = errorData.detail
    if (response.status === 403 && detail && typeof detail === 'object') {
      if (detail.code === 'MEMBERSHIP_EXPIRED') {
        router.push('/activate')
        throw new Error(detail.message || '会员已过期')
      }
      throw new Error(detail.message || '没有访问权限')
    }
    const message =
      typeof detail === 'string' ? detail : `HTTP error! status: ${response.status}`
    throw new Error(message)
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return null
  }

  return response.json()
}
