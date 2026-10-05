import { ref, onMounted } from 'vue'
import * as settingsApi from '@/api/settings'
import type {
  NotificationSettings,
  NotificationSettingsUpdate,
  NotificationTestResponse,
  RotationSettings,
  SystemStatus
} from '@/api/settings'

export function useSettings() {
  const notificationSettings = ref<NotificationSettings>({})
  const rotationSettings = ref<RotationSettings>({})
  const systemStatus = ref<SystemStatus | null>(null)
  const isReady = ref(false)

  const isLoading = ref(false)
  const isSaving = ref(false)
  const error = ref<Error | null>(null)

  async function fetchAll() {
    isLoading.value = true
    error.value = null
    const [notif, rotation, status] = await Promise.allSettled([
      settingsApi.getNotificationSettings(),
      settingsApi.getRotationSettings(),
      settingsApi.getSystemStatus()
    ])
    if (notif.status === 'fulfilled') notificationSettings.value = notif.value
    if (rotation.status === 'fulfilled') rotationSettings.value = rotation.value
    if (status.status === 'fulfilled') systemStatus.value = status.value
    const failed = [notif, rotation, status].find(
      (r): r is PromiseRejectedResult => r.status === 'rejected'
    )
    if (failed) {
      error.value =
        failed.reason instanceof Error ? failed.reason : new Error(String(failed.reason))
    }
    isLoading.value = false
    isReady.value = true
  }

  async function refreshStatus() {
    isLoading.value = true
    error.value = null
    try {
      systemStatus.value = await settingsApi.getSystemStatus()
    } catch (e) {
      if (e instanceof Error) error.value = e
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function saveNotificationSettings(payload: NotificationSettingsUpdate) {
    isSaving.value = true
    try {
      await settingsApi.updateNotificationSettings(payload)
      const [notif, status] = await Promise.all([
        settingsApi.getNotificationSettings(),
        settingsApi.getSystemStatus()
      ])
      notificationSettings.value = notif
      systemStatus.value = status
    } catch (e) {
      if (e instanceof Error) error.value = e
      throw e
    } finally {
      isSaving.value = false
    }
  }

  async function testNotification(payload: {
    channel?: string
    settings: NotificationSettingsUpdate
  }): Promise<NotificationTestResponse> {
    isSaving.value = true
    try {
      return await settingsApi.testNotificationSettings(payload)
    } catch (e) {
      if (e instanceof Error) error.value = e
      throw e
    } finally {
      isSaving.value = false
    }
  }

  async function saveRotationSettings() {
    isSaving.value = true
    try {
      await settingsApi.updateRotationSettings(rotationSettings.value)
    } catch (e) {
      if (e instanceof Error) error.value = e
      throw e
    } finally {
      isSaving.value = false
    }
  }

  onMounted(fetchAll)

  return {
    notificationSettings,
    rotationSettings,
    systemStatus,
    isLoading,
    isSaving,
    isReady,
    error,
    fetchAll,
    saveNotificationSettings,
    testNotification,
    saveRotationSettings,
    refreshStatus,
  }
}
