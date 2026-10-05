<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import Toaster from '@/components/ui/toast/Toaster.vue'
import { useAuth } from '@/composables/useAuth'

// 应用启动时刷新一次会员状态（token 失效会自动登出）
onMounted(() => {
  useAuth().fetchMe()
})
</script>

<template>
  <RouterView />
  <Toaster />
</template>
