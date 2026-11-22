<script setup>
// Alegere între câteva opțiuni (categoria produsului, sub-pagini), cu butoane mari pentru ecran tactil
defineProps({
  modelValue: { type: [String, Number, Boolean], default: null },
  options: { type: Array, required: true }, // [{ value, label }]
  label: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="segmented" role="group" :aria-label="label">
    <button
      v-for="o in options"
      :key="String(o.value)"
      type="button"
      :class="{ on: o.value === modelValue }"
      :aria-pressed="o.value === modelValue"
      @click="emit('update:modelValue', o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>

<style scoped>
.segmented {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 14px;
}

.segmented button {
  min-height: 44px;
  padding: 0 1.1rem;
  border: none;
  border-radius: 10px;
  background: transparent;
}

.segmented button.on {
  color: #fff;
  font-weight: 600;
  background: var(--ink);
}
</style>
