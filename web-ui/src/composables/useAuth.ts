import { ref, computed } from 'vue'
import router from '@/router'
import { wsService } from '@/services/websocket'

export interface MembershipUser {
  id: number
  username: string
  role: string
  status: string
  expired_at: string | null
  membership_active: boolean
  remaining_days: number | null
}

const TOKEN_KEY = 'auth_token'
const USER_KEY = 'auth_user'

function readStoredUser(): MembershipUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as MembershipUser) : null
  } catch {
    return null
  }
}

// Global State
const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
const user = ref<MembershipUser | null>(readStoredUser())

export function useAuth() {
  const isAuthenticated = computed(() => !!token.value)
  const membershipActive = computed(() => {
    if (!user.value) return false
    return user.value.membership_active || user.value.role === 'admin'
  })
  const isAdmin = computed(() => user.value?.role === 'admin')
  const username = computed(() => user.value?.username ?? null)

  function applySession(newToken: string, newUser: MembershipUser) {
    token.value = newToken
    user.value = newUser
    localStorage.setItem(TOKEN_KEY, newToken)
    localStorage.setItem(USER_KEY, JSON.stringify(newUser))
    // websocket.ts 与旧界面引用的兼容键
    localStorage.setItem('auth_logged_in', 'true')
    localStorage.setItem('auth_username', newUser.username)
    wsService.start()
  }

  function setMembershipUser(newUser: MembershipUser) {
    user.value = newUser
    localStorage.setItem(USER_KEY, JSON.stringify(newUser))
  }

  function clearSession() {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem('auth_logged_in')
    localStorage.removeItem('auth_username')
    wsService.stop()
    if (router.currentRoute.value.name !== 'Login') {
      router.push('/login')
    }
  }

  function logout() {
    clearSession()
  }

  async function fetchMe(): Promise<MembershipUser | null> {
    if (!token.value) return null
    try {
      const response = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token.value}` },
      })
      if (response.status === 401) {
        clearSession()
        return null
      }
      if (!response.ok) return user.value
      const me = (await response.json()) as MembershipUser
      setMembershipUser(me)
      return me
    } catch {
      return user.value
    }
  }

  async function login(username: string, password: string): Promise<{ ok: boolean; error?: string }> {
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        return { ok: false, error: body.detail || '登录失败' }
      }
      applySession(body.token, body.user)
      return { ok: true }
    } catch {
      return { ok: false, error: '登录过程中发生错误' }
    }
  }

  async function register(username: string, password: string): Promise<{ ok: boolean; error?: string }> {
    try {
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        return { ok: false, error: body.detail || '注册失败' }
      }
      applySession(body.token, body.user)
      return { ok: true }
    } catch {
      return { ok: false, error: '注册过程中发生错误' }
    }
  }

  return {
    token,
    user,
    username,
    isAuthenticated,
    membershipActive,
    isAdmin,
    login,
    register,
    logout,
    fetchMe,
    setMembershipUser,
  }
}
