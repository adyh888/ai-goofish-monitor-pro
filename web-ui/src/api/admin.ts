import { http } from '@/lib/http'

export interface CardKeyItem {
  id: number
  code: string
  duration_days: number
  status: 'unused' | 'used' | 'disabled'
  batch_no: string
  note: string
  used_by: number | null
  used_at: string | null
  created_at: string
}

export interface AdminUserItem {
  id: number
  username: string
  role: 'user' | 'admin'
  status: 'active' | 'disabled'
  expired_at: string | null
  membership_active: boolean
  remaining_days: number | null
}

export interface CardsSummary {
  unused: number
  used: number
  disabled: number
}

export const adminApi = {
  async generateCards(payload: {
    count: number
    duration_days: number
    batch_no?: string
    note?: string
  }): Promise<{ batch_no: string; duration_days: number; codes: string[] }> {
    return await http('/api/admin/cards/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },

  async listCards(params?: {
    status?: string
    batch_no?: string
    limit?: number
  }): Promise<{ items: CardKeyItem[]; total: number }> {
    return await http('/api/admin/cards', { params })
  },

  async cardsSummary(): Promise<CardsSummary> {
    return await http('/api/admin/cards/summary')
  },

  async setCardStatus(id: number, status: 'unused' | 'disabled'): Promise<CardKeyItem> {
    return await http(`/api/admin/cards/${id}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
  },

  async exportCards(): Promise<string> {
    const response = await fetch('/api/admin/cards/export', {
      headers: { Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}` },
    })
    if (!response.ok) {
      throw new Error('导出失败')
    }
    return await response.text()
  },

  async listUsers(): Promise<{ items: AdminUserItem[] }> {
    return await http('/api/admin/users')
  },

  async createUser(payload: {
    username: string
    password: string
    role?: string
  }): Promise<AdminUserItem> {
    return await http('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },

  async setUserExpiry(id: number, expiredAt: string | null): Promise<AdminUserItem> {
    return await http(`/api/admin/users/${id}/expiry`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expired_at: expiredAt }),
    })
  },

  async setUserStatus(id: number, status: 'active' | 'disabled'): Promise<AdminUserItem> {
    return await http(`/api/admin/users/${id}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
  },

  async resetUserPassword(id: number, newPassword: string): Promise<{ message: string }> {
    return await http(`/api/admin/users/${id}/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: newPassword }),
    })
  },

  async getPlatformSettings(): Promise<Record<string, boolean | string | number>> {
    const result = (await http('/api/admin/platform')) as {
      settings: Record<string, boolean | string | number>
    }
    return result.settings
  },

  async savePlatformSettings(
    patch: Record<string, boolean | string | number>,
  ): Promise<{ message: string }> {
    return await http('/api/admin/platform', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  },

  async overview(): Promise<{
    total_users: number
    active_members: number
    cards_unused: number
    cards_used: number
  }> {
    return await http('/api/admin/overview')
  },
}
