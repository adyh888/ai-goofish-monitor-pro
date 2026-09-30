<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowDown,
  ArrowUp,
  CircleCheck,
  Download,
  Pencil,
  Play,
  Plus,
  Trash2,
} from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from '@/components/ui/toast'
import {
  activateAiProfile,
  createAiProfile,
  deleteAiProfile,
  fetchAiModels,
  getAiProfiles,
  moveAiProfile,
  testAiProfile,
  toggleAiProfile,
  updateAiProfile,
  type AiProfile,
  type AiProfilePayload,
} from '@/api/settings'

const { t } = useI18n()

const profiles = ref<AiProfile[]>([])
const isLoading = ref(false)
const busyProfileId = ref<number | null>(null)

const dialogOpen = ref(false)
const editingId = ref<number | null>(null)
const isSaving = ref(false)
const isTestingProfile = ref(false)
const isFetchingModels = ref(false)
const fetchedModels = ref<string[]>([])

const MODEL_SUGGESTIONS: Array<{ match: RegExp; models: string[] }> = [
  { match: /deepseek/i, models: ['deepseek-chat', 'deepseek-reasoner'] },
  { match: /openai\.com/i, models: ['gpt-4o', 'gpt-4o-mini'] },
  { match: /moonshot/i, models: ['moonshot-v1-8k-vision-preview', 'moonshot-v1-32k-vision-preview'] },
  { match: /dashscope|aliyun/i, models: ['qwen-vl-plus', 'qwen2.5-vl-72b-instruct'] },
  { match: /bigmodel\.cn|zhipu/i, models: ['glm-4v-flash', 'glm-4v-plus'] },
]

const form = reactive({
  name: '',
  base_url: '',
  api_key: '',
  model_name: '',
  proxy_url: '',
})

// 服务商真实列表与静态候选合并去重（如 deepseek-chat 可用但不在 /models 返回里）
const modelSuggestions = computed(() => {
  const base = form.base_url || ''
  const hit = MODEL_SUGGESTIONS.find((p) => p.match.test(base))
  return [...new Set([...fetchedModels.value, ...(hit ? hit.models : [])])]
})

// 推理/思考模型会输出思考过程，token 用量高且易解析失败（如 deepseek-reasoner/flash、QwQ、o 系列等）
const REASONING_MODEL_RE = /deepseek-(reasoner|flash|r1)|qwq|thinking|^o[134]([-_.]|$)/i
const isLikelyReasoningModel = computed(() => REASONING_MODEL_RE.test((form.model_name || '').trim()))

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function notifyError(title: string, description?: string) {
  toast({ title, description, variant: 'destructive' })
}

async function loadProfiles() {
  isLoading.value = true
  try {
    profiles.value = await getAiProfiles()
  } catch (e) {
    notifyError(t('settings.aiProfiles.loadFailed'), (e as Error).message)
  } finally {
    isLoading.value = false
  }
}

function openCreateDialog() {
  editingId.value = null
  Object.assign(form, { name: '', base_url: '', api_key: '', model_name: '', proxy_url: '' })
  fetchedModels.value = []
  dialogOpen.value = true
}

function openEditDialog(profile: AiProfile) {
  editingId.value = profile.id
  Object.assign(form, {
    name: profile.name,
    base_url: profile.base_url,
    api_key: '',
    model_name: profile.model_name,
    proxy_url: profile.proxy_url,
  })
  fetchedModels.value = []
  dialogOpen.value = true
}

async function handleSave() {
  isSaving.value = true
  try {
    const payload: AiProfilePayload = {
      name: form.name,
      base_url: form.base_url,
      model_name: form.model_name,
      proxy_url: form.proxy_url,
    }
    // 编辑时 API Key 留空表示保持不变
    if (editingId.value === null || form.api_key.trim()) {
      payload.api_key = form.api_key.trim()
    }
    const result =
      editingId.value === null
        ? await createAiProfile(payload)
        : await updateAiProfile(editingId.value, payload)
    toast({ title: result.message })
    dialogOpen.value = false
    await loadProfiles()
  } catch (e) {
    notifyError(t('settings.aiProfiles.saveFailed'), (e as Error).message)
  } finally {
    isSaving.value = false
  }
}

async function withBusy(profileId: number, action: () => Promise<void>) {
  busyProfileId.value = profileId
  try {
    await action()
  } catch (e) {
    notifyError(t('settings.aiProfiles.actionFailed'), (e as Error).message)
  } finally {
    busyProfileId.value = null
  }
}

