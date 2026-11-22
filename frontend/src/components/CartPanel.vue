<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import { formatLei, formatPercent, formatQuantity } from '../money.js'
import { cancelOrder, removeItem, setBuyer, store, updateItem } from '../store.js'
import AppDialog from './AppDialog.vue'
import Icon from './Icon.vue'
import LineEditor from './LineEditor.vue'

const emit = defineEmits(['pay', 'done'])

const order = computed(() => store.order)
const items = computed(() => store.order?.items ?? [])
const isCompany = computed(() => store.order?.buyer_type === 'pj')

// ─── Linii: atingere → editare; −/+ pentru produsele la bucată ────────────────

const editing = ref(null)

function closeEditor() {
  editing.value = null
  emit('done')
}

async function step(item, pieces) {
  const quantity = item.quantity_milli + pieces * 1000
  await (quantity > 0 ? updateItem(item.id, { quantity_milli: quantity }) : removeItem(item.id))
  emit('done')
}

watch(items, (now) => {
  if (editing.value && !now.some((i) => i.id === editing.value.id)) editing.value = null
  nextTick(() => document.querySelector('.lines .last')?.scrollIntoView({ block: 'nearest' }))
})

// ─── Cumpărătorul: persoană fizică sau firmă cu CUI ───────────────────────────

const buyerOpen = ref(false)
const buyerCui = ref('')
const buyerName = ref('')
const buyerCuiInput = ref(null)

function openBuyer() {
  buyerCui.value = store.order?.buyer_cui ?? ''
  buyerName.value = store.order?.buyer_name ?? ''
  buyerOpen.value = true
  nextTick(() => buyerCuiInput.value?.focus())
}

function closeBuyer() {
  buyerOpen.value = false
  emit('done')
}

async function saveBuyer() {
  if (await setBuyer({ buyer_type: 'pj', buyer_cui: buyerCui.value, buyer_name: buyerName.value })) closeBuyer()
}

async function clearBuyer() {
  if (await setBuyer({ buyer_type: 'pf' })) closeBuyer()
}

// ─── Anulare, cu confirmare ───────────────────────────────────────────────────

const confirmingCancel = ref(false)
const keepButton = ref(null)

function askCancel() {
  confirmingCancel.value = true
  nextTick(() => keepButton.value?.focus())
}

async function cancel() {
  confirmingCancel.value = false
  if (await cancelOrder()) emit('done')
}

// Altă comandă pe ecran (plătită, anulată) — dialogurile deschise nu mai au sens
watch(
  () => store.order?.id,
  (_, oldId) => {
    if (oldId == null) return
    editing.value = null
    buyerOpen.value = false
    confirmingCancel.value = false
  },
)
</script>

