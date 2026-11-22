<script setup>
import { computed, nextTick, onActivated, ref, watch } from 'vue'

import { api, downloads } from '../api.js'
import AppDialog from '../components/AppDialog.vue'
import BarTable from '../components/BarTable.vue'
import Icon from '../components/Icon.vue'
import { formatDateTime, formatLei, formatQuantity, localIsoDate } from '../money.js'
import { store } from '../store.js'

// ─── Vânzări pe perioadă ──────────────────────────────────────────────────────

const today = () => localIsoDate()
const dateFrom = ref(today())
const dateTo = ref(today())
const report = ref(null)
const reportError = ref('')

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return localIsoDate(d)
}

const RANGES = {
  azi: () => [today(), today()],
  ieri: () => [daysAgo(1), daysAgo(1)],
  '7 zile': () => [daysAgo(6), today()],
  'luna aceasta': () => [`${today().slice(0, 8)}01`, today()],
}

function setRange(name) {
  ;[dateFrom.value, dateTo.value] = RANGES[name]()
}

const activeRange = computed(() =>
  Object.keys(RANGES).find((name) => RANGES[name]().join() === [dateFrom.value, dateTo.value].join()),
)

let seq = 0
async function loadSales() {
  const mySeq = ++seq
  try {
    const body = await api.salesReport({ date_from: dateFrom.value, date_to: dateTo.value })
    if (mySeq !== seq) return
    report.value = body
    reportError.value = ''
  } catch (error) {
    if (mySeq === seq) reportError.value = error.message
  }
}

watch([dateFrom, dateTo], () => {
  if (dateFrom.value && dateTo.value) loadSales()
})

const totals = computed(() => report.value?.totals)
const averageBani = computed(() => (totals.value?.receipts ? Math.round(totals.value.total_bani / totals.value.receipts) : 0))
const exportUrl = computed(() => downloads.sales({ date_from: dateFrom.value, date_to: dateTo.value }))

const categoryRows = computed(() =>
  (report.value?.by_category ?? []).map((c) => ({ key: c.sale_type, label: c.name, value: c.total_bani })),
)
const productRows = computed(() =>
  (report.value?.top_products ?? []).map((p) => ({
    key: `${p.product_id}-${p.sale_type}`,
    label: p.name,
    value: p.total_bani,
    detail: formatQuantity(p.quantity_milli, p.sale_type),
  })),
)
const dayRows = computed(() =>
  (report.value?.by_day ?? []).map((d) => ({
    key: d.day,
    label: d.day.split('-').reverse().join('.'),
    value: d.total_bani,
    detail: `${d.receipts} bonuri`,
  })),
)

// ─── Casa de marcat: rapoarte X, Z, memorie fiscală ───────────────────────────

const fiscalLog = ref([])
const unreported = ref(null)
const fiscalBusy = ref('')
const fiscalError = ref('')
const fiscalDone = ref('')
const confirmingZ = ref(false)
const cancelZButton = ref(null)
const fmFrom = ref(`${today().slice(0, 8)}01`)
const fmTo = ref(today())

async function loadFiscal() {
  try {
    const [log, pending] = await Promise.all([api.fiscalReports(), api.unreportedTotals()])
    fiscalLog.value = log.items
    unreported.value = pending
  } catch (error) {
    fiscalError.value = error.message
  }
}

function askZ() {
  confirmingZ.value = true
  nextTick(() => cancelZButton.value?.focus())
}

async function runReport(body, label) {
  confirmingZ.value = false
  fiscalBusy.value = label
  fiscalError.value = ''
  fiscalDone.value = ''
  try {
    const saved = await api.createFiscalReport(body)
    fiscalDone.value = `${label} emis${saved.z_number ? ` — nr. ${saved.z_number}` : ''}${saved.simulated ? ' (simulare, nu s-a tipărit)' : ''}`
    await loadFiscal()
  } catch (error) {
    fiscalError.value = error.message
  } finally {
    fiscalBusy.value = ''
  }
}

function reportName(r) {
  if (r.type === 'period') return `Memorie fiscală ${formatDateTime(r.date_from)} – ${formatDateTime(r.date_to)}`
  return r.type === 'Z' ? `Z nr. ${r.z_number ?? '?'}` : 'X'
}

// Casa raportează alt total decât aplicația: de verificat (vânzări din afara aplicației, bon pierdut)
function deviceMismatch(r) {
  const device = r.details.device
  return device && device.total_bani !== r.total_bani ? device : null
}

