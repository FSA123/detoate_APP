<script setup>
// Linia de pe bon, la atingere: cantitatea și, pe două file, cele două părți ale
// prețului, care se combină: „Modificare preț” (prețul nou, în locul celui din
// catalog) și „Reducere (%)” (din prețul nou, dacă există, altfel din cel din
// catalog). Ex.: 120 lei → preț nou 100 → reducere 30% → 70 lei. Tastatura de pe
// ecran scrie în câmpul atins ultimul. Prețul redus e calculat la fel ca în backend
// (și ca pe casa de marcat).
import { computed, nextTick, onMounted, ref } from 'vue'

import { discountedPrice, formatDecimal, formatLei, formatPercent, lineTotalBani, parseDecimal } from '../money.js'
import { removeItem, store, updateItem } from '../store.js'
import AppDialog from './AppDialog.vue'
import Icon from './Icon.vue'
import NumPad from './NumPad.vue'
import SegmentedControl from './SegmentedControl.vue'

const MAX_PRICE_BANI = 99_999_999 // ca în backend: 999.999,99 lei

const props = defineProps({ item: { type: Object, required: true } })
const emit = defineEmits(['close'])

const byWeight = props.item.sale_type === 'weight'
const manualPrice = props.item.manual_price_bani ?? null // prețul nou salvat; null = cel din catalog
// Prețul la care se aplică reducerea, înainte de modificările din acest dialog
const basePrice = manualPrice ?? props.item.list_price_bani
const quantity = ref(byWeight ? formatDecimal(props.item.quantity_milli, 3) : String(props.item.quantity_milli / 1000))
const discount = ref(props.item.discount_bp ? formatPercent(props.item.discount_bp) : '')
// Gol (prețul de acum, ca indiciu) = prețul nu se schimbă; plin doar dacă linia are deja un preț nou
const price = ref(manualPrice !== null ? formatDecimal(manualPrice, 2) : '')
// Fila deschisă: „Modificare preț” dacă linia are doar un preț nou, altfel „Reducere (%)”
const mode = ref(manualPrice !== null && !props.item.discount_bp ? 'price' : 'discount')
const modes = [
  { value: 'discount', label: 'Reducere (%)' },
  { value: 'price', label: 'Modificare preț' },
]
const active = ref('quantity')
const quantityInput = ref(null)
const discountInput = ref(null)
const priceInput = ref(null)
const inputs = { quantity: quantityInput, discount: discountInput, price: priceInput }
const texts = { quantity, discount, price }

const keypadText = computed({
  get: () => texts[active.value].value,
  set: (value) => (texts[active.value].value = value),
})
const keypadDecimals = computed(() => (active.value === 'quantity' ? (byWeight ? 3 : 0) : 2))
const quantityMilli = computed(() => parseDecimal(quantity.value, 3))
// Gol = fără reducere; în sutimi de procent: 12,5% → 1250
const discountBp = computed(() => (discount.value.trim() === '' ? 0 : parseDecimal(discount.value, 2)))
const discountValid = computed(() => discountBp.value !== null && discountBp.value <= 9999)
const priceEmpty = computed(() => price.value.trim() === '')
const priceBani = computed(() => parseDecimal(price.value, 2))
const priceValid = computed(() => priceBani.value !== null && priceBani.value >= 1 && priceBani.value <= MAX_PRICE_BANI)
// Prețul pe care îl va avea linia după „Salvează”: prețul nou (sau cel de până acum) minus reducerea
const unitPrice = computed(() => {
  if (!discountValid.value || (!priceEmpty.value && !priceValid.value)) return null
  return discountedPrice(priceEmpty.value ? basePrice : priceBani.value, discountBp.value)
})
const preview = computed(() =>
  quantityMilli.value && unitPrice.value !== null ? lineTotalBani(quantityMilli.value, unitPrice.value) : null,
)

function activate(field) {
  active.value = field
  nextTick(() => inputs[field].value?.select())
}

function switchMode(value) {
  mode.value = value
  activate(value)
}