<template>
  <aside class="cart">
    <header class="cart-head">
      <h2>{{ order ? `Bon #${order.id}` : 'Bon nou' }}</h2>
      <button v-if="order" type="button" class="danger cancel" @click="askCancel"><Icon name="trash" />Anulează</button>
    </header>

    <ol class="lines">
      <li v-for="item in items" :key="item.id" :class="{ last: item.id === store.lastItemId }">
        <button type="button" class="line" :aria-label="`Modifică ${item.product_name}`" @click="editing = item">
          <span class="line-name">
            {{ item.product_name }}
            <em v-if="item.discount_bp" class="tag brand">−{{ formatPercent(item.discount_bp) }}%</em>
            <em v-else-if="item.price_overridden" class="tag warn">preț modificat</em>
          </span>
          <span class="line-detail num">{{ formatQuantity(item.quantity_milli, item.sale_type) }} × {{ formatLei(item.unit_price_bani) }}</span>
          <span class="line-total num">{{ formatLei(item.line_total_bani) }}</span>
        </button>
        <div v-if="item.sale_type === 'unit'" class="steppers">
          <button type="button" class="step" aria-label="O bucată mai puțin" @click="step(item, -1)"><Icon name="minus" /></button>
          <button type="button" class="step" aria-label="O bucată în plus" @click="step(item, 1)"><Icon name="plus" /></button>
        </div>
      </li>
      <li v-if="!items.length" class="empty-state">Scanați sau atingeți un produs</li>
    </ol>

    <footer class="cart-foot">
      <button type="button" class="buyer" :class="{ company: isCompany }" @click="openBuyer">
        <Icon name="company" />
        <span v-if="isCompany">Firmă: <strong>{{ order.buyer_name || order.buyer_cui }}</strong>
          <span v-if="order.buyer_name" class="muted"> · {{ order.buyer_cui }}</span></span>
        <span v-else>Persoană fizică · <u>adaugă CUI firmă</u></span>
      </button>

      <div class="total">
        <span>Total</span>
        <strong>{{ formatLei(order?.total_bani ?? 0) }} <small>lei</small></strong>
      </div>

      <div class="pay">
        <button type="button" class="primary pay-cash" :disabled="!items.length" @click="emit('pay', 'cash')">
          <Icon name="cash" :size="26" />Numerar<kbd>F8</kbd>
        </button>
        <button type="button" class="dark pay-card" :disabled="!items.length" @click="emit('pay', 'card')">
          <Icon name="card" :size="26" />Card<kbd>F9</kbd>
        </button>
      </div>
    </footer>
  </aside>

  <LineEditor v-if="editing" :item="editing" @close="closeEditor" />

  <AppDialog v-if="buyerOpen" title="Bon pe firmă" @close="closeBuyer">
    <label class="field">
      CUI
      <input ref="buyerCuiInput" v-model="buyerCui" autocomplete="off" placeholder="ex: RO14080700"
             @keydown.enter.prevent="saveBuyer" />
    </label>
    <label class="field">
      Denumire firmă (opțional)
      <input v-model="buyerName" autocomplete="off" @keydown.enter.prevent="saveBuyer" />
    </label>
    <template #actions>
      <button v-if="isCompany" type="button" class="danger" @click="clearBuyer"><Icon name="close" />Fără firmă</button>
      <span class="spacer"></span>
      <button type="button" @click="closeBuyer">Renunță</button>
      <button type="button" class="primary" @click="saveBuyer">Salvează</button>
    </template>
  </AppDialog>

  <AppDialog v-if="confirmingCancel" title="Anulați bonul?" role="alertdialog" @close="confirmingCancel = false">
    <p>Produsele de pe bonul #{{ order?.id }} se scot; nu se tipărește nimic și stocul nu se schimbă.</p>
    <template #actions>
      <button ref="keepButton" type="button" @click="confirmingCancel = false">Nu, păstrează</button>
      <button type="button" class="danger-solid" @click="cancel"><Icon name="trash" />Da, anulează</button>
    </template>
  </AppDialog>
</template>

<style scoped>
.cart {
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-left: 1px solid var(--border);
}

.cart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
}

.cart-head h2 {
  font-size: 1.2rem;
}

.cancel {
  min-height: 44px;
  padding: 0 0.9rem;
}

.lines {
  flex: 1;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}

.lines li {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--border);
}

.lines li.last {
  background: var(--brand-soft);
  box-shadow: inset 4px 0 0 var(--brand);
}

.line {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.15rem 0.75rem;
  align-items: baseline;
  padding: 0.6rem 0.5rem 0.6rem 1rem;
  text-align: left;
  background: transparent;
  border: none;
  border-radius: 0;
}

.line:active:not(:disabled) {
  background: var(--brand-soft);
}

.line-name {
  font-weight: 500;
  overflow-wrap: anywhere;
}

.line-total {
  grid-row: 1 / span 2;
  grid-column: 2;
  align-self: center;
  font-size: 1.05rem;
  font-weight: 600;
}

.line-detail {
  grid-column: 1;
  text-align: left;
  font-size: 0.9rem;
  color: var(--muted);
}

.steppers {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0 0.75rem 0 0.25rem;
}

.step {
  width: var(--touch);
  padding: 0;
  border-radius: 50%;
}

.cart-foot {
  display: grid;
  gap: 0.75rem;
  padding: 0.85rem 1rem 1rem;
  border-top: 1px solid var(--border);
}

.buyer {
  justify-content: flex-start;
  font-size: 0.92rem;
  font-weight: 400;
  text-align: left;
  border-style: dashed;
}

.buyer.company {
  border-style: solid;
  border-color: var(--ink);
}

.total {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 1.1rem;
}

.total strong {
  font-size: 2.3rem;
}

.total small {
  font-size: 1.1rem;
}

.pay {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.6rem;
}

.pay button {
  min-height: 68px;
  font-size: 1.25rem;
  font-weight: 600;
}

kbd {
  padding: 0 0.3rem;
  font-family: inherit;
  font-size: 0.7rem;
  font-weight: 500;
  opacity: 0.75;
  border: 1px solid currentColor;
  border-radius: 4px;
}
</style>
