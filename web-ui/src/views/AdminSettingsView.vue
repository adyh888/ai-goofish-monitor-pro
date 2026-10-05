<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { adminApi } from '@/api/admin'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toast'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { RefreshCw } from 'lucide-vue-next'

const { t } = useI18n()
const isLoading = ref(false)
const isSaving = ref(false)

const form = reactive({
  REGISTRATION_ENABLED: true,
  AI_BASE_URL_WHITELIST: '',
  PLATFORM_PROXY_POOL_ENABLED: true,
  PER_USER_TASK_LIMIT: 10,
  PER_USER_CONCURRENT_RUNNING: 1,
  GLOBAL_SPIDER_CONCURRENCY: 5,
})

async function load() {
  isLoading.value = true
  try {
    const settings = await adminApi.getPlatformSettings()
    Object.assign(form, settings)
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.platform.loadFailed'), variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

async function save() {
  isSaving.value = true
  try {
    const result = await adminApi.savePlatformSettings({ ...form })
    toast({ description: result.message || t('admin.platform.saved') })
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.platform.saveFailed'), variant: 'destructive' })
  } finally {
    isSaving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6 max-w-3xl">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-black text-slate-900">{{ t('admin.platform.title') }}</h1>
        <p class="text-sm text-slate-500 mt-1">{{ t('admin.platform.description') }}</p>
      </div>
      <Button variant="outline" :disabled="isLoading" @click="load">
        <RefreshCw class="w-4 h-4 mr-1" />
        {{ t('common.refresh') }}
      </Button>
    </div>

    <Card>
      <CardHeader>
        <CardTitle class="text-base">{{ t('admin.platform.title') }}</CardTitle>
        <CardDescription>{{ t('admin.platform.hint') }}</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="flex items-center justify-between rounded-xl border border-slate-200/70 p-4">
          <div>
            <p class="text-sm font-bold text-slate-700">{{ t('admin.platform.registration') }}</p>
            <p class="text-xs text-slate-400 mt-0.5">{{ t('admin.platform.registrationHint') }}</p>
          </div>
          <Switch v-model="form.REGISTRATION_ENABLED" />
        </div>

        <div class="flex items-center justify-between rounded-xl border border-slate-200/70 p-4">
          <div>
            <p class="text-sm font-bold text-slate-700">{{ t('admin.platform.platformPool') }}</p>
            <p class="text-xs text-slate-400 mt-0.5">{{ t('admin.platform.platformPoolHint') }}</p>
          </div>
          <Switch v-model="form.PLATFORM_PROXY_POOL_ENABLED" />
        </div>

        <div class="grid gap-2">
          <Label for="whitelist">{{ t('admin.platform.whitelist') }}</Label>
          <Textarea
            id="whitelist"
            v-model="form.AI_BASE_URL_WHITELIST"
            :placeholder="'api.deepseek.com, api.openai.com, *.example.com'"
            class="font-mono text-xs min-h-20"
          />
          <p class="text-xs text-slate-400">{{ t('admin.platform.whitelistHint') }}</p>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div class="grid gap-2">
            <Label for="task-limit">{{ t('admin.platform.taskLimit') }}</Label>
            <Input id="task-limit" type="number" min="1" v-model.number="form.PER_USER_TASK_LIMIT" />
          </div>
          <div class="grid gap-2">
            <Label for="concurrent">{{ t('admin.platform.concurrent') }}</Label>
            <Input id="concurrent" type="number" min="1" v-model.number="form.PER_USER_CONCURRENT_RUNNING" />
          </div>
          <div class="grid gap-2">
            <Label for="global">{{ t('admin.platform.globalConcurrency') }}</Label>
            <Input id="global" type="number" min="1" v-model.number="form.GLOBAL_SPIDER_CONCURRENCY" />
          </div>
        </div>

        <div class="flex justify-end">
          <Button :disabled="isSaving" @click="save">
            {{ isSaving ? t('common.saving') : t('common.save') }}
          </Button>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
