<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import LocaleToggle from '@/components/layout/LocaleToggle.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from 'vue-i18n'

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const mode = ref<'login' | 'register'>('login')
const isLoading = ref(false)
const error = ref('')

const { login, register, membershipActive } = useAuth()
const router = useRouter()
const route = useRoute()
const { t } = useI18n()

function switchMode(next: 'login' | 'register') {
  mode.value = next
  error.value = ''
}

async function handleSubmit() {
  if (!username.value || !password.value) {
    error.value = t('login.errors.missingCredentials')
    return
  }
  if (mode.value === 'register' && password.value !== confirmPassword.value) {
    error.value = t('login.errors.passwordMismatch')
    return
  }

  isLoading.value = true
  error.value = ''

  try {
    const result =
      mode.value === 'login'
        ? await login(username.value, password.value)
        : await register(username.value, password.value)

    if (result.ok) {
      // 新注册用户未激活会员，直接进入激活页
      const target =
        mode.value === 'register' && !membershipActive.value
          ? { name: 'Activate' }
          : (route.query.redirect as string) || '/'
      router.push(target)
    } else {
      error.value = result.error || t('login.errors.invalidCredentials')
    }
  } catch {
    error.value = t('login.errors.unexpected')
  } finally {
    isLoading.value = false
  }
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
        <CardTitle class="text-2xl text-center">
          {{ mode === 'login' ? t('login.title') : t('login.registerTitle') }}
        </CardTitle>
        <CardDescription class="text-center">
          {{ mode === 'login' ? t('login.description') : t('login.registerDescription') }}
        </CardDescription>
      </CardHeader>
      <form @submit.prevent="handleSubmit">
        <CardContent class="grid gap-4">
          <div class="grid gap-2">
            <Label for="username">{{ t('login.username') }}</Label>
            <Input id="username" type="text" v-model="username" autocomplete="username" required />
          </div>
          <div class="grid gap-2">
            <Label for="password">{{ t('login.password') }}</Label>
            <Input id="password" type="password" v-model="password" autocomplete="current-password" required />
          </div>
          <div v-if="mode === 'register'" class="grid gap-2">
            <Label for="confirm-password">{{ t('login.confirmPassword') }}</Label>
            <Input id="confirm-password" type="password" v-model="confirmPassword" autocomplete="new-password" required />
          </div>
          <div v-if="error" class="text-sm font-medium text-red-500" role="alert">
            {{ error }}
          </div>
        </CardContent>
        <CardFooter class="flex flex-col gap-3">
          <Button class="w-full" type="submit" :disabled="isLoading">
            {{
              isLoading
                ? t('login.submitting')
                : mode === 'login'
                  ? t('login.submit')
                  : t('login.registerSubmit')
            }}
          </Button>
          <button
            type="button"
            class="text-xs font-semibold text-primary hover:underline focus:outline-none"
            @click="switchMode(mode === 'login' ? 'register' : 'login')"
          >
            {{
              mode === 'login' ? t('login.switchToRegister') : t('login.switchToLogin')
            }}
          </button>
        </CardFooter>
      </form>
    </Card>
  </div>
</template>