const handleActivate = (p: AiProfile) =>
  withBusy(p.id, async () => {
    const result = await activateAiProfile(p.id)
    toast({ title: result.message })
    await loadProfiles()
  })

const handleToggle = (p: AiProfile, enabled: boolean) =>
  withBusy(p.id, async () => {
    await toggleAiProfile(p.id, enabled)
    await loadProfiles()
  })

const handleMove = (p: AiProfile, direction: 'up' | 'down') =>
  withBusy(p.id, async () => {
    await moveAiProfile(p.id, direction)
    await loadProfiles()
  })

const handleDelete = (p: AiProfile) =>
  withBusy(p.id, async () => {
    if (!window.confirm(t('settings.aiProfiles.deleteConfirm', { name: p.name }))) return
    const result = await deleteAiProfile(p.id)
    toast({ title: result.message })
    await loadProfiles()
  })

const handleTest = (p: AiProfile) =>
  withBusy(p.id, async () => {
    isTestingProfile.value = true
    try {
      const result = await testAiProfile(p.id)
      if (result.success) {
        toast({ title: result.message, description: result.response })
      } else {
        notifyError(t('settings.aiProfiles.testFailed'), result.message)
      }
    } finally {
      isTestingProfile.value = false
    }
  })

async function handleFetchModels() {
  isFetchingModels.value = true
  try {
    const result = await fetchAiModels({
      OPENAI_BASE_URL: form.base_url,
      OPENAI_API_KEY: form.api_key.trim() || undefined,
    })
    if (result.success && result.models.length) {
      fetchedModels.value = result.models
      toast({ title: t('settings.ai.fetchModelsSuccess', { count: result.models.length }) })
    } else {
      notifyError(t('settings.ai.fetchModelsFailed'), result.message || undefined)
    }
  } catch (e) {
    notifyError(t('settings.ai.fetchModelsFailed'), (e as Error).message)
  } finally {
    isFetchingModels.value = false
  }
}

function selectModel(model: string) {
  form.model_name = model
}

loadProfiles()

defineExpose({ loadProfiles })
</script>

