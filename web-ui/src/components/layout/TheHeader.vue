<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import DashboardTaskSearch from '@/components/layout/DashboardTaskSearch.vue'
import LocaleToggle from '@/components/layout/LocaleToggle.vue'
import {
  Zap,
  Bell,
  Search,
  UserCircle,
  HelpCircle,
  Menu,
  LogOut,
  Ticket,
  ChevronDown
} from 'lucide-vue-next'
import Badge from '@/components/ui/badge/Badge.vue'
import { useMobileNav } from '@/composables/useMobileNav'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from 'vue-i18n'

const router = useRouter()
const route = useRoute()
const { toggleMobileNav } = useMobileNav()
const inactiveSearchValue = ref('')
const userMenuOpen = ref(false)
const { t } = useI18n()
const { user, username, isAdmin, membershipActive, logout } = useAuth()

const isDashboard = computed(() => route.name === 'Dashboard')

const membershipLabel = computed(() => {
  if (!user.value) return ''
  if (isAdmin.value) return t('header.adminBadge')
  const days = user.value.remaining_days ?? 0
  if (days <= 0) return t('header.membershipExpired')
  if (days <= 3) return t('header.membershipExpiring', { days })
  return t('header.membershipDays', { days })
})

const membershipTone = computed(() => {
  if (isAdmin.value) return 'border-primary/20 text-primary bg-primary/5'
  const days = user.value?.remaining_days ?? 0
  if (days <= 0) return 'border-red-200 bg-red-50 text-red-600'
  if (days <= 3) return 'border-amber-200 bg-amber-50 text-amber-600'
  return 'border-emerald-200 bg-emerald-50 text-emerald-600'
})

function goActivate() {
  userMenuOpen.value = false
  router.push('/activate')
}

function handleLogout() {
  userMenuOpen.value = false
  logout()
}

function goNotifications() {
  router.push({ name: 'Settings', query: { tab: 'notifications' } })
}

function goPrompts() {
  router.push({ name: 'Settings', query: { tab: 'prompts' } })
}
</script>

<template>
  <header class="flex items-center justify-between px-6 h-16 bg-white/60 backdrop-blur-md border-b border-slate-200/60 sticky top-0 z-[100]">
    <!-- Brand Logo -->
    <RouterLink
      to="/dashboard"
      class="flex items-center gap-2 group rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      :aria-label="t('header.goHome')"
    >
      <div class="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shadow-lg shadow-primary/20 transition-transform group-hover:rotate-12">
        <Zap class="w-5 h-5 text-white fill-white" />
      </div>
      <h1 class="text-lg font-black text-slate-800 tracking-tighter">
        AI <span class="text-primary">Xianyu</span> Hunter
      </h1>
      <Badge variant="outline" class="ml-2 text-[10px] font-bold border-primary/20 text-primary bg-primary/5 uppercase tracking-widest hidden sm:flex">
        PRO
      </Badge>
    </RouterLink>

    <!-- Search & Navigation -->
    <div class="hidden md:flex flex-grow max-w-md mx-8">
      <DashboardTaskSearch v-if="isDashboard" />
      <div v-else class="relative w-full group">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 transition-colors" />
        <input 
          type="text" 
          v-model="inactiveSearchValue"
          readonly
          aria-disabled="true"
          :placeholder="t('header.searchUnavailable')"
          class="w-full h-10 pl-10 pr-4 bg-slate-100/50 border border-slate-200/50 rounded-xl text-sm transition-all focus:outline-none focus:ring-2 focus:ring-primary/20 focus:bg-white focus:border-primary/50"
        />
        <kbd class="absolute right-3 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded border border-slate-300 bg-white text-[10px] text-slate-400 font-sans shadow-sm pointer-events-none">
          /
        </kbd>
      </div>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-3">
      <div class="flex items-center gap-2">
        <LocaleToggle />
      </div>

      <div class="flex items-center gap-1 sm:gap-2">
         <Button
           variant="ghost"
           size="icon"
           class="rounded-full text-slate-500 hover:text-primary hover:bg-primary/10"
           :aria-label="t('header.openNotifications')"
           @click="goNotifications"
         >
            <Bell class="w-5 h-5" />
         </Button>
         <Button
           variant="ghost"
           size="icon"
           class="rounded-full text-slate-500 hover:text-primary hover:bg-primary/10"
           :aria-label="t('header.openPrompts')"
           @click="goPrompts"
         >
            <HelpCircle class="w-5 h-5" />
         </Button>
      </div>
      
      <div class="h-6 w-px bg-slate-200 mx-1 hidden sm:block"></div>

      <div class="relative">
        <Button
          variant="ghost"
          class="hidden sm:flex items-center gap-2 pl-2 pr-3 rounded-full hover:bg-slate-100 transition-all active:scale-95"
          aria-label="user menu"
          @click="userMenuOpen = !userMenuOpen"
        >
          <div class="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center overflow-hidden border border-slate-300 shadow-sm">
             <UserCircle class="w-6 h-6 text-slate-500" />
          </div>
          <div class="text-left hidden lg:block">
             <p class="text-xs font-black text-slate-700 leading-none mb-0.5">{{ username || '...' }}</p>
             <p class="text-[10px] font-semibold border rounded-full px-2 py-0.5 inline-block" :class="membershipTone">
               {{ membershipLabel }}
             </p>
          </div>
          <ChevronDown class="w-3.5 h-3.5 text-slate-400" />
        </Button>
        <Badge
          v-if="!membershipActive"
          variant="outline"
          class="sm:hidden border-red-200 bg-red-50 text-red-600 text-[10px]"
        >
          {{ t('header.membershipExpired') }}
        </Badge>

        <div
          v-if="userMenuOpen"
          class="absolute right-0 top-12 w-56 rounded-xl border border-slate-200/70 bg-white shadow-xl p-2 z-[120]"
          @click.stop
        >
            <div class="px-3 py-2 border-b border-slate-100">
              <p class="text-sm font-black text-slate-800">{{ username }}</p>
              <p class="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
                {{ isAdmin ? t('header.adminBadge') : t('header.userBadge') }}
              </p>
            </div>
            <button
              type="button"
              class="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-primary/5 hover:text-primary"
              @click="goActivate"
            >
              <Ticket class="w-4 h-4" />
              {{ t('header.activateMembership') }}
            </button>
            <button
              type="button"
              class="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-red-50 hover:text-red-500"
              @click="handleLogout"
            >
              <LogOut class="w-4 h-4" />
              {{ t('header.logout') }}
            </button>
          </div>
      </div>
      <div v-if="userMenuOpen" class="fixed inset-0 z-[110]" @click="userMenuOpen = false"></div>

      <Button
        variant="ghost"
        size="icon"
        class="md:hidden"
        :aria-label="t('header.openNavigation')"
        @click="toggleMobileNav"
      >
         <Menu class="w-6 h-6 text-slate-700" />
      </Button>
    </div>
  </header>
</template>
