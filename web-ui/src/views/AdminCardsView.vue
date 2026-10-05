<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { adminApi, type CardKeyItem, type CardsSummary } from '@/api/admin'
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
import { Download, Plus, RefreshCw, Copy, Ban, RotateCcw } from 'lucide-vue-next'

const { t } = useI18n()

const cards = ref<CardKeyItem[]>([])
const summary = ref<CardsSummary>({ unused: 0, used: 0, disabled: 0 })
const isLoading = ref(false)
const statusFilter = ref('')

const generateOpen = ref(false)
const isGenerating = ref(false)
const genCount = ref(50)
const genDays = ref(30)
const genBatch = ref('')
const genNote = ref('')

const resultOpen = ref(false)
const resultCodes = ref<string[]>([])
const resultDays = ref(0)

const filteredCards = computed(() =>
  statusFilter.value
    ? cards.value.filter((card) => card.status === statusFilter.value)
    : cards.value,
)

async function loadCards() {
  isLoading.value = true
  try {
    const [list, cardSummary] = await Promise.all([
      adminApi.listCards({ limit: 1000 }),
      adminApi.cardsSummary(),
    ])
    cards.value = list.items
    summary.value = cardSummary
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.cards.loadFailed'), variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

async function handleGenerate() {
  if (genCount.value < 1 || genDays.value < 1) {
    toast({ description: t('admin.cards.invalidInput'), variant: 'destructive' })
    return
  }
  isGenerating.value = true
  try {
    const result = await adminApi.generateCards({
      count: genCount.value,
      duration_days: genDays.value,
      batch_no: genBatch.value.trim(),
      note: genNote.value.trim(),
    })
    generateOpen.value = false
    resultCodes.value = result.codes
    resultDays.value = result.duration_days
    resultOpen.value = true
    await loadCards()
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.cards.generateFailed'), variant: 'destructive' })
  } finally {
    isGenerating.value = false
  }
}

async function handleToggleStatus(card: CardKeyItem) {
  const target = card.status === 'disabled' ? 'unused' : 'disabled'
  try {
    await adminApi.setCardStatus(card.id, target)
    await loadCards()
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.cards.statusFailed'), variant: 'destructive' })
  }
}

function copyCodes() {
  navigator.clipboard.writeText(resultCodes.value.join('\n')).then(
    () => toast({ description: t('admin.cards.copied') }),
    () => toast({ description: t('admin.cards.copyFailed'), variant: 'destructive' }),
  )
}

function downloadTxt(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

async function handleExportUnused() {
  try {
    const text = await adminApi.exportCards()
    if (!text.trim()) {
      toast({ description: t('admin.cards.nothingToExport'), variant: 'destructive' })
      return
    }
    downloadTxt(text, `card-keys-${new Date().toISOString().slice(0, 10)}.txt`)
  } catch (e) {
    toast({ description: e instanceof Error ? e.message : t('admin.cards.exportFailed'), variant: 'destructive' })
  }
}

function statusBadgeClass(status: CardKeyItem['status']) {
  if (status === 'unused') return 'border-emerald-200 bg-emerald-50 text-emerald-600'
  if (status === 'used') return 'border-slate-200 bg-slate-100 text-slate-500'
  return 'border-red-200 bg-red-50 text-red-500'
}

onMounted(loadCards)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-black text-slate-900">{{ t('admin.cards.title') }}</h1>
        <p class="text-sm text-slate-500 mt-1">{{ t('admin.cards.description') }}</p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" :disabled="isLoading" @click="loadCards">
          <RefreshCw class="w-4 h-4 mr-1" />
          {{ t('common.refresh') }}
        </Button>
        <Button variant="outline" @click="handleExportUnused">
          <Download class="w-4 h-4 mr-1" />
          {{ t('admin.cards.exportUnused') }}
        </Button>
        <Button @click="generateOpen = true">
          <Plus class="w-4 h-4 mr-1" />
          {{ t('admin.cards.generate') }}
        </Button>
      </div>
    </div>

    <div class="grid grid-cols-3 gap-4">
      <Card><CardContent class="p-4">
        <p class="text-xs font-bold text-slate-400 uppercase">{{ t('admin.cards.unused') }}</p>
        <p class="text-2xl font-black text-emerald-600 mt-1">{{ summary.unused }}</p>
      </CardContent></Card>
      <Card><CardContent class="p-4">
        <p class="text-xs font-bold text-slate-400 uppercase">{{ t('admin.cards.used') }}</p>
        <p class="text-2xl font-black text-slate-600 mt-1">{{ summary.used }}</p>
      </CardContent></Card>
      <Card><CardContent class="p-4">
        <p class="text-xs font-bold text-slate-400 uppercase">{{ t('admin.cards.disabled') }}</p>
        <p class="text-2xl font-black text-red-500 mt-1">{{ summary.disabled }}</p>
      </CardContent></Card>
    </div>

    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-base">{{ t('admin.cards.listTitle') }}</CardTitle>
        <CardDescription>{{ t('admin.cards.listDescription') }}</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="flex gap-2 mb-4">
          <Button
            v-for="option in ['', 'unused', 'used', 'disabled']"
            :key="option || 'all'"
            size="sm"
            :variant="statusFilter === option ? 'default' : 'outline'"
            @click="statusFilter = option"
          >
            {{ option ? t(`admin.cards.status.${option}`) : t('admin.cards.all') }}
          </Button>
        </div>
        <div class="rounded-xl border border-slate-200/70 overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{{ t('admin.cards.code') }}</TableHead>
                <TableHead>{{ t('admin.cards.days') }}</TableHead>
                <TableHead>{{ t('admin.cards.statusCol') }}</TableHead>
                <TableHead>{{ t('admin.cards.batch') }}</TableHead>
                <TableHead>{{ t('admin.cards.usedAt') }}</TableHead>
                <TableHead class="text-right">{{ t('admin.cards.actions') }}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="card in filteredCards" :key="card.id">
                <TableCell class="font-mono text-xs font-bold">{{ card.code }}</TableCell>
                <TableCell>{{ card.duration_days }} {{ t('admin.cards.daysUnit') }}</TableCell>
                <TableCell>
                  <Badge variant="outline" :class="statusBadgeClass(card.status)">
                    {{ t(`admin.cards.status.${card.status}`) }}
                  </Badge>
                </TableCell>
                <TableCell class="text-xs text-slate-500">{{ card.batch_no || '-' }}</TableCell>
                <TableCell class="text-xs text-slate-500">
                  {{ card.used_at ? new Date(card.used_at).toLocaleString() : '-' }}
                </TableCell>
                <TableCell class="text-right">
                  <Button
                    v-if="card.status !== 'used'"
                    size="sm"
                    variant="ghost"
                    :class="card.status === 'disabled' ? 'text-emerald-600' : 'text-red-500'"
                    @click="handleToggleStatus(card)"
                  >
                    <Ban v-if="card.status === 'unused'" class="w-4 h-4" />
                    <RotateCcw v-else class="w-4 h-4" />
                    {{ card.status === 'disabled' ? t('admin.cards.enable') : t('admin.cards.disable') }}
                  </Button>
                  <span v-else class="text-xs text-slate-400">-</span>
                </TableCell>
              </TableRow>
              <TableRow v-if="!filteredCards.length">
                <TableCell colspan="6" class="text-center text-sm text-slate-400 py-8">
                  {{ t('admin.cards.empty') }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>

    <!-- 生成卡密 -->
    <Dialog v-model:open="generateOpen">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>{{ t('admin.cards.generate') }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-2">
          <div class="grid gap-2">
            <Label for="gen-count">{{ t('admin.cards.count') }}</Label>
            <Input id="gen-count" type="number" min="1" max="1000" v-model.number="genCount" />
          </div>
          <div class="grid gap-2">
            <Label for="gen-days">{{ t('admin.cards.durationDays') }}</Label>
            <Input id="gen-days" type="number" min="1" max="3650" v-model.number="genDays" />
          </div>
          <div class="grid gap-2">
            <Label for="gen-batch">{{ t('admin.cards.batchNo') }}</Label>
            <Input id="gen-batch" type="text" v-model="genBatch" placeholder="2026-10" />
          </div>
          <div class="grid gap-2">
            <Label for="gen-note">{{ t('admin.cards.note') }}</Label>
            <Input id="gen-note" type="text" v-model="genNote" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="generateOpen = false">{{ t('common.cancel') }}</Button>
          <Button :disabled="isGenerating" @click="handleGenerate">
            {{ isGenerating ? t('admin.cards.generating') : t('admin.cards.generate') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 生成结果 -->
    <Dialog v-model:open="resultOpen">
      <DialogContent class="max-w-lg">
        <DialogHeader>
          <DialogTitle>{{ t('admin.cards.resultTitle', { count: resultCodes.length, days: resultDays }) }}</DialogTitle>
        </DialogHeader>
        <div class="max-h-72 overflow-y-auto rounded-lg bg-slate-50 p-3 font-mono text-xs leading-5 whitespace-pre-wrap">{{ resultCodes.join('\n') }}</div>
        <DialogFooter>
          <Button variant="outline" @click="copyCodes">
            <Copy class="w-4 h-4 mr-1" />
            {{ t('admin.cards.copyAll') }}
          </Button>
          <Button @click="downloadTxt(resultCodes.join('\n'), `card-keys-${resultDays}d.txt`)">
            <Download class="w-4 h-4 mr-1" />
            {{ t('admin.cards.download') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
