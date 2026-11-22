<script setup>
// Fereastra comună pentru toate dialogurile: fundal estompat, Esc sau atingere în afară închide
// (dacă nu e `persistent`, de ex. cât timp casa tipărește).
// Focusul: conținutul îl poate alege singur; dacă nu, intră pe prima acțiune (la confirmări,
// cea sigură — „Nu”), ca Enter/Esc să lucreze pe dialogul de deasupra. La închidere se întoarce.
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

defineProps({
  title: { type: String, required: true },
  width: { type: String, default: '440px' },
  persistent: { type: Boolean, default: false },
  role: { type: String, default: 'dialog' },
})
const emit = defineEmits(['close'])

const sheet = ref(null)
const previous = document.activeElement

onMounted(() =>
  nextTick(() => {
    if (!sheet.value || sheet.value.contains(document.activeElement)) return
    // Pe rând, nu ca listă de selectori (aceea ia primul din pagină, adică butonul ×)
    const target = ['.sheet-actions button', 'input, select', 'button']
      .map((selector) => sheet.value.querySelector(selector))
      .find(Boolean)
    target?.focus({ preventScroll: true })
  }),
)

onBeforeUnmount(() => {
  if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true })
})
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click.self="!persistent && emit('close')" @keydown.esc="!persistent && emit('close')">
      <section ref="sheet" class="sheet" :role="role" aria-modal="true" :aria-label="title"
               :style="{ width: `min(${width}, calc(100vw - 2rem))` }">
        <header class="sheet-head">
          <h2>{{ title }}</h2>
          <button v-if="!persistent" type="button" class="ghost close" aria-label="Închide" @click="emit('close')">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>
        <div class="sheet-body">
          <slot />
        </div>
        <footer v-if="$slots.actions" class="sheet-actions">
          <slot name="actions" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgb(28 28 28 / 0.5);
}

.sheet {
  max-height: calc(100vh - 2rem);
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-radius: 20px;
  box-shadow: 0 24px 60px rgb(0 0 0 / 0.3);
}

.sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.1rem 1.25rem 0.5rem 1.4rem;
}

.sheet-head h2 {
  font-size: 1.25rem;
}

.close {
  width: var(--touch);
  padding: 0;
}

.sheet-body {
  display: grid;
  gap: 1rem;
  padding: 0.5rem 1.4rem 1.25rem;
  overflow-y: auto;
}

.sheet-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  padding: 1rem 1.4rem 1.25rem;
  border-top: 1px solid var(--border);
}

.sheet-actions :deep(button) {
  min-width: 120px;
  min-height: 56px;
  font-size: 1.05rem;
}
</style>
