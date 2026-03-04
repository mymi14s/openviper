import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Lazy load views
const Login = () => import('@/views/Login.vue')
const Dashboard = () => import('@/views/Dashboard.vue')
const ModelList = () => import('@/views/ModelList.vue')
const ModelCreate = () => import('@/views/ModelCreate.vue')
const ModelEdit = () => import('@/views/ModelEdit.vue')
const ModelHistory = () => import('@/views/ModelHistory.vue')
const NotFound = () => import('@/views/NotFound.vue')

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: Login,
    meta: { requiresAuth: false, title: 'Login' },
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: Dashboard,
    meta: { requiresAuth: true, title: 'Dashboard' },
  },
  {
    path: '/:appLabel/:modelName',
    name: 'model-list',
    component: ModelList,
    meta: { requiresAuth: true },
    props: true,
  },
  {
    path: '/:appLabel/:modelName/add',
    name: 'model-create',
    component: ModelCreate,
    meta: { requiresAuth: true },
    props: true,
  },
  {
    path: '/:appLabel/:modelName/:id',
    name: 'model-edit',
    component: ModelEdit,
    meta: { requiresAuth: true },
    props: true,
  },
  {
    path: '/:appLabel/:modelName/:id/history',
    name: 'model-history',
    component: ModelHistory,
    meta: { requiresAuth: true },
    props: true,
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: NotFound,
    meta: { title: 'Not Found' },
  },
]

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 }
  },
})

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()
  const requiresAuth = to.meta.requiresAuth !== false

  const title = to.meta.title as string | undefined
  document.title = title ? `${title} | OpenViper Admin` : 'OpenViper Admin'

  if (requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (requiresAuth && authStore.isAuthenticated && !authStore.isStaff && !authStore.isSuperuser) {
    authStore.clearAuth()
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (to.name === 'login' && authStore.isAuthenticated) {
    next({ name: 'dashboard' })
  } else {
    next()
  }
})

export default router
