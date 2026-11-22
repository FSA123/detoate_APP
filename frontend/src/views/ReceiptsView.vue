<script setup>
// Bonurile de pe o zi (plătite și anulate), sau unul căutat după număr, cu detaliile la atingere
import { onActivated, ref, watch } from 'vue'

import { api } from '../api.js'
import AppDialog from '../components/AppDialog.vue'
import Icon from '../components/Icon.vue'
import { formatDateTime, formatLei, formatPercent, formatQuantity, localIsoDate } from '../money.js'

const PAGE = 100

const day = ref(localIsoDate())
const search = ref('')
const receipts = ref([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
const detail = ref(null)
const detailError = ref('')

function shiftDay(days) {
  const [y, m, d] = day.value.split('-').map(Number)
  day.value = localIsoDate(new Date(y, m - 1, d + days))
}

let seq = 0
let timer = null

async function load(append = false) {
  const mySeq = ++seq
  loading.value = true
  // Cu un număr căutat, în toate zilele; altfel ziua aleasă
  const params = { status: 'paid,cancelled', limit: PAGE, offset: append ? receipts.value.length : 0 }
  if (search.value.trim()) params.q = search.value.trim()
  else Object.assign(params, { date_from: day.value, date_to: day.value })
  try {
    const body = await api.orders(params)
    if (mySeq !== seq) return
    receipts.value = append ? [...receipts.value, ...body.items] : body.items
    total.value = body.total
    loadError.value = ''
  } catch (error) {
    if (mySeq === seq) loadError.value = error.message
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch(day, () => load())
watch(search, () => {
  clearTimeout(timer)
  timer = setTimeout(() => load(), 250)
})

async function open(receipt) {
  detail.value = { ...receipt, items: null }
  detailError.value = ''
  try {
    detail.value = await api.order(receipt.id)
  } catch (error) {
    detailError.value = error.message
  }
}

const time = (r) => formatDateTime(r.fiscalized_at || r.updated_at).split(' ')[1] ?? ''

onActivated(() => load())
</script>

<template>
  <section class="page receipts">
    <header class="page-head">
      <h2>Bonuri</h2>
      <div class="toolbar">
        <button type="button" aria-label="Ziua precedentă" @click="shiftDay(-1)"><Icon name="down" class="chev-left" /></button>
        <input v-model="day" type="date" :max="localIsoDate()" aria-label="Ziua" :disabled="!!search.trim()" />
        <button type="button" aria-label="Ziua următoare" :disabled="day >= localIsoDate()" @click="shiftDay(1)">
          <Icon name="down" class="chev-right" />
        </button>
        <button type="button" :class="{ dark: day === localIsoDate() }" @click="day = localIsoDate()">Azi</button>
        <div class="search-box">
          <Icon name="search" class="search-icon" />
          <input v-model="search" type="search" placeholder="Nr. bon, nr. comandă sau CUI" aria-label="Caută bon" />
        </div>
      </div>
    </header>

    <p v-if="loadError" class="notice error"><Icon name="warning" />{{ loadError }}</p>
    <p class="muted summary">
      <template v-if="search.trim()">
        {{ total }} {{ total === 1 ? 'bon găsit' : 'bonuri găsite' }} pentru „{{ search.trim() }}”, din toate zilele
      </template>
      <template v-else>{{ total }} {{ total === 1 ? 'bon' : 'bonuri' }} pe {{ formatDateTime(day) }}</template>
    </p>

    <div class="card table-card">
      <table class="data">
        <thead>
          <tr>
            <th>Ora</th><th>Bon fiscal</th><th>Comanda</th><th>Plată</th><th>Client</th><th class="num">Total (lei)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in receipts" :key="r.id" class="clickable" :class="{ cancelled: r.status === 'cancelled' }" @click="open(r)">
            <td class="num left">{{ search.trim() ? formatDateTime(r.fiscalized_at || r.updated_at) : time(r) }}</td>
            <td>
              {{ r.fiscal_receipt_number || '—' }}
              <em v-if="r.status === 'cancelled'" class="tag">anulat</em>
              <em v-else-if="r.fiscal_simulated" class="tag warn">simulat</em>
            </td>
            <td class="num left">#{{ r.id }}</td>
            <td>{{ r.payment_method === 'cash' ? 'Numerar' : r.payment_method === 'card' ? 'Card' : '—' }}</td>
            <td>{{ r.buyer_cui || '—' }}</td>
            <td class="num">{{ formatLei(r.total_bani) }}</td>
          </tr>
          <tr v-if="!receipts.length && !loading">
            <td colspan="6" class="empty-state">Niciun bon</td>
          </tr>
        </tbody>
      </table>
      <button v-if="receipts.length < total" type="button" class="more" :disabled="loading" @click="load(true)">
        Încă {{ Math.min(PAGE, total - receipts.length) }} din {{ total - receipts.length }}
      </button>
    </div>

    <AppDialog v-if="detail" :title="detail.status === 'cancelled' ? `Comanda #${detail.id} — anulată` : `Bon ${detail.fiscal_receipt_number || ''}`"
               width="620px" @close="detail = null">
      <p v-if="detailError" class="notice error"><Icon name="warning" />{{ detailError }}</p>
      <dl class="facts">
        <div><dt>Comanda</dt><dd>#{{ detail.id }}</dd></div>
        <div><dt>{{ detail.status === 'paid' ? 'Plătit' : 'Creat' }}</dt><dd>{{ formatDateTime(detail.fiscalized_at || detail.created_at) }}</dd></div>
        <div v-if="detail.status === 'paid'"><dt>Plată</dt><dd>{{ detail.payment_method === 'cash' ? 'Numerar' : 'Card' }}</dd></div>
        <div v-if="detail.fiscal_z_number"><dt>Raport Z</dt><dd>nr. {{ detail.fiscal_z_number }}</dd></div>
        <div v-if="detail.buyer_cui"><dt>Firmă</dt><dd>{{ detail.buyer_name ? `${detail.buyer_name} · ` : '' }}{{ detail.buyer_cui }}</dd></div>
        <div v-if="detail.fiscal_simulated"><dt>Simulare</dt><dd>nu s-a tipărit pe casa de marcat</dd></div>
      </dl>
      <table v-if="detail.items" class="data lines">
        <thead><tr><th>Produs</th><th class="num">Cantitate</th><th class="num">Preț</th><th class="num">Total</th></tr></thead>
        <tbody>
          <tr v-for="i in detail.items" :key="i.id">
            <td>
              {{ i.product_name }}
              <em v-if="i.discount_bp" class="tag brand">−{{ formatPercent(i.discount_bp) }}%</em>
              <em v-else-if="i.price_overridden" class="tag warn">preț modificat</em>
            </td>
            <td class="num">{{ formatQuantity(i.quantity_milli, i.sale_type) }}</td>
            <td class="num">{{ formatLei(i.unit_price_bani) }}</td>
            <td class="num">{{ formatLei(i.line_total_bani) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!detailError" class="muted">Se încarcă…</p>
      <div class="sum">
        <span>Total</span><strong>{{ formatLei(detail.total_bani) }} lei</strong>
      </div>
      <div v-if="detail.payment_method === 'cash' && detail.cash_received_bani !== null" class="sum small">
        <span>Primit {{ formatLei(detail.cash_received_bani) }} lei · rest</span>
        <strong>{{ formatLei(detail.cash_received_bani - detail.total_bani) }} lei</strong>
      </div>
      <template #actions>
        <button type="button" class="primary" @click="detail = null">Închide</button>
      </template>
    </AppDialog>
  </section>
</template>

<style scoped>
.toolbar input[type='date'] {
  width: 12rem;
}

.toolbar > button {
  min-width: var(--touch);
  padding: 0 0.9rem;
}

.chev-left {
  transform: rotate(90deg);
}

.chev-right {
  transform: rotate(-90deg);
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-box input {
  width: min(320px, 60vw);
  padding-left: 2.6rem;
}

.search-icon {
  position: absolute;
  left: 0.8rem;
  color: var(--muted);
  pointer-events: none;
}

.summary {
  margin-bottom: 0.75rem;
}

.table-card {
  padding: 0.25rem 0.5rem 0.5rem;
  overflow-x: auto;
}

td.left {
  text-align: left;
}

tr.cancelled td {
  color: var(--muted);
}

.more {
  display: flex;
  margin: 0.75rem auto 0.25rem;
}

.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.6rem 1rem;
  margin: 0;
}

.facts dt {
  font-size: 0.8rem;
  color: var(--muted);
}

.facts dd {
  margin: 0;
  font-weight: 500;
}

.sum {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 1.05rem;
}

.sum strong {
  font-size: 1.6rem;
}

.sum.small strong {
  font-size: 1.1rem;
}
</style>