<template>
  <Card>
    <CardHeader>
      <div class="flex items-start justify-between">
        <div>
          <CardTitle>{{ t('settings.aiProfiles.title') }}</CardTitle>
          <CardDescription>{{ t('settings.aiProfiles.description') }}</CardDescription>
        </div>
        <Button size="sm" @click="openCreateDialog">
          <Plus class="mr-1 h-4 w-4" />
          {{ t('settings.aiProfiles.add') }}
        </Button>
      </div>
    </CardHeader>
    <CardContent>
      <p v-if="isLoading && !profiles.length" class="py-8 text-center text-sm text-gray-500">
        {{ t('settings.ai.loading') }}
      </p>
      <p v-else-if="!profiles.length" class="py-8 text-center text-sm text-gray-500">
        {{ t('settings.aiProfiles.empty') }}
      </p>
      <div v-else class="space-y-3">
        <div
          v-for="(profile, index) in profiles"
          :key="profile.id"
          class="rounded-xl border p-4"
          :class="profile.is_active ? 'border-blue-300 bg-blue-50/50' : 'bg-white'"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium">{{ profile.name }}</span>
                <Badge v-if="profile.is_active" class="bg-blue-600">
                  {{ t('settings.aiProfiles.activeBadge') }}
                </Badge>
                <Badge v-if="!profile.enabled" variant="secondary">
                  {{ t('settings.aiProfiles.disabledBadge') }}
                </Badge>
              </div>
              <p class="mt-1 truncate text-sm text-gray-500">
                {{ profile.model_name }} · {{ hostOf(profile.base_url) }}
                <span v-if="profile.has_api_key"> · {{ profile.api_key_hint }}</span>
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-1.5">
              <Switch
                :model-value="profile.enabled"
                :disabled="busyProfileId === profile.id"
                @update:model-value="(v: boolean) => handleToggle(profile, v)"
              />
              <Button
                v-if="!profile.is_active"
                variant="outline"
                size="sm"
                :disabled="!profile.enabled || busyProfileId === profile.id"
                @click="handleActivate(profile)"
              >
                <CircleCheck class="mr-1 h-3.5 w-3.5" />
                {{ t('settings.aiProfiles.setActive') }}
              </Button>
              <Button
                variant="outline"
                size="sm"
                :disabled="busyProfileId === profile.id"
                @click="handleTest(profile)"
              >
                <Play class="mr-1 h-3.5 w-3.5" />
                {{ t('settings.aiProfiles.test') }}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8"
                :disabled="index === 0 || busyProfileId === profile.id"
                :title="t('settings.aiProfiles.moveUp')"
                @click="handleMove(profile, 'up')"
              >
                <ArrowUp class="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8"
                :disabled="index === profiles.length - 1 || busyProfileId === profile.id"
                :title="t('settings.aiProfiles.moveDown')"
                @click="handleMove(profile, 'down')"
              >
                <ArrowDown class="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8"
                @click="openEditDialog(profile)"
              >
                <Pencil class="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-red-500 hover:text-red-600"
                @click="handleDelete(profile)"
              >
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
        <p class="text-xs text-gray-500">{{ t('settings.aiProfiles.failoverHint') }}</p>
      </div>
    </CardContent>

    <Dialog v-model:open="dialogOpen">
      <DialogContent class="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {{
              editingId === null
                ? t('settings.aiProfiles.addTitle')
                : t('settings.aiProfiles.editTitle')
            }}
          </DialogTitle>
          <DialogDescription>{{ t('settings.aiProfiles.dialogDescription') }}</DialogDescription>
        </DialogHeader>
        <div class="grid gap-3">
          <div class="grid gap-1.5">
            <Label>{{ t('settings.aiProfiles.profileName') }}</Label>
            <Input v-model="form.name" :placeholder="t('settings.aiProfiles.profileNamePlaceholder')" />
          </div>
          <div class="grid gap-1.5">
            <Label>API Base URL</Label>
            <Input v-model="form.base_url" placeholder="https://api.deepseek.com" />
          </div>
          <div class="grid gap-1.5">
            <Label>API Key</Label>
            <Input
              v-model="form.api_key"
              type="password"
              :placeholder="
                editingId === null
                  ? t('settings.ai.keyPlaceholder')
                  : t('settings.aiProfiles.keyKeepPlaceholder')
              "
            />
            <p v-if="editingId !== null" class="text-xs text-gray-500">
              {{ t('settings.aiProfiles.keyKeepHint') }}
            </p>
          </div>
          <div class="grid gap-1.5">
            <Label>{{ t('settings.ai.modelName') }}</Label>
            <Input
              v-model="form.model_name"
              :placeholder="t('settings.ai.modelNamePlaceholder')"
              list="profile-model-suggestions"
              autocomplete="off"
            />
            <datalist id="profile-model-suggestions">
              <option v-for="m in modelSuggestions" :key="m" :value="m" />
            </datalist>
            <p v-if="isLikelyReasoningModel" class="text-xs font-medium text-amber-600">
              {{ t('settings.ai.modelNameReasoningWarning') }}
            </p>
            <p class="text-xs text-gray-500">{{ t('settings.ai.modelNameHint') }}</p>
            <div>
              <Button variant="outline" size="sm" :disabled="isFetchingModels" @click="handleFetchModels">
                <Download class="mr-1 h-3.5 w-3.5" />
                {{ isFetchingModels ? t('settings.ai.fetchModelsLoading') : t('settings.ai.fetchModels') }}
              </Button>
            </div>
            <div v-if="fetchedModels.length" class="grid gap-1">
              <p class="text-xs text-gray-500">{{ t('settings.ai.pickModelHint') }}</p>
              <div class="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto rounded-md border bg-slate-50 p-2">
                <button
                  v-for="m in fetchedModels"
                  :key="m"
                  type="button"
                  class="rounded-full border bg-white px-2.5 py-0.5 text-xs"
                  :class="form.model_name === m
                    ? 'border-blue-500 font-medium text-blue-600'
                    : 'border-gray-200 text-gray-600 hover:border-blue-400 hover:text-blue-600'"
                  @click="selectModel(m)"
                >
                  {{ m }}
                </button>
              </div>
            </div>
          </div>
          <div class="grid gap-1.5">
            <Label>{{ t('settings.ai.proxy') }}</Label>
            <Input v-model="form.proxy_url" placeholder="http://127.0.0.1:7890" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="dialogOpen = false">
            {{ t('common.cancel') }}
          </Button>
          <Button :disabled="isSaving" @click="handleSave">
            {{ t('settings.aiProfiles.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </Card>
</template>
