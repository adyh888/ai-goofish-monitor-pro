<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { adminApi, type AdminUserItem } from '@/api/admin'
import { useAuth } from '@/composables/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Badge from '@/components/ui/badge/Badge.vue'
import { toast } from '@/components/ui/toast'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { KeyRound, Plus, RefreshCw, UserCheck, UserX } from 'lucide-vue-next'

const { t } = useI18n()
const { user: currentUser } = useAuth()

const users = ref<AdminUserItem[]>([])
const isLoading = ref(false)

const expiryOpen = ref(false)
const expiryTarget = ref<AdminUserItem | null>(null)
const expiryValue = ref('')
const isSavingExpiry = ref(false)

const passwordOpen = ref(false)
const passwordTarget = ref<AdminUserItem | null>(null)
const newPassword = ref('')
const isSavingPassword = ref(false)

const createOpen = ref(false)
const isCreating = ref(false)
const newUsername = ref('')
const newPasswordInput = ref('')

async function loadUsers() {
  isLoading.value = true
  try {
    const result = await adminApi.listUsers()
    users.value = result.items
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.users.loadFailed'), variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

function openExpiry(user: AdminUserItem) {
  expiryTarget.value = user
  expiryValue.value = user.expired_at ? user.expired_at.slice(0, 16) : ''
  expiryOpen.value = true
}

async function saveExpiry() {
  if (!expiryTarget.value) return
  isSavingExpiry.value = true
  try {
    const isoValue = expiryValue.value ? new Date(expiryValue.value).toISOString() : null
    await adminApi.setUserExpiry(expiryTarget.value.id, isoValue)
    expiryOpen.value = false
    toast({ description: t('admin.users.expirySaved') })
    await loadUsers()
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.users.saveFailed'), variant: 'destructive' })
  } finally {
    isSavingExpiry.value = false
  }
}

async function clearExpiry(user: AdminUserItem) {
  try {
    await adminApi.setUserExpiry(user.id, null)
    toast({ description: t('admin.users.expiryCleared') })
    await loadUsers()
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.users.saveFailed'), variant: 'destructive' })
  }
}

async function toggleStatus(user: AdminUserItem) {
  const target = user.status === 'active' ? 'disabled' : 'active'
  try {
    await adminApi.setUserStatus(user.id, target)
    await loadUsers()
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.users.saveFailed'), variant: 'destructive' })
  }
}

function openPasswordReset(user: AdminUserItem) {
  passwordTarget.value = user
  newPassword.value = ''
  passwordOpen.value = true
}

async function savePassword() {
  if (!passwordTarget.value) return
  if (newPassword.value.length < 6) {
    toast({ description: t('admin.users.passwordTooShort'), variant: 'destructive' })
    return
  }
  isSavingPassword.value = true
  try {
    await adminApi.resetUserPassword(passwordTarget.value.id, newPassword.value)
    passwordOpen.value = false
    toast({ description: t('admin.users.passwordReset') })
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.users.saveFailed'), variant: 'destructive' })
  } finally {
    isSavingPassword.value = false
  }
}

async function handleCreate() {
  if (!newUsername.value.trim() || newPasswordInput.value.length < 6) {
    toast({ description: t('admin.users.invalidCreate'), variant: 'destructive' })
    return
  }
  isCreating.value = true
  try {
    await adminApi.createUser({
      username: newUsername.value.trim(),
      password: newPasswordInput.value,
    })
    createOpen.value = false
    newUsername.value = ''
    newPasswordInput.value = ''
    toast({ description: t('admin.users.created') })
    await loadUsers()
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.users.createFailed'), variant: 'destructive' })
  } finally {
    isCreating.value = false
  }
}

function formatExpiry(user: AdminUserItem) {
  if (user.role === 'admin') return t('admin.users.unlimited')
  if (!user.expired_at) return t('activate.neverActivated')
  return new Date(user.expired_at).toLocaleString()
}

onMounted(loadUsers)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-black text-slate-900">{{ t('admin.users.title') }}</h1>
        <p class="text-sm text-slate-500 mt-1">{{ t('admin.users.description') }}</p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" :disabled="isLoading" @click="loadUsers">
          <RefreshCw class="w-4 h-4 mr-1" />
          {{ t('common.refresh') }}
        </Button>
        <Button @click="createOpen = true">
          <Plus class="w-4 h-4 mr-1" />
          {{ t('admin.users.create') }}
        </Button>
      </div>
    </div>

    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-base">{{ t('admin.users.listTitle') }}</CardTitle>
        <CardDescription>{{ t('admin.users.listDescription') }}</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="rounded-xl border border-slate-200/70 overflow-hidden overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{{ t('admin.users.username') }}</TableHead>
                <TableHead>{{ t('admin.users.role') }}</TableHead>
                <TableHead>{{ t('admin.users.status') }}</TableHead>
                <TableHead>{{ t('admin.users.membership') }}</TableHead>
                <TableHead>{{ t('admin.users.expiry') }}</TableHead>
                <TableHead class="text-right">{{ t('admin.users.actions') }}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="user in users" :key="user.id">
                <TableCell class="font-bold">
                  {{ user.username }}
                  <span v-if="currentUser && user.id === currentUser.id" class="ml-1 text-[10px] text-primary">({{ t('admin.users.you') }})</span>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" :class="user.role === 'admin' ? 'border-primary/20 bg-primary/5 text-primary' : 'border-slate-200 bg-slate-50 text-slate-500'">
                    {{ user.role === 'admin' ? t('admin.users.roleAdmin') : t('admin.users.roleUser') }}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" :class="user.status === 'active' ? 'border-emerald-200 bg-emerald-50 text-emerald-600' : 'border-red-200 bg-red-50 text-red-500'">
                    {{ user.status === 'active' ? t('admin.users.statusActive') : t('admin.users.statusDisabled') }}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" :class="user.membership_active ? 'border-emerald-200 bg-emerald-50 text-emerald-600' : 'border-amber-200 bg-amber-50 text-amber-600'">
                    {{ user.membership_active ? t('admin.users.memberActive') : t('admin.users.memberInactive') }}
                  </Badge>
                </TableCell>
                <TableCell class="text-xs text-slate-500">{{ formatExpiry(user) }}</TableCell>
                <TableCell class="text-right">
                  <div class="inline-flex gap-1">
                    <Button size="sm" variant="ghost" title="调整到期时间" @click="openExpiry(user)">
                      <KeyRound class="w-4 h-4 text-slate-400" />
                    </Button>
                    <Button
                      v-if="!currentUser || user.id !== currentUser.id"
                      size="sm"
                      variant="ghost"
                      :class="user.status === 'active' ? 'text-red-500' : 'text-emerald-600'"
                      @click="toggleStatus(user)"
                    >
                      <UserX v-if="user.status === 'active'" class="w-4 h-4" />
                      <UserCheck v-else class="w-4 h-4" />
                    </Button>
                    <Button size="sm" variant="ghost" :title="t('admin.users.resetPassword')" @click="openPasswordReset(user)">
                      <KeyRound class="w-4 h-4 text-slate-400" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>

    <!-- 调整到期时间 -->
    <Dialog v-model:open="expiryOpen">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>{{ t('admin.users.expiryDialogTitle', { user: expiryTarget?.username }) }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-2">
          <div class="grid gap-2">
            <Label for="expiry-value">{{ t('admin.users.expiryLabel') }}</Label>
            <Input id="expiry-value" type="datetime-local" v-model="expiryValue" />
          </div>
          <p class="text-xs text-slate-400">{{ t('admin.users.expiryHint') }}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="expiryTarget && clearExpiry(expiryTarget)">
            {{ t('admin.users.clearExpiry') }}
          </Button>
          <Button :disabled="isSavingExpiry" @click="saveExpiry">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 重置密码 -->
    <Dialog v-model:open="passwordOpen">
      <DialogContent class="max-w-sm">
        <DialogHeader>
          <DialogTitle>{{ t('admin.users.resetPasswordTitle', { user: passwordTarget?.username }) }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-2 py-2">
          <Label for="new-password">{{ t('admin.users.newPassword') }}</Label>
          <Input id="new-password" type="text" v-model="newPassword" />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="passwordOpen = false">{{ t('common.cancel') }}</Button>
          <Button :disabled="isSavingPassword" @click="savePassword">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 新建用户 -->
    <Dialog v-model:open="createOpen">
      <DialogContent class="max-w-sm">
        <DialogHeader>
          <DialogTitle>{{ t('admin.users.create') }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-2">
          <div class="grid gap-2">
            <Label for="new-username">{{ t('admin.users.username') }}</Label>
            <Input id="new-username" type="text" v-model="newUsername" />
          </div>
          <div class="grid gap-2">
            <Label for="create-password">{{ t('admin.users.initialPassword') }}</Label>
            <Input id="create-password" type="text" v-model="newPasswordInput" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="createOpen = false">{{ t('common.cancel') }}</Button>
          <Button :disabled="isCreating" @click="handleCreate">{{ t('common.save') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
