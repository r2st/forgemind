<script setup>
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  Tooltip, Legend, TimeScale, Filler,
} from 'chart.js'
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, TimeScale, Filler)

defineProps({
  labels: { type: Array, default: () => [] },
  datasets: { type: Array, default: () => [] },
  height: { type: Number, default: 220 },
})
</script>
<template>
  <div :style="{ height: height + 'px' }">
    <Line
      :data="{ labels, datasets }"
      :options="{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#cbd5e1' } } },
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1d2530' } },
          y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1d2530' } },
        },
        elements: { point: { radius: 0 }, line: { tension: 0.3, borderWidth: 2 } },
      }"
    />
  </div>
</template>
