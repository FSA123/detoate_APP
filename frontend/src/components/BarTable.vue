<script setup>
// Un tabel cu bare de mărime: o singură serie, deci fără legendă — numele
// rândului și valoarea scrisă sunt eticheta, tabelul e vederea accesibilă.
import { computed } from 'vue'

import { formatLei, formatShare } from '../money.js'

const props = defineProps({
  rows: { type: Array, required: true },  // [{ key, label, value (bani), detail? }]
  total: { type: Number, required: true }, // pentru pondere
  labelHeader: { type: String, required: true },
  detailHeader: { type: String, default: '' },
})

const max = computed(() => Math.max(...props.rows.map((r) => r.value), 1))
</script>

<template>
  <table class="data bars">
    <thead>
      <tr>
        <th>{{ labelHeader }}</th>
        <th v-if="detailHeader" class="num">{{ detailHeader }}</th>
        <th class="bar-col" aria-hidden="true"></th>
        <th class="num">Valoare (lei)</th>
        <th class="num">Pondere</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="r in rows" :key="r.key" :title="`${r.label}: ${formatLei(r.value)} lei (${formatShare(r.value, total)})`">
        <td>{{ r.label }}</td>
        <td v-if="detailHeader" class="num">{{ r.detail }}</td>
        <td class="bar-col" aria-hidden="true">
          <span class="bar" :style="{ width: `${(r.value / max) * 100}%` }"></span>
        </td>
        <td class="num">{{ formatLei(r.value) }}</td>
        <td class="num share">{{ formatShare(r.value, total) }}</td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.bar-col {
  width: 34%;
  min-width: 80px;
}

/* Bară subțire, pornită din linia de bază: capătul de la bază drept, capătul de date rotunjit 4px */
.bar {
  display: block;
  height: 10px;
  min-width: 2px;
  background: var(--viz-bar);
  border-radius: 0 4px 4px 0;
}

tbody tr:hover .bar {
  background: var(--viz-bar-hover);
}

.share {
  color: var(--muted);
}
</style>
