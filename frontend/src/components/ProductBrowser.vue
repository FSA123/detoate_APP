<script setup>
import { ref, watch } from 'vue'

import { api } from '../api.js'
import { formatLei, parseEntry } from '../money.js'
import { store } from '../store.js'
import Icon from './Icon.vue'

const emit = defineEmits(['pick'])

const query = ref('')
// Vânzarea la kilogram: un singur preț pe kg pentru orice marfă (backend: rândul fix KG)
const kg = ref(null)
const products = ref([]) // catalogul: produsele la bucată
const totalProducts = ref(0)
const input = ref(null)
const LIMIT = 80

let searchSeq = 0
let searchTimer = null

async function search() {
  clearTimeout(searchTimer)
  const seq = ++searchSeq
  const params = { limit: LIMIT }
  const text = parseEntry(query.value)?.code ?? query.value.trim()
  if (text) params.q = text
  try {
    const { items, total } = await api.products(params)
    if (seq !== searchSeq) return // un răspuns întârziat nu suprascrie unul mai nou
    products.value = items
    totalProducts.value = total
  } catch (error) {
    store.error = error.message
  }
}

watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(search, 150)
})

// Textul rămas în câmp (un cod greșit, o căutare) rămâne vizibil, dar selectat:
// următoarea scanare îl înlocuiește în loc să se lipească de el
function focus() {
  input.value?.select()
}

function fail(message) {
  store.error = message
  focus()
}

function clear() {
  query.value = ''
  input.value?.focus()
}

// Enter: cod sau cod de bare exact (tastat sau scanat); dacă nu e un cod și
// textul potrivește un singur produs, acela
async function submit() {
  const entry = parseEntry(query.value)
  if (!entry) return fail('Cantitate invalidă — exemplu: 3*200 sau 1,250*101')
  if (!entry.code) return
  let product
  try {
    product = await api.lookup(entry.code)
  } catch (error) {
    if (error.status !== 404) return fail(error.message)
    await search()
    if (products.value.length !== 1) {
      return fail(products.value.length ? `Alegeți produsul din listă (${products.value.length} rezultate)` : error.message)
    }
    product = products.value[0]
  }
  query.value = ''
  emit('pick', product, entry.quantityMilli)
}

// La kilogram: casierul tastează doar greutatea (dialogul de cântar din CashierView)
function pickKg() {
  if (!kg.value) return
  if (!kg.value.price_bani) return fail('Prețul pe kilogram nu e setat — setați-l în Produse → La kilogram')
  emit('pick', kg.value)
}

async function loadKg() {
  try {
    kg.value = await api.kg()
  } catch (error) {
    store.error = error.message
  }
}

// La fiecare întoarcere pe ecranul casei (îl cheamă CashierView): produsele și prețul
// pe kg modificate între timp pe pagina Produse apar fără reîncărcarea paginii
function refresh() {
  search()
  loadKg()
}

defineExpose({ focus, refresh })
</script>

<template>
  <section class="browser">
    <div class="search-box">
      <Icon name="search" :size="24" class="search-icon" />
      <input
        ref="input"
        v-model="query"
        class="search"
        type="text"
        autocomplete="off"
        spellcheck="false"
        aria-label="Caută produs"
        placeholder="Cod, nume sau scanare  ·  3*200 = 3 buc"
        @keydown.enter.prevent="submit"
        @keydown.esc="query = ''"
      />
      <button v-if="query" type="button" class="ghost clear" aria-label="Golește căutarea" @mousedown.prevent @click="clear">
        <Icon name="close" />
      </button>
    </div>

    <!-- mousedown.prevent: o atingere nu ia focusul din câmpul de căutare, unde „tastează” scannerul -->
    <button type="button" class="kg" :class="{ unset: kg && !kg.price_bani }" :disabled="!kg"
            @mousedown.prevent @click="pickKg">
      <Icon name="weight" :size="30" />
      <span class="kg-label">La kilogram</span>
      <span class="kg-price">{{ kg?.price_bani ? `${formatLei(kg.price_bani)} lei / kg` : 'preț nesetat' }}</span>
    </button>

    <h3 class="section-title"><Icon name="piece" :size="18" />La bucată</h3>

    <div class="grid">
      <button v-for="p in products" :key="p.id" class="tile" @mousedown.prevent @click="emit('pick', p)">
        <span class="tile-name">{{ p.name }}</span>
        <span class="tile-foot">
          <span class="tile-price">{{ formatLei(p.price_bani) }}<small> lei</small></span>
          <span class="tile-code">{{ p.code }}</span>
        </span>
      </button>
      <p v-if="!products.length" class="empty-state">
        {{ query ? 'Niciun produs găsit' : 'Niciun produs la bucată încă — se adaugă din Produse' }}
      </p>
      <p v-if="totalProducts > products.length" class="more-hint muted">
        Se văd primele {{ products.length }} din {{ totalProducts }} produse — căutați după nume sau cod.
      </p>
    </div>
  </section>
</template>

<style scoped>
.browser {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1rem 1.1rem 0;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 1rem;
  color: var(--muted);
  pointer-events: none;
}

.search {
  min-height: 60px;
  padding: 0 3.5rem 0 3.25rem;
  font-size: 1.2rem;
  border-width: 2px;
  border-radius: 16px;
}

.clear {
  position: absolute;
  right: 0.4rem;
  width: var(--touch);
  padding: 0;
}

/* Vânzarea la kilogram: un buton mare, mereu vizibil, deasupra produselor la bucată */
.kg {
  min-height: 72px;
  justify-content: flex-start;
  gap: 0.75rem;
  padding: 0 1.25rem;
  font-size: 1.2rem;
  font-weight: 600;
  background: var(--brand-soft);
  border: 2px solid var(--brand);
  border-radius: 16px;
}

.kg:active:not(:disabled) {
  background: var(--brand-soft);
}

.kg-price {
  margin-left: auto;
  font-family: var(--font-numbers);
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  color: var(--brand-deep);
}

.kg.unset {
  background: var(--surface);
  border-style: dashed;
}

.kg.unset .kg-price {
  font-family: inherit;
  font-weight: 500;
  color: var(--muted);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0.15rem 0 -0.35rem;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--muted);
}

.grid {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  grid-auto-rows: minmax(124px, auto);
  align-content: start;
  gap: 0.65rem;
  padding-bottom: 1rem;
}

.tile {
  flex-direction: column;
  align-items: stretch;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.85rem 0.9rem;
  text-align: left;
  border: 1.5px solid var(--border);
  border-radius: 16px;
}

.tile:active {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.tile-name {
  font-weight: 600;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.tile-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}

.tile-price {
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--brand-strong);
}

.tile-price small {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--muted);
}

.tile-code {
  font-size: 0.75rem;
  color: var(--muted);
}

.grid > .empty-state,
.more-hint {
  grid-column: 1 / -1;
  padding: 0.5rem 0 1rem;
  text-align: center;
}
</style>
