<script setup>
// Tastatura numerică de pe ecran, pentru casa tactilă. Editează un text (v-model)
// prin applyKey; mousedown.prevent: atingerea unei taste nu ia focusul din câmp,
// deci tastatura fizică și cântarul/scannerul merg în paralel.
import { applyKey } from '../money.js'

const props = defineProps({
  modelValue: { type: String, required: true },
  decimals: { type: Number, default: 2 },
  submitLabel: { type: String, default: 'OK' },
})
const emit = defineEmits(['update:modelValue', 'submit'])

function press(key) {
  emit('update:modelValue', applyKey(props.modelValue, key, props.decimals))
}
</script>

<template>
  <div class="numpad" role="group" aria-label="Tastatură numerică">
    <button v-for="d in ['7', '8', '9']" :key="d" type="button" @mousedown.prevent @click="press(d)">{{ d }}</button>
    <button type="button" class="action" aria-label="Șterge ultima cifră" @mousedown.prevent @click="press('back')">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M9 5h12v14H9l-7-7zM13 9l5 5M18 9l-5 5" />
      </svg>
    </button>
    <button v-for="d in ['4', '5', '6']" :key="d" type="button" @mousedown.prevent @click="press(d)">{{ d }}</button>
    <button type="button" class="action" aria-label="Golește" @mousedown.prevent @click="press('clear')">C</button>
    <button v-for="d in ['1', '2', '3']" :key="d" type="button" @mousedown.prevent @click="press(d)">{{ d }}</button>
    <button type="button" class="primary ok" @mousedown.prevent @click="emit('submit')">{{ submitLabel }}</button>
    <button v-if="decimals" type="button" aria-label="Virgulă" @mousedown.prevent @click="press(',')">,</button>
    <button type="button" :class="{ wide: !decimals }" @mousedown.prevent @click="press('0')">0</button>
  </div>
</template>

<style scoped>
.numpad {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-auto-rows: 60px;
  gap: 0.5rem;
}

.numpad button {
  min-height: 0;
  padding: 0;
  font-size: 1.5rem;
  font-weight: 500;
  border-radius: 14px;
}

.action {
  font-size: 1.15rem;
  color: var(--muted);
  background: var(--bg);
}

.ok {
  grid-row: span 2;
  font-size: 1.2rem;
}

.wide {
  grid-column: span 2;
}
</style>
