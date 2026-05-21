<script setup>
const props = defineProps({ severity: String })
const cls = {
  INFO: 'pill pill-info',
  LOW: 'pill pill-low',
  MEDIUM: 'pill pill-medium',
  HIGH: 'pill pill-high',
  CRITICAL: 'pill pill-critical',
}[props.severity] || 'pill pill-info'
</script>
<template>
  <span :class="cls">{{ severity }}</span>
</template>
