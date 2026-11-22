<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import logo from './assets/logo-white.svg'
import Icon from './components/Icon.vue'
import { loadFiscalStatus, store } from './store.js'
import CashierView from './views/CashierView.vue'
import ProductsView from './views/ProductsView.vue'
import ReceiptsView from './views/ReceiptsView.vue'
import ReportsView from './views/ReportsView.vue'

const PAGES = [
  { id: 'casa', label: 'Casa', icon: 'cash', view: CashierView },
  { id: 'bonuri', label: 'Bonuri', icon: 'receipt', view: ReceiptsView },
  { id: 'produse', label: 'Produse', icon: 'file', view: ProductsView },
  { id: 'rapoarte', label: 'Rapoarte', icon: 'printer', view: ReportsView },
]

// Pagina e în adresă (#/rapoarte), ca un refresh să rămână pe ea
function pageFromHash() {
  const id = location.hash.replace(/^#\/?/, '')
  return PAGES.some((p) => p.id === id) ? id : 'casa'
}

const pageId = ref(pageFromHash())
const page = computed(() => PAGES.find((p) => p.id === pageId.value))

function onHashChange() {
  pageId.value = pageFromHash()
  store.error = ''
}

onMounted(() => {
  window.addEventListener('hashchange', onHashChange)
  loadFiscalStatus()
})
onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))
</script>

<template>
  <header class="topbar">
    <img class="logo" :src="logo" alt="detoate market" />
    <nav class="tabs" aria-label="Pagini">
      <a v-for="p in PAGES" :key="p.id" :href="`#/${p.id}`" :class="{ active: p.id === pageId }"
         :aria-current="p.id === pageId ? 'page' : undefined">
        <Icon :name="p.icon" :size="20" />{{ p.label }}
      </a>
    </nav>
    <p v-if="store.fiscal.simulated" class="status simulated">
      <Icon name="warning" :size="18" />MOD SIMULARE — bonurile nu se tipăresc pe casa de marcat
    </p>
    <p v-else-if="store.fiscal.problem" class="status problem" :title="store.fiscal.problem">
      <Icon name="warning" :size="18" />Casa de marcat nu este configurată — bonurile nu se pot emite
    </p>
  </header>

  <KeepAlive>
    <component :is="page.view" />
  </KeepAlive>

  <!-- mousedown.prevent: atingerea mesajului nu ia focusul din căutare — altfel următoarea scanare s-ar pierde -->
  <div v-if="store.error" class="toast" role="alert" @mousedown.prevent @click="store.error = ''">
    <Icon name="warning" />{{ store.error }}
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  min-height: 64px;
  padding: 0 1rem 0 1.25rem;
  color: #fff;
  background: var(--ink);
}

.logo {
  height: 30px;
  flex-shrink: 0;
}

.tabs {
  display: flex;
  align-self: stretch;
  gap: 0.25rem;
}

.tabs a {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0 1.1rem;
  font-weight: 500;
  color: #c9c9c9;
  text-decoration: none;
  border-bottom: 4px solid transparent;
  border-top: 4px solid transparent;
  touch-action: manipulation;
}

.tabs a.active {
  color: #fff;
  font-weight: 600;
  border-bottom-color: var(--brand);
}

.status {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 0 auto;
  padding: 0.45rem 0.8rem;
  font-size: 0.82rem;
  font-weight: 600;
  border-radius: 10px;
}

.simulated {
  color: var(--warn);
  background: var(--warn-soft);
}

.problem {
  color: #fff;
  background: var(--danger);
}

@media (max-width: 1100px) {
  .status {
    max-width: 260px;
    font-size: 0.75rem;
  }
}
</style>
