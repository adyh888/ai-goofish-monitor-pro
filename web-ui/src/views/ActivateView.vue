<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { http } from '@/lib/http'
import LocaleToggle from '@/components/layout/LocaleToggle.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Badge from '@/components/ui/badge/Badge.vue'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from 'vue-i18n'

const cardCode = ref('')
const isLoading = ref(false)
const message = ref('')
const messageTone = ref<'success' | 'error'>('success')

const { user, membershipActive, setMembershipUser, logout } = useAuth()
const router = useRouter()
const { t } = useI18n()

onMounted(() => {
  // 刷新一次会员状态，避免本地缓存过期
  useAuth().fetchMe()
})

const expiryText = computed(() => {
  if (!user.value?.expired_at) return t('activate.neverActivated')
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(user.value.expired_at),
  )
})

const remainingText = computed(() => {
  if (!user.value) return ''
  if (user.value.role === 'admin') return t('activate.unlimited')
  const days = user.value.remaining_days ?? 0
  return t('activate.remainingDays', { days })
})

async function handleActivate() {
  const code = cardCode.value.trim()
  if (!code) {
    message.value = t('activate.errors.missingCode')
    messageTone.value = 'error'
    return
  }

  isLoading.value = true
  message.value = ''
  try {
    const result = await http('/api/auth/activate-card', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
    setMembershipUser(result.user)
    message.value = result.message || t('activate.success')
    messageTone.value = 'success'
    cardCode.value = ''
  } catch (e) {
    message.value = e instanceof Error ? e.message : t('activate.errors.failed')
    messageTone.value = 'error'
  } finally {
    isLoading.value = false
  }
}

function goApp() {
  router.push(membershipActive.value ? '/dashboard' : '/activate')
}

function handleLogout() {
  logout()
}
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-100 px-4">
    <div aria-hidden="true" class="absolute inset-0">
      <div class="absolute left-[-10%] top-[-10%] h-72 w-72 rounded-full bg-primary/10 blur-3xl"></div>
      <div class="absolute bottom-[-10%] right-[-5%] h-72 w-72 rounded-full bg-blue-300/10 blur-3xl"></div>
    </div>
    <div class="absolute right-6 top-6">
      <LocaleToggle />
    </div>
    <Card class="app-surface relative z-10 w-full max-w-md border-none">
      <CardHeader>
        <CardTitle class="text-2xl text-center">{{ t('activate.title') }}</CardTitle>
        <CardDescription class="text-center">{{ t('activate.description') }}</CardDescription>
      </CardHeader>
      <CardContent class="grid gap-4">
        <div class="rounded-xl border border-slate-200/70 bg-slate-50/60 p-4 space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-500">{{ t('activate.account') }}</span>
            <span class="font-bold text-slate-800">{{ user?.username }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-500">{{ t('activate.status') }}</span>
            <Badge :class="membershipActive ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : 'bg-red-100 text-red-600 border-red-200'" variant="outline">
              {{ membershipActive ? t('activate.activeBadge') : t('activate.expiredBadge') }}
            </Badge>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-500">{{ t('activate.expiry') }}</span>
            <span class="font-semibold text-slate-700">{{ expiryText }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-500">{{ t('activate.remaining') }}</span>
            <span class="font-semibold text-slate-700">{{ remainingText }}</span>
          </div>
        </div>

        <div class="grid gap-2">
          <Label for="card-code">{{ t('activate.cardCode') }}</Label>
          <Input
            id="card-code"
            type="text"
            v-model="cardCode"
            placeholder="XYG-XXXX-XXXX-XXXX"
            class="font-mono uppercase"
            @keydown.enter="handleActivate"
          />
          <p class="text-xs text-slate-400">{{ t('activate.cardHint') }}</p>
        </div>

        <div v-if="message" class="text-sm font-medium" :class="messageTone === 'success' ? 'text-emerald-600' : 'text-red-500'" role="alert">
          {{ message }}
        </div>
      </CardContent>
      <CardFooter class="flex flex-col gap-2">
        <Button class="w-full" type="button" :disabled="isLoading" @click="handleActivate">
          {{ isLoading ? t('activate.activating') : t('activate.submit') }}
        </Button>
        <div class="flex w-full gap-2">
          <Button variant="outline" class="w-full" :disabled="!membershipActive" @click="goApp">
            {{ t('activate.backToApp') }}
          </Button>
          <Button variant="ghost" class="w-full text-slate-500" @click="handleLogout">
            {{ t('activate.logout') }}
          </Button>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>
