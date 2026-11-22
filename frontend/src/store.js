import { reactive } from 'vue'

import { api } from './api.js'

// Bonul curent. O singură casă, deci o singură stare, folosită de toate componentele.
export const store = reactive({
  order: null,       // comanda pending de pe ecran; null = bon nou, încă fără produse
  lastItemId: null,  // linia adăugată sau modificată ultima — evidențiată în bon
  error: '',         // ultima eroare, afișată casierului
  // Casa de marcat: mode = simulate | tremol | none | conflict; problem = de ce nu se pot emite bonuri
  fiscal: { mode: null, simulated: false, problem: null },
})

export async function loadFiscalStatus() {
  try {
    store.fiscal = await api.fiscalStatus()
  } catch (error) {
    store.error = error.message
  }
}

// Acțiunile pe bon rulează strict pe rând: la scanări rapide răspunsurile nu
// se pot încurca, iar primul produs nu poate crea două comenzi.
// Fiecare acțiune întoarce rezultatul, sau null dacă a eșuat (eroarea e în store.error).
let queue = Promise.resolve()

function enqueue(action) {
  const run = queue.then(async () => {
    store.error = ''
    try {
      return await action()
    } catch (error) {
      store.error = error.message
      // Comanda a fost plătită sau anulată din altă fereastră — reia bonul curent
      if (error.status === 409) await loadCurrent().catch(() => {})
      return null
    }
  })
  queue = run
  return run
}

async function loadCurrent() {
  const { items } = await api.orders({ status: 'pending', limit: 1 })
  store.order = items.length ? await api.order(items[0].id) : null
}

async function currentOrder() {
  if (!store.order) store.order = await api.createOrder()
  return store.order
}

// Linia nouă sau cea a cărei cantitate s-a schimbat
function changedItem(before, after) {
  const old = new Map((before?.items ?? []).map((i) => [i.id, i.quantity_milli]))
  return after.items.find((i) => old.get(i.id) !== i.quantity_milli)
}

// Reia bonul deschis (la pornire și la întoarcerea pe ecranul casei)
export const loadCurrentOrder = () => enqueue(loadCurrent)

export const addProduct = (product, quantityMilli) =>
  enqueue(async () => {
    const before = await currentOrder()
    const body = { product_id: product.id }
    if (quantityMilli != null) body.quantity_milli = quantityMilli
    store.order = await api.addItem(before.id, body)
    store.lastItemId = changedItem(before, store.order)?.id ?? null
    return store.order
  })

export const updateItem = (itemId, fields) =>
  enqueue(async () => {
    store.order = await api.updateItem(store.order.id, itemId, fields)
    store.lastItemId = itemId
    return store.order
  })

export const removeItem = (itemId) =>
  enqueue(async () => {
    store.order = await api.deleteItem(store.order.id, itemId)
    return store.order
  })

export const setBuyer = (fields) =>
  enqueue(async () => {
    const order = await currentOrder()
    store.order = await api.updateOrder(order.id, fields)
    return store.order
  })

export const cancelOrder = () =>
  enqueue(async () => {
    await api.cancelOrder(store.order.id)
    store.order = null
    return true
  })

export const pay = (method, cashReceivedBani) =>
  enqueue(async () => {
    const body = { payment_method: method }
    if (cashReceivedBani != null) body.cash_received_bani = cashReceivedBani
    const result = await api.pay(store.order.id, body)
    store.order = null
    store.lastItemId = null
    return result
  })