async function save() {
  if (!quantityMilli.value) return (store.error = 'Cantitate invalidă')
  // Ambele părți ale prețului se salvează împreună; întâi eroarea din fila deschisă
  const priceError = !priceEmpty.value && !priceValid.value ? 'Preț nou: o sumă în lei, ex. 4,50' : ''
  const discountError = discountValid.value ? '' : 'Reducere: un procent între 0 și 99,99, ex. 10 sau 12,5'
  const error = mode.value === 'price' ? priceError || discountError : discountError || priceError
  if (error) return (store.error = error)
  const fields = {}
  if (quantityMilli.value !== props.item.quantity_milli) fields.quantity_milli = quantityMilli.value
  if (!priceEmpty.value && priceBani.value !== manualPrice) fields.manual_price_bani = priceBani.value
  if (discountBp.value !== props.item.discount_bp) fields.discount_bp = discountBp.value
  if (Object.keys(fields).length && !(await updateItem(props.item.id, fields))) return
  emit('close')
}

// Înapoi la prețul din catalog: fără preț nou și fără reducere
async function catalogPrice() {
  if (await updateItem(props.item.id, { manual_price_bani: null, discount_bp: 0 })) emit('close')
}

async function remove() {
  if (await removeItem(props.item.id)) emit('close')
}

onMounted(() => activate('quantity'))
</script>

<template>
  <AppDialog :title="item.product_name" width="760px" @close="emit('close')">
    <div class="columns">
      <div class="fields">
        <label class="field">
          Cantitate ({{ byWeight ? 'kg' : 'bucăți' }})
          <input id="edit-qty" ref="quantityInput" v-model="quantity" class="big-input"
                 :class="{ active: active === 'quantity' }" inputmode="none" autocomplete="off"
                 @focus="active = 'quantity'" @keydown.enter.prevent="save" />
        </label>
        <SegmentedControl :model-value="mode" :options="modes" label="Prețul liniei" @update:model-value="switchMode" />
        <label v-if="mode === 'discount'" class="field">
          Reducere (%)
          <input id="edit-discount" ref="discountInput" v-model="discount" class="big-input"
                 :class="{ active: active === 'discount' }" inputmode="none" autocomplete="off" placeholder="0"
                 @focus="active = 'discount'" @keydown.enter.prevent="save" />
        </label>
        <label v-else class="field">
          Preț nou (lei / {{ byWeight ? 'kg' : 'buc' }})
          <input id="edit-price" ref="priceInput" v-model="price" class="big-input"
                 :class="{ active: active === 'price' }" inputmode="none" autocomplete="off"
                 :placeholder="formatDecimal(basePrice, 2)"
                 @focus="active = 'price'" @keydown.enter.prevent="save" />
        </label>
        <p class="muted price">
          Preț din catalog{{ byWeight ? ' / kg' : '' }}: {{ formatLei(item.list_price_bani) }} lei
          <template v-if="unitPrice !== null && unitPrice !== item.list_price_bani">
            → <strong>{{ formatLei(unitPrice) }} lei</strong>
          </template>
        </p>
        <p class="line-total">Total linie: <strong>{{ preview === null ? '—' : `${formatLei(preview)} lei` }}</strong></p>
      </div>
      <NumPad v-model="keypadText" :decimals="keypadDecimals" submit-label="Salvează" @submit="save" />
    </div>
    <template #actions>
      <button type="button" class="danger" @click="remove"><Icon name="trash" />Șterge linia</button>
      <button v-if="item.price_overridden" type="button" @click="catalogPrice">Preț din catalog</button>
      <span class="spacer"></span>
      <button type="button" @click="emit('close')">Renunță</button>
      <button type="button" class="primary" @click="save">Salvează</button>
    </template>
  </AppDialog>
</template>

<style scoped>
.columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1.25rem;
}

.fields {
  display: grid;
  align-content: start;
  gap: 0.9rem;
}

.line-total {
  margin: 0;
  font-size: 1.1rem;
}
</style>
