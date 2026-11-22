// Cererile către backend. Erorile ajung ca Error cu mesajul din {"error": ...}
// (deja în română, pentru casier), statusul HTTP în err.status și restul
// răspunsului în err.data (ex. erorile pe rânduri de la importul Excel).

async function request(method, path, body) {
  const init = { method }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  let response
  try {
    response = await fetch(`/api${path}`, init)
  } catch {
    throw new Error('Serverul nu răspunde — verificați că aplicația backend rulează')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(data?.error || `Eroare de server (${response.status})`)
    error.status = response.status
    error.data = data
    throw error
  }
  return data
}

const query = (params) => new URLSearchParams(params).toString()

export const api = {
  fiscalStatus: () => request('GET', '/fiscal/status'),

  products: (params) => request('GET', `/products?${query(params)}`),
  kg: () => request('GET', '/products/kg'),
  updateKg: (fields) => request('PATCH', '/products/kg', fields),
  lookup: (code) => request('GET', `/products/lookup?${query({ code })}`),
  createProduct: (fields) => request('POST', '/products', fields),
  updateProduct: (id, fields) => request('PATCH', `/products/${id}`, fields),
  deleteProduct: (id) => request('DELETE', `/products/${id}`),

  orders: (params) => request('GET', `/orders?${query(params)}`),
  order: (id) => request('GET', `/orders/${id}`),
  createOrder: () => request('POST', '/orders', {}),
  updateOrder: (id, fields) => request('PATCH', `/orders/${id}`, fields),
  cancelOrder: (id) => request('POST', `/orders/${id}/cancel`),
  addItem: (id, body) => request('POST', `/orders/${id}/items`, body),
  updateItem: (id, itemId, fields) => request('PATCH', `/orders/${id}/items/${itemId}`, fields),
  deleteItem: (id, itemId) => request('DELETE', `/orders/${id}/items/${itemId}`),
  pay: (id, body) => request('POST', `/orders/${id}/pay`, body),

  salesReport: (params) => request('GET', `/reports/sales?${query(params)}`),
  fiscalReports: () => request('GET', '/fiscal/reports?limit=30'),
  unreportedTotals: () => request('GET', '/fiscal/unreported'),
  createFiscalReport: (body) => request('POST', '/fiscal/reports', body),
  importProducts(file) {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/excel/products', form)
  },
}

// Fișierele Excel se descarcă direct, printr-un link (aceeași origine)
export const downloads = {
  products: '/api/excel/products',
  sales: (params) => `/api/excel/sales?${query(params)}`,
}
