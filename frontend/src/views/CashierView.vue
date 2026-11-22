<script setup>
import { nextTick, onActivated, onDeactivated, ref } from 'vue'

import CartPanel from '../components/CartPanel.vue'
import PaymentDialog from '../components/PaymentDialog.vue'
import ProductBrowser from '../components/ProductBrowser.vue'
import QuantityDialog from '../components/QuantityDialog.vue'
import { addProduct, loadCurrentOrder, store } from '../store.js'

const browser = ref(null)
const weighing = ref(null) // produsul la kg pentru care se cere cantitatea
const paying = ref(null)   // 'cash' | 'card' cât timp dialogul de plată e deschis

// Câmpul de căutare primește focusul după fiecare acțiune — scannerul de
// coduri de bare „tastează” acolo
function focusSearch() {
  nextTick(() => browser.value?.focus())
}

async function onPick(product, quantityMilli) {
  if (quantityMilli == null && product.sale_type === 'weight') {
    weighing.value = product
    return
  }
  focusSearch()
  await addProduct(product, quantityMilli)
}

function onWeighed(quantityMilli) {
  const product = weighing.value
  weighing.value = null
  focusSearch()
  addProduct(product, quantityMilli)
}

function closeWeighing() {
  weighing.value = null
  focusSearch()
}

function openPayment(method) {
  if (store.order?.items.length && !weighing.value) paying.value = method
}

function closePayment() {
  paying.value = null
  focusSearch()
}

function onKeydown(event) {
  // Cu un dialog deschis (cântar, plată, linie, firmă), tastele rapide nu deschid altul peste
  if (paying.value || weighing.value || document.querySelector('.overlay')) return
  if (event.key === 'F8' || event.key === 'F9') {
    event.preventDefault()
    openPayment(event.key === 'F8' ? 'cash' : 'card')
  }
}

// Ecranul rămâne în memorie când se schimbă pagina; F8/F9 merg doar pe el
onActivated(() => {
  window.addEventListener('keydown', onKeydown)
  loadCurrentOrder()
  browser.value?.refresh()
  focusSearch()
})
onDeactivated(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <main class="pos">
    <ProductBrowser ref="browser" @pick="onPick" />
    <CartPanel @pay="openPayment" @done="focusSearch" />
  </main>

  <QuantityDialog v-if="weighing" :product="weighing" @confirm="onWeighed" @cancel="closeWeighing" />
  <PaymentDialog v-if="paying" :method="paying" @close="closePayment" />
</template>

<style scoped>
.pos {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 410px;
}

@media (min-width: 1300px) {
  .pos {
    grid-template-columns: minmax(0, 1fr) 460px;
  }
}
</style>
