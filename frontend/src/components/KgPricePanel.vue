<script setup>
// Vânzarea la kilogram: un singur preț pe kg pentru orice marfă, plus denumirea
// tipărită pe bon. Se poate schimba oricând; bonurile emise rămân cu prețul lor.
import { onMounted, ref } from 'vue'

import { api } from '../api.js'
import { formatDecimal, formatLei, parseDecimal } from '../money.js'
import Icon from './Icon.vue'

const name = ref('')
const price = ref('')
const current = ref(null)
const busy = ref(false)
const error = ref('')
const saved = ref('')

async function load() {
  try {
    current.value = await api.kg()
    name.value = current.value.name
    price.value = current.value.price_bani ? formatDecimal(current.value.price_bani, 2) : ''
  } catch (e) {
    error.value = e.message
  }
}

async function save() {
  error.value = ''
  saved.value = ''
  const bani = parseDecimal(price.value, 2)
  if (!bani) {
    error.value = 'Preț pe kg: un număr mai mare decât 0, ex. 12,50'
    return
  }
  busy.value = true
  try {
    current.value = await api.updateKg({ name: name.value, price_bani: bani })
    name.value = current.value.name
    price.value = formatDecimal(current.value.price_bani, 2)
    saved.value = `Salvat: „${current.value.name}”, ${formatLei(current.value.price_bani)} lei / kg`
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <form class="card kg-panel" @submit.prevent="save">
    <div class="kg-head">
      <Icon name="weight" :size="26" />
      <div>
        <h3>La kilogram</h3>
        <p class="muted">Un singur preț pe kg, pentru tot ce se vinde la cântar. La casă se tastează doar greutatea.</p>
      </div>
    </div>
    <div class="kg-fields">
      <label class="field">
        Preț (lei / kg)
        <input v-model="price" inputmode="decimal" autocomplete="off" placeholder="ex: 12,50" />
      </label>
      <label class="field">
        Denumire pe bon
        <input v-model="name" autocomplete="off" maxlength="200" />
      </label>
      <button type="submit" class="primary" :disabled="busy">Salvează</button>
    </div>
    <p v-if="current && !current.price_bani" class="notice warn">
      <Icon name="warning" />Prețul pe kg nu e setat: la casă, vânzarea la kilogram e blocată până îl salvați.
    </p>
    <p v-if="saved" class="notice ok" role="status"><Icon name="check" />{{ saved }}</p>
    <p v-if="error" class="field-error" role="alert"><Icon name="warning" />{{ error }}</p>
  </form>
</template>

<style scoped>
.kg-panel {
  display: grid;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.kg-head {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.kg-head > svg {
  flex-shrink: 0;
  color: var(--brand);
}

.kg-head h3,
.kg-head p {
  margin: 0;
}

.kg-head p {
  margin-top: 0.15rem;
}

.kg-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) auto;
  align-items: end;
  gap: 0.75rem;
}

.kg-panel .notice {
  margin: 0;
}
</style>
