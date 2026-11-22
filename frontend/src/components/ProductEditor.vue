<script setup>
// Un produs: nou (product = null) sau existent. Stocul nu se modifică aici — doar
// stocul inițial, la creare; recepțiile și ajustările sunt o funcție separată.
// TVA-ul nu se alege: e 21% pentru toate produsele, fix în backend.
import { nextTick, onMounted, ref } from 'vue'

import { api } from '../api.js'
import { formatDecimal, parseDecimal } from '../money.js'
import AppDialog from './AppDialog.vue'
import Icon from './Icon.vue'

const props = defineProps({
  product: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const creating = !props.product
const p = props.product ?? {}
const form = ref({
  code: p.code ?? '',
  barcode: p.barcode ?? '',
  name: p.name ?? '',
  price: p.price_bani == null ? '' : formatDecimal(p.price_bani, 2),
  min_stock_qty: String(p.min_stock_qty ?? 0),
  initial_stock_qty: '',
  active: p.active ?? true,
})
const busy = ref(false)
const error = ref('')
const confirmingDelete = ref(false)
const firstInput = ref(null)


function wholeNumber(text, label) {
  const value = text.trim() === '' ? 0 : Number(text)
  if (!Number.isInteger(value) || value < 0) throw new Error(`${label}: un număr întreg, fără virgulă`)
  return value
}

function payload() {
  const f = form.value
  const price = parseDecimal(f.price, 2)
  if (price === null) throw new Error('Preț: un număr, ex. 12,50')
  const body = {
    code: f.code,
    barcode: f.barcode,
    name: f.name,
    price_bani: price,
    min_stock_qty: wholeNumber(f.min_stock_qty, 'Stoc minim'),
  }
  if (creating) {
    if (f.initial_stock_qty.trim()) body.initial_stock_qty = wholeNumber(f.initial_stock_qty, 'Stoc inițial')
  } else {
    body.active = f.active
  }
  return body
}

async function save() {
  error.value = ''
  let body
  try {
    body = payload()
  } catch (e) {
    error.value = e.message
    return
  }
  busy.value = true
  try {
    const saved = creating ? await api.createProduct(body) : await api.updateProduct(p.id, body)
    emit('saved', creating ? `Produsul „${saved.name}” a fost adăugat` : `Produsul „${saved.name}” a fost salvat`)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function remove() {
  confirmingDelete.value = false
  busy.value = true
  try {
    const result = await api.deleteProduct(p.id)
    emit('saved', result.deleted === 'hard'
      ? `Produsul „${p.name}” a fost șters`
      : `Produsul „${p.name}” are vânzări sau mișcări de stoc, deci a fost dezactivat, nu șters (se poate reactiva)`)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(() => nextTick(() => firstInput.value?.focus()))
</script>

<template>
  <AppDialog :title="creating ? 'Produs nou' : form.name || 'Produs'" width="760px" :persistent="busy" @close="emit('close')">
    <form class="form" @submit.prevent="save">
      <div class="row">
        <label class="field">
          Denumire
          <input ref="firstInput" v-model="form.name" autocomplete="off" maxlength="200" />
        </label>
        <label class="field">
          Preț (lei / bucată)
          <input v-model="form.price" inputmode="decimal" autocomplete="off" placeholder="ex: 12,50" />
        </label>
      </div>
      <div class="row">
        <label class="field">
          Cod (PLU)
          <input v-model="form.code" autocomplete="off" maxlength="32" />
        </label>
        <label class="field">
          Cod de bare (opțional)
          <input v-model="form.barcode" autocomplete="off" maxlength="64" inputmode="numeric" />
        </label>
      </div>
      <div class="row">
        <label class="field">
          Stoc minim (buc) — sub el apare „stoc scăzut”
          <input v-model="form.min_stock_qty" inputmode="numeric" autocomplete="off" />
        </label>
        <label v-if="creating" class="field">
          Stoc inițial (buc, opțional)
          <input v-model="form.initial_stock_qty" inputmode="numeric" autocomplete="off" placeholder="0" />
        </label>
        <div v-else class="field">
          Stoc acum
          <p class="stock">{{ p.stock_qty }} buc</p>
        </div>
      </div>
      <label v-if="!creating" class="field inline">
        <input v-model="form.active" type="checkbox" />
        Activ — apare la casă (un produs inactiv rămâne pe bonurile vechi)
      </label>
      <p v-if="error" class="field-error" role="alert"><Icon name="warning" />{{ error }}</p>
      <button type="submit" hidden></button>
    </form>

    <template #actions>
      <button v-if="!creating" type="button" class="danger" :disabled="busy" @click="confirmingDelete = true">
        <Icon name="trash" />Șterge
      </button>
      <span class="spacer"></span>
      <button type="button" :disabled="busy" @click="emit('close')">Renunță</button>
      <button type="button" class="primary" :disabled="busy" @click="save">{{ creating ? 'Adaugă produsul' : 'Salvează' }}</button>
    </template>
  </AppDialog>

  <AppDialog v-if="confirmingDelete" title="Ștergeți produsul?" role="alertdialog" @close="confirmingDelete = false">
    <p>„{{ p.name }}” dispare din catalog. Dacă a fost vândut sau are mișcări de stoc, doar se dezactivează,
      ca bonurile și rapoartele vechi să rămână corecte.</p>
    <template #actions>
      <button type="button" @click="confirmingDelete = false">Nu</button>
      <button type="button" class="danger-solid" @click="remove"><Icon name="trash" />Da, șterge</button>
    </template>
  </AppDialog>
</template>

<style scoped>
.form {
  display: grid;
  gap: 0.9rem;
}

.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.9rem;
}

.stock {
  display: flex;
  align-items: center;
  min-height: var(--touch);
  margin: 0;
  font-size: 1.05rem;
  color: var(--ink);
}
</style>
