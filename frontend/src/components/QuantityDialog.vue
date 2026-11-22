<script setup>
import { computed, onMounted, ref } from 'vue'

import { formatLei, lineTotalBani, parseDecimal } from '../money.js'
import AppDialog from './AppDialog.vue'
import NumPad from './NumPad.vue'

const props = defineProps({ product: { type: Object, required: true } })
const emit = defineEmits(['confirm', 'cancel'])

const text = ref('')
const input = ref(null)
const tried = ref(false)

const quantityMilli = computed(() => parseDecimal(text.value, 3))
const preview = computed(() => (quantityMilli.value ? lineTotalBani(quantityMilli.value, props.product.price_bani) : null))

function confirm() {
  tried.value = true
  if (quantityMilli.value) emit('confirm', quantityMilli.value)
}

onMounted(() => input.value.focus())
</script>

<template>
  <AppDialog :title="product.name" width="420px" @close="emit('cancel')">
    <p class="muted">{{ formatLei(product.price_bani) }} lei / kg</p>
    <label class="field">
      Cantitate (kg)
      <input ref="input" v-model="text" class="big-input active" inputmode="none" autocomplete="off" placeholder="0,000"
             @keydown.enter.prevent="confirm" />
    </label>
    <p v-if="preview !== null" class="preview">= {{ formatLei(preview) }} lei</p>
    <p v-else-if="tried" class="field-error">Introduceți cantitatea în kg, ex: 0,750</p>
    <p v-else class="preview muted">&nbsp;</p>
    <NumPad v-model="text" :decimals="3" submit-label="Adaugă" @submit="confirm" />
  </AppDialog>
</template>

<style scoped>
.preview {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  text-align: right;
}
</style>
