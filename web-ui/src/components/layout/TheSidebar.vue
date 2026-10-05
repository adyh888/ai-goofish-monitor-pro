<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import {
  LayoutDashboard,
  ListTodo,
  Users,
  Layers,
  Terminal,
  Settings2,
  ChevronRight,
  Ticket,
  UserCog,
  Settings2 as AdminSettingsIcon
} from 'lucide-vue-next'
import { useWebSocket } from '@/composables/useWebSocket'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from 'vue-i18n'

const emit = defineEmits<{
  (event: 'navigate'): void
}>()
const { isConnected } = useWebSocket()
const { isAdmin } = useAuth()
const { t } = useI18n()

const navItems = computed(() => [
  { to: '/dashboard', label: t('sidebar.dashboard'), icon: LayoutDashboard },
  { to: '/tasks', label: t('sidebar.tasks'), icon: ListTodo },
  { to: '/accounts', label: t('sidebar.accounts'), icon: Users },
  { to: '/results', label: t('sidebar.results'), icon: Layers },
  { to: '/logs', label: t('sidebar.logs'), icon: Terminal },
  { to: '/settings', label: t('sidebar.settings'), icon: Settings2 },
])

const adminItems = computed(() => [
  { to: '/admin/cards', label: t('sidebar.adminCards'), icon: Ticket },
  { to: '/admin/users', label: t('sidebar.adminUsers'), icon: UserCog },
  { to: '/admin/settings', label: t('sidebar.adminSettings'), icon: AdminSettingsIcon },
])

const connectionLabel = computed(() => (
  isConnected.value ? t('sidebar.backendConnected') : t('sidebar.backendConnecting')
))
const connectionTone = computed(() =>
  isConnected.value
    ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]'
    : 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.45)]'
)
</script>

<template>
  <nav class="space-y-1">
    <RouterLink
      v-for="item in navItems"
      :key="item.to"
      :to="item.to"
      v-slot="{ isActive }"
      class="group relative flex items-center px-4 py-3 rounded-xl transition-all duration-200 overflow-hidden"
      @click="emit('navigate')"
    >
      <!-- Active Background Effect -->
      <div 
        v-if="isActive" 
        class="absolute inset-0 bg-gradient-to-r from-primary/10 to-transparent z-0"
      ></div>
      <div 
        v-if="isActive" 
        class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-primary rounded-r-full"
      ></div>

      <div class="relative z-10 flex items-center w-full">
        <component 
          :is="item.icon" 
          class="w-5 h-5 mr-3 transition-colors"
          :class="isActive ? 'text-primary' : 'text-slate-400 group-hover:text-slate-600'"
        />
        <span 
          class="text-sm font-bold transition-colors flex-grow"
          :class="isActive ? 'text-slate-900' : 'text-slate-500 group-hover:text-slate-700'"
        >
          {{ item.label }}
        </span>
        <ChevronRight 
          v-if="isActive"
          class="w-4 h-4 text-primary animate-in fade-in slide-in-from-left-2"
        />
      </div>
    </RouterLink>

    <!-- 平台管理（仅管理员可见） -->
    <template v-if="isAdmin">
      <p class="px-4 pt-6 pb-1 text-[10px] font-black text-slate-400 uppercase tracking-widest">
        {{ t('sidebar.adminSection') }}
      </p>
      <RouterLink
        v-for="item in adminItems"
        :key="item.to"
        :to="item.to"
        v-slot="{ isActive }"
        class="group relative flex items-center px-4 py-3 rounded-xl transition-all duration-200 overflow-hidden"
        @click="emit('navigate')"
      >
        <div
          v-if="isActive"
          class="absolute inset-0 bg-gradient-to-r from-primary/10 to-transparent z-0"
        ></div>
        <div
          v-if="isActive"
          class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-primary rounded-r-full"
        ></div>

        <div class="relative z-10 flex items-center w-full">
          <component
            :is="item.icon"
            class="w-5 h-5 mr-3 transition-colors"
            :class="isActive ? 'text-primary' : 'text-slate-400 group-hover:text-slate-600'"
          />
          <span
            class="text-sm font-bold transition-colors flex-grow"
            :class="isActive ? 'text-slate-900' : 'text-slate-500 group-hover:text-slate-700'"
          >
            {{ item.label }}
          </span>
          <ChevronRight
            v-if="isActive"
            class="w-4 h-4 text-primary animate-in fade-in slide-in-from-left-2"
          />
        </div>
      </RouterLink>
    </template>

    <!-- Support Section -->
    <div class="mt-12 px-4">
      <div class="rounded-2xl p-4 bg-slate-50/50 border border-slate-100 border-dashed">
         <p class="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">{{ t('sidebar.systemStatus') }}</p>
         <div class="flex items-center gap-2">
            <div class="w-2 h-2 rounded-full" :class="connectionTone"></div>
            <span class="text-xs font-bold text-slate-600">{{ connectionLabel }}</span>
         </div>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.router-link-active {
  background-color: transparent !important;
}
</style>