onActivated(() => {
  loadSales()
  loadFiscal()
})
</script>

<template>
  <section class="page reports">
    <header class="page-head">
      <h2>Rapoarte</h2>
      <div class="toolbar period">
        <button v-for="(_, name) in RANGES" :key="name" type="button" :class="{ dark: activeRange === name }" @click="setRange(name)">
          {{ name[0].toUpperCase() + name.slice(1) }}
        </button>
        <label class="field inline">De la <input v-model="dateFrom" type="date" :max="dateTo" /></label>
        <label class="field inline">până la <input v-model="dateTo" type="date" :min="dateFrom" /></label>
        <a class="button" :href="exportUrl" download><Icon name="download" />Excel</a>
      </div>
    </header>

    <p v-if="reportError" class="notice error"><Icon name="warning" />{{ reportError }}</p>
    <p v-if="totals?.simulated_receipts" class="notice warn">
      <Icon name="warning" />{{ totals.simulated_receipts }} din {{ totals.receipts }} bonuri sunt simulate — nu există pe casa de marcat.
    </p>

    <div v-if="totals" class="kpis">
      <div class="kpi main">
        <span class="kpi-label">Încasări</span>
        <span class="kpi-value">{{ formatLei(totals.total_bani) }} <small>lei</small></span>
      </div>
      <div class="kpi">
        <span class="kpi-label">Bonuri</span>
        <span class="kpi-value">{{ totals.receipts }}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">Numerar</span>
        <span class="kpi-value">{{ formatLei(totals.cash_bani) }} <small>lei</small></span>
      </div>
      <div class="kpi">
        <span class="kpi-label">Card</span>
        <span class="kpi-value">{{ formatLei(totals.card_bani) }} <small>lei</small></span>
      </div>
      <div class="kpi">
        <span class="kpi-label">Bon mediu</span>
        <span class="kpi-value">{{ formatLei(averageBani) }} <small>lei</small></span>
      </div>
    </div>

    <div v-if="report" class="grid">
      <section class="card">
        <h3>Pe categorii</h3>
        <BarTable v-if="categoryRows.length" :rows="categoryRows" :total="totals.total_bani" label-header="Categorie" />
        <p v-else class="muted">Nicio vânzare în perioada aleasă</p>
      </section>

      <section class="card">
        <h3>TVA</h3>
        <table v-if="totals.receipts" class="data">
          <tbody>
            <tr><td>Încasări, cu TVA</td><td class="num">{{ formatLei(totals.total_bani) }} lei</td></tr>
            <tr><td>din care TVA (21%)</td><td class="num">{{ formatLei(totals.vat_bani) }} lei</td></tr>
            <tr><td>fără TVA</td><td class="num">{{ formatLei(totals.total_bani - totals.vat_bani) }} lei</td></tr>
          </tbody>
        </table>
        <p v-else class="muted">Nicio vânzare în perioada aleasă</p>
        <p class="muted note">TVA calculat de aplicație, orientativ — valoarea oficială e pe raportul Z.</p>
      </section>

      <section class="card wide">
        <h3>Cele mai vândute</h3>
        <BarTable v-if="productRows.length" :rows="productRows" :total="totals.total_bani" label-header="Produs"
                  detail-header="Cantitate" />
        <p v-else class="muted">Nicio vânzare în perioada aleasă</p>
      </section>

      <section v-if="dayRows.length > 1" class="card wide">
        <h3>Pe zile</h3>
        <BarTable :rows="dayRows" :total="totals.total_bani" label-header="Ziua" detail-header="Bonuri" />
      </section>
    </div>

    <section class="card fiscal">
      <h3>Casa de marcat</h3>
      <p class="muted">
        <strong>X</strong> — situația zilei, oricând. <strong>Z</strong> — închide ziua fiscală: o dată pe zi, la
        închidere, și nu se poate anula.
      </p>
      <div class="toolbar fiscal-actions">
        <button type="button" :disabled="!!fiscalBusy || !!store.fiscal.problem" @click="runReport({ type: 'X' }, 'Raport X')">
          <Icon name="printer" />Raport X
        </button>
        <button type="button" class="danger-solid" :disabled="!!fiscalBusy || !!store.fiscal.problem" @click="askZ">
          <Icon name="printer" />Raport Z…
        </button>
        <span class="separator" aria-hidden="true"></span>
        <label class="field inline">Memorie fiscală <input v-model="fmFrom" type="date" :max="fmTo" aria-label="de la" /></label>
        <label class="field inline">– <input v-model="fmTo" type="date" :min="fmFrom" :max="today()" aria-label="până la" /></label>
        <button type="button" :disabled="!!fiscalBusy || !!store.fiscal.problem"
                @click="runReport({ type: 'period', date_from: fmFrom, date_to: fmTo }, 'Raport memorie fiscală')">
          Tipărește
        </button>
      </div>
      <p v-if="store.fiscal.problem" class="notice error"><Icon name="warning" />{{ store.fiscal.problem }}</p>
      <p v-if="fiscalBusy" class="notice warn" role="status"><Icon name="printer" />Se tipărește: {{ fiscalBusy }}…</p>
      <p v-if="fiscalError" class="notice error" role="alert"><Icon name="warning" />{{ fiscalError }}</p>
      <p v-if="fiscalDone" class="notice ok" role="status"><Icon name="check" />{{ fiscalDone }}</p>

      <table v-if="fiscalLog.length" class="data log">
        <thead>
          <tr>
            <th>Data</th><th>Raport</th><th class="num">Bonuri</th><th class="num">Total (lei)</th>
            <th class="num">Numerar</th><th class="num">Card</th><th>Verificare</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in fiscalLog" :key="r.id">
            <td class="num left">{{ formatDateTime(r.created_at) }}</td>
            <td>{{ reportName(r) }} <em v-if="r.simulated" class="tag warn">simulat</em></td>
            <td class="num">{{ r.details.receipts }}</td>
            <td class="num">{{ formatLei(r.total_bani) }}</td>
            <td class="num">{{ formatLei(r.cash_bani) }}</td>
            <td class="num">{{ formatLei(r.card_bani) }}</td>
            <td>
              <span v-if="deviceMismatch(r)" class="mismatch">
                ⚠ casa: {{ formatLei(deviceMismatch(r).total_bani) }} — verificați vânzările făcute direct pe casă
              </span>
              <span v-else-if="r.details.device" class="muted">✓ ca pe casă</span>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Niciun raport emis încă din aplicație.</p>
    </section>

    <AppDialog v-if="confirmingZ" title="Emiteți raportul Z?" role="alertdialog" @close="confirmingZ = false">
      <p>
        Raportul Z <strong>închide ziua fiscală</strong> pe casa de marcat. Nu se poate anula și se face o singură
        dată pe zi, la închidere.
      </p>
      <p v-if="unreported" class="muted z-summary">
        Cuprinde {{ unreported.receipts }} bonuri din aplicație, în total {{ formatLei(unreported.total_bani) }} lei
        (numerar {{ formatLei(unreported.cash_bani) }}, card {{ formatLei(unreported.card_bani) }}).
      </p>
      <template #actions>
        <button ref="cancelZButton" type="button" @click="confirmingZ = false">Renunță</button>
        <button type="button" class="danger-solid" @click="runReport({ type: 'Z' }, 'Raport Z')">
          <Icon name="printer" />Da, emite raportul Z
        </button>
      </template>
    </AppDialog>
  </section>
</template>

<style scoped>
.period .field.inline,
.fiscal-actions .field.inline {
  font-size: 0.9rem;
  color: var(--muted);
}

.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.kpi {
  display: grid;
  gap: 0.2rem;
  padding: 1rem 1.1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
}

.kpi.main {
  border-color: var(--brand);
  box-shadow: inset 0 4px 0 var(--brand);
}

.kpi-label {
  font-size: 0.88rem;
  color: var(--muted);
}

/* Cifre proporționale la valorile mari (Poppins); tabulare doar în coloane */
.kpi-value {
  font-size: 1.7rem;
  font-weight: 600;
}

.kpi-value small {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--muted);
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  margin-bottom: 1rem;
}

@media (max-width: 1000px) {
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.grid .wide {
  grid-column: 1 / -1;
}

.note {
  margin-top: 0.6rem;
  font-size: 0.8rem;
}

.fiscal-actions {
  margin: 0.85rem 0;
}

.separator {
  width: 1px;
  align-self: stretch;
  margin: 0 0.3rem;
  background: var(--border);
}

.log {
  margin-top: 0.5rem;
}

td.left {
  text-align: left;
}

.mismatch {
  font-weight: 600;
  color: var(--warn);
}

.z-summary {
  margin: 0;
}
</style>
