// Bani și cantități ca întregi, exact ca în backend (vezi backend/database.py):
// sume în bani, cantități în miimi. Fără float — 19,99 × 100 în float dă
// 1998,9999…, iar asta nu are voie să ajungă pe un bon.

/** 1250, 2 → "12,50"; 1250, 3 → "1,250" — forma pentru câmpurile de editare */
export function formatDecimal(value, decimals) {
  const scale = 10 ** decimals
  const whole = String(Math.floor(value / scale))
  return decimals ? `${whole},${String(value % scale).padStart(decimals, '0')}` : whole
}

/** 123456 → "1.234,56" */
export function formatLei(bani) {
  const [whole, fraction] = formatDecimal(bani, 2).split(',')
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.')},${fraction}`
}

/** Ponderea în total, cu o zecimală: 1350 din 3684 → "36,6%" */
export function formatShare(value, total) {
  if (!total) return '—'
  return `${formatDecimal(Math.round((value * 1000) / total), 1)}%`
}

/** Data locală ca AAAA-LL-ZZ (nu UTC: după miezul nopții, „azi” e ziua magazinului) */
export function localIsoDate(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** "2026-10-19 18:30:01" → "19.10.2026 18:30" */
export function formatDateTime(text) {
  if (!text) return ''
  const [day, time = ''] = text.split(' ')
  return `${day.split('-').reverse().join('.')} ${time.slice(0, 5)}`.trim()
}

/** Cantitatea unei linii: "3 buc" sau "1,250 kg" */
export function formatQuantity(milli, saleType) {
  return saleType === 'unit' ? `${milli / 1000} buc` : `${formatDecimal(milli, 3)} kg`
}

/**
 * Text tastat de casier → întreg scalat: "12,5" cu 2 zecimale → 1250.
 * Virgulă sau punct; mai multe zecimale decât se permit sau orice altceva → null.
 */
export function parseDecimal(text, decimals) {
  const match = String(text).trim().replace(',', '.').match(/^(\d{0,12})(?:\.(\d*))?$/)
  if (!match || (!match[1] && !match[2])) return null
  const fraction = match[2] ?? ''
  if (fraction.length > decimals) return null
  return Number(match[1] || 0) * 10 ** decimals + Number(fraction.padEnd(decimals, '0') || 0)
}

/**
 * O tastă de pe tastatura numerică de pe ecran aplicată textului:
 * '0'–'9', ',', 'back', 'clear'. O tastă care ar face numărul invalid (a treia
 * zecimală la preț, a doua virgulă, prea multe cifre) e ignorată.
 */
export function applyKey(text, key, decimals, maxWholeDigits = 7) {
  const current = String(text).replace('.', ',')
  if (key === 'clear') return ''
  if (key === 'back') return current.slice(0, -1)
  if (key === ',') {
    if (!decimals || current.includes(',')) return current
    return current === '' ? '0,' : `${current},`
  }
  if (!/^[0-9]$/.test(key)) return current
  const [whole, fraction] = current.split(',')
  if (fraction !== undefined) return fraction.length < decimals ? current + key : current
  if (whole === '0') return key // fără zerouri în față: „0” urmat de 5 devine „5”
  return whole.length < maxWholeDigits ? current + key : current
}

/** Totalul liniei, rotunjit ca în backend (routes/orders.line_total_bani) — doar pentru previzualizare */
export function lineTotalBani(quantityMilli, unitPriceBani) {
  return Math.floor((quantityMilli * unitPriceBani + 500) / 1000)
}

/** Prețul după reducere (în sutimi de procent: 10% = 1000), rotunjit comercial — ca backend-ul: 6,99 − 10% → 6,29 */
export function discountedPrice(listPriceBani, discountBp) {
  return Math.floor((listPriceBani * (10000 - discountBp) + 5000) / 10000)
}

/** Reducerea, fără zecimale inutile: 1000 → "10", 1250 → "12,5", 1416 → "14,16" */
export function formatPercent(bp) {
  return formatDecimal(bp, 2).replace(/,?0+$/, '')
}

/**
 * Câmpul de căutare, la Enter: "200", sau cu cantitate în față — "3*200"
 * (3 bucăți din codul 200), "1,250*101" (1,250 kg). Cantitate invalidă → null.
 */
export function parseEntry(text) {
  const star = text.indexOf('*')
  if (star === -1) return { quantityMilli: null, code: text.trim() }
  const quantityMilli = parseDecimal(text.slice(0, star), 3)
  if (!quantityMilli) return null
  return { quantityMilli, code: text.slice(star + 1).trim() }
}
