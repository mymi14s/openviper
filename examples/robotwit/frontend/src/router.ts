import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes = [
  { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
  { path: '/explore', name: 'explore', component: () => import('./views/ExploreView.vue') },
  { path: '/notifications', name: 'notifications', component: () => import('./views/NotificationsView.vue'), meta: { requiresAuth: true } },
  { path: '/bookmarks', name: 'bookmarks', component: () => import('./views/BookmarksView.vue'), meta: { requiresAuth: true } },
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
  { path: '/register', name: 'register', component: () => import('./views/RegisterView.vue') },
  { path: '/agent/:id', name: 'profile', component: () => import('./views/ProfileView.vue') },
  { path: '/tweet/:id', name: 'tweet', component: () => import('./views/TweetView.vue') },
  { path: '/hashtag/:name', name: 'hashtag', component: () => import('./views/HashtagView.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    next('/login')
  } else {
    next()
  }
})