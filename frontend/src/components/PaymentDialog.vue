<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { formatDecimal, formatLei, parseDecimal } from '../money.js'
import { pay, store } from '../store.js'
import AppDialog from './AppDialog.vue'
import Icon from './Icon.vue'
import NumPad from './NumPad.vue'

const props = defineProps({ method: { type: String, required: true } })
const emit = defineEmits(['close'])

// Bonul nu se poate modifica cât timp dialogul e deschis, deci totalul e fix
const total = store.order.total_bani
const cash = props.method === 'cash'

const received = ref('')
const busy = ref(false)
const error = ref('')
const result = ref(null)
const receivedInput = ref(null)
const confirmButton = ref(null)
const doneButton = ref(null)

// Câmp gol = suma exactă
const receivedBani = computed(() => (received.value.trim() ? parseDecimal(received.value, 2) : total))
const change = computed(() => (receivedBani.value === null ? null : receivedBani.value - total))
// Bancnotele uzuale peste total — o atingere completează suma primită
const bills = computed(() => [1000, 2000, 5000, 10000, 20000].filter((b) => b > total).slice(0, 4))

watch(received, () => (error.value = ''))

function focusFirst() {
  nextTick(() => (cash ? receivedInput.value : confirmButton.value)?.focus())
}

function setReceived(bani) {
  received.value = formatDecimal(bani, 2)
}

async function submit() {
  if (busy.value) return
  if (result.value) return emit('close')
  if (cash) {
    if (receivedBani.value === null) return (error.value = 'Suma primită nu este un număr valid')
    if (change.value < 0) return (error.value = 'Suma primită este mai mică decât totalul')
  }
  busy.value = true
  error.value = ''
  const paid = await pay(props.method, cash ? receivedBani.value : null)
  busy.value = false
  if (!paid) {
    // Bonul nu s-a emis — comanda rămâne deschisă, plata se poate reîncerca
    error.value = store.error
    store.error = ''
    focusFirst()
    return
  }
  result.value = paid
  await nextTick()
  doneButton.value?.focus()
}

function close() {
  if (!busy.value) emit('close')
}

onMounted(focusFirst)
</script>

<template>
  <AppDialog :title="result ? 'Bon emis' : cash ? 'Plată numerar' : 'Plată cu cardul'" :width="cash && !result ? '780px' : '460px'"
             :persistent="busy" @close="close">
    <template v-if="!result">
      <div :class="{ columns: cash }">
        <div class="amounts">
          <div class="amount">
            <span>De plată</span>
            <strong>{{ formatLei(total) }} lei</strong>
          </div>
          <template v-if="cash">
            <label class="field">
              Primit (lei)
              <input ref="receivedInput" v-model="received" class="big-input active" inputmode="none" autocomplete="off"
                     :placeholder="`${formatDecimal(total, 2)} — exact`" :disabled="busy" @keydown.enter.prevent="submit" />
            </label>
            <div class="bills">
              <button v-for="b in bills" :key="b" type="button" :disabled="busy" @mousedown.prevent @click="setReceived(b)">
                {{ b / 100 }} lei
              </button>
            </div>
            <div class="amount change">
              <span>Rest</span>
              <strong>{{ change !== null && change >= 0 ? formatLei(change) : '—' }} lei</strong>
            </div>
          </template>
          <p v-else class="muted card-hint"><Icon name="card" />Încasați întâi pe terminalul bancar, apoi confirmați aici.</p>
          <p v-if="error" class="field-error" role="alert"><Icon name="warning" />{{ error }}</p>
        </div>
        <NumPad v-if="cash" v-model="received" :decimals="2" submit-label="Emite" @submit="submit" />
      </div>
    </template>

    <template v-else>
      <p class="receipt-number">
        <Icon name="check" :size="28" />Nr. {{ result.order.fiscal_receipt_number }}
        <span v-if="result.order.fiscal_simulated" class="tag warn">simulare — nu s-a tipărit pe casa de marcat</span>
      </p>
      <div v-if="result.change_bani !== null" class="amount change big">
        <span>Rest de dat</span>
        <strong>{{ formatLei(result.change_bani) }} lei</strong>
      </div>
    </template>

    <template #actions>
      <template v-if="!result">
        <button type="button" :disabled="busy" @click="close">Renunță</button>
        <button ref="confirmButton" type="button" class="primary" :disabled="busy" @click="submit">
          {{ busy ? 'Se emite bonul…' : 'Emite bonul' }}
        </button>
      </template>
      <button v-else ref="doneButton" type="button" class="primary" @click="emit('close')">Bon nou</button>
    </template>
  </AppDialog>
</template>

<style scoped>
.columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1.5rem;
}

.amounts {
  display: grid;
  align-content: start;
  gap: 0.9rem;
}

.amount {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
}

.amount strong {
  font-size: 1.6rem;
}

.change strong {
  color: var(--brand-strong);
}

.big strong {
  font-size: 2.6rem;
}

.bills {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.5rem;
}

.card-hint {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.receipt-number {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1.1rem;
  font-weight: 500;
  color: var(--ok);
}
</style>
