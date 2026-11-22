<script setup>
import { onActivated, ref, watch } from 'vue'

import { api } from '../api.js'
import ExcelPanel from '../components/ExcelPanel.vue'
import Icon from '../components/Icon.vue'
import KgPricePanel from '../components/KgPricePanel.vue'
import ProductEditor from '../components/ProductEditor.vue'
import SegmentedControl from '../components/SegmentedControl.vue'
import { formatLei } from '../money.js'

const PAGE = 100
const SECTIONS = [
  { value: 'produse', label: 'Produse' },
  { value: 'excel', label: 'Excel' },
]

const section = ref('produse')
const query = ref('')
const active = ref('1')
const lowStock = ref(false)
const products = ref([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
const saved = ref('')

const editing = ref(undefined) // undefined = închis, null = produs nou, obiect = produs existent
const kgPanel = ref(null)

let seq = 0
let timer = null

async function load(append = false) {
  const mySeq = ++seq
  loading.value = true
  const params = { limit: PAGE, offset: append ? products.value.length : 0, active: active.value }
  if (query.value.trim()) params.q = query.value.trim()
  if (lowStock.value) params.low_stock = 1
  try {
    const body = await api.products(params)
    if (mySeq !== seq) return
    products.value = append ? [...products.value, ...body.items] : body.items
    total.value = body.total
    loadError.value = ''
  } catch (error) {
    if (mySeq === seq) loadError.value = error.message
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch([query, active, lowStock], () => {
  clearTimeout(timer)
  timer = setTimeout(() => load(), 200)
})

watch(section, (now) => {
  saved.value = ''
  if (now === 'produse') load() // după un import din Excel
})

function edit(product) {
  saved.value = ''
  editing.value = product
}

function onSaved(message) {
  editing.value = undefined
  saved.value = message
  load()
}

onActivated(() => {
  load()
  kgPanel.value?.load()
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <h2>Produse</h2>
      <SegmentedControl v-model="section" :options="SECTIONS" label="Secțiune" />
    </header>

    <template v-if="section === 'produse'">
      <KgPricePanel ref="kgPanel" />

      <h3 class="catalog-title">La bucată</h3>
      <div class="toolbar filters">
        <input v-model="query" type="search" placeholder="Caută cod, cod de bare sau nume" aria-label="Caută produs" />
        <select v-model="active" aria-label="Stare">
          <option value="1">Active</option>
          <option value="0">Inactive</option>
          <option value="all">Toate</option>
        </select>
        <label class="field inline"><input v-model="lowStock" type="checkbox" /> Sub stocul minim</label>
        <span class="spacer"></span>
        <span class="muted count">{{ total }} produse</span>
        <button type="button" class="primary" @click="edit(null)"><Icon name="plus" />Produs nou</button>
      </div>

      <p v-if="saved" class="notice ok" role="status"><Icon name="check" />{{ saved }}</p>
      <p v-if="loadError" class="notice error"><Icon name="warning" />{{ loadError }}</p>

      <div class="card table-card">
        <table class="data products">
          <thead>
            <tr>
              <th>Cod</th><th>Denumire</th><th class="num">Preț (lei / buc)</th><th class="num">Stoc (buc)</th><th class="num">Stoc minim</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in products" :key="p.id" class="clickable" :class="{ inactive: !p.active }" @click="edit(p)">
              <td class="code">{{ p.code }}</td>
              <td>
                {{ p.name }}
                <em v-if="!p.active" class="tag">inactiv</em>
                <em v-if="p.low_stock" class="tag warn">stoc scăzut</em>
              </td>
              <td class="num">{{ formatLei(p.price_bani) }}</td>
              <td class="num">{{ p.stock_qty }}</td>
              <td class="num">{{ p.min_stock_qty || '—' }}</td>
            </tr>
            <tr v-if="!products.length && !loading">
              <td colspan="5" class="empty-state">
                {{ query || lowStock ? 'Niciun produs nu se potrivește' : 'Niciun produs la bucată încă — adăugați unul (Produs nou) sau importați din Excel' }}
              </td>
            </tr>
          </tbody>
        </table>
        <button v-if="products.length < total" type="button" class="more" :disabled="loading" @click="load(true)">
          Încă {{ Math.min(PAGE, total - products.length) }} din {{ total - products.length }}
        </button>
      </div>
    </template>

    <ExcelPanel v-if="section === 'excel'" />

    <ProductEditor v-if="editing !== undefined" :product="editing" @close="editing = undefined" @saved="onSaved" />
  </section>
</template>

<style scoped>
.catalog-title {
  margin: 0 0 0.6rem;
}

.filters {
  margin-bottom: 0.9rem;
}

.filters input[type='search'] {
  width: min(360px, 100%);
}

.count {
  margin-right: 0.25rem;
}

.table-card {
  padding: 0.25rem 0.5rem 0.5rem;
  overflow-x: auto;
}

.code {
  font-family: var(--font-numbers);
}

.inactive td {
  color: var(--muted);
}

.more {
  display: flex;
  margin: 0.75rem auto 0.25rem;
}
</style>
