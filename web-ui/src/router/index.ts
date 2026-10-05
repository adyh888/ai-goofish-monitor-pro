import { watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'
import { useAuth } from '@/composables/useAuth'
import { i18n, t } from '@/i18n'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { titleKey: 'routes.login' },
  },
  {
    path: '/activate',
    name: 'Activate',
    component: () => import('@/views/ActivateView.vue'),
    meta: { titleKey: 'routes.activate' },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { titleKey: 'routes.dashboard', requiresAuth: true },
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('@/views/TasksView.vue'),
        meta: { titleKey: 'routes.tasks', requiresAuth: true },
      },
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('@/views/AccountsView.vue'),
        meta: { titleKey: 'routes.accounts', requiresAuth: true },
      },
      {
        path: 'results',
        name: 'Results',
        component: () => import('@/views/ResultsView.vue'),
        meta: { titleKey: 'routes.results', requiresAuth: true },
      },
      {
        path: 'logs',
        name: 'Logs',
        component: () => import('@/views/LogsView.vue'),
        meta: { titleKey: 'routes.logs', requiresAuth: true },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { titleKey: 'routes.settings', requiresAuth: true },
      },
      {
        path: 'admin/cards',
        name: 'AdminCards',
        component: () => import('@/views/AdminCardsView.vue'),
        meta: { titleKey: 'routes.adminCards', requiresAuth: true, requiresAdmin: true },
      },
      {
        path: 'admin/users',
        name: 'AdminUsers',
        component: () => import('@/views/AdminUsersView.vue'),
        meta: { titleKey: 'routes.adminUsers', requiresAuth: true, requiresAdmin: true },
      },
      {
        path: 'admin/settings',
        name: 'AdminSettings',
        component: () => import('@/views/AdminSettingsView.vue'),
        meta: { titleKey: 'routes.adminSettings', requiresAuth: true, requiresAdmin: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

function updateDocumentTitle() {
  const currentRoute = router.currentRoute.value
  const titleKey = typeof currentRoute.meta.titleKey === 'string'
    ? currentRoute.meta.titleKey
    : null
  const appName = t('app.name')
  document.title = titleKey ? `${t(titleKey)} - ${appName}` : appName
}

router.beforeEach((to, _from, next) => {
  const { isAuthenticated, membershipActive, isAdmin } = useAuth()

  if (to.meta.requiresAuth && !isAuthenticated.value) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  if (isAuthenticated.value && to.name === 'Login') {
    next({ name: 'Dashboard' })
    return
  }

  // 会员拦截：未激活/已过期的用户只能停留在激活页（后端 403 兜底）
  if (
    isAuthenticated.value &&
    to.meta.requiresAuth &&
    to.name !== 'Activate' &&
    !membershipActive.value
  ) {
    next({ name: 'Activate' })
    return
  }

  if (to.meta.requiresAdmin && !isAdmin.value) {
    next({ name: 'Dashboard' })
    return
  }

  next()
})

router.afterEach(() => {
  updateDocumentTitle()
})

watch(
  () => i18n.global.locale.value,
  () => {
    updateDocumentTitle()
  },
)

export default router
