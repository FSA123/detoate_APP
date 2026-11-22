<script setup>
// Catalogul în Excel: descărcare, și import cu raport pe rânduri (totul sau nimic)
import { ref } from 'vue'

import { api, downloads } from '../api.js'
import Icon from './Icon.vue'

const importing = ref(false)
const imported = ref(null)
const importError = ref(null)

async function importFile(event) {
  const file = event.target.files[0]
  event.target.value = '' // același fișier se poate alege din nou după corectare
  if (!file) return
  importing.value = true
  imported.value = null
  importError.value = null
  try {
    imported.value = await api.importProducts(file)
  } catch (error) {
    importError.value = { message: error.message, rows: error.data?.errors ?? [], count: error.data?.error_count ?? 0 }
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="excel-panel">
    <div class="card actions">
      <div>
        <h3>Descărcați catalogul</h3>
        <p class="muted">Toate produsele, în formatul pe care îl acceptă importul. Modificați-l în Excel și importați-l înapoi.</p>
      </div>
      <a class="button" :href="downloads.products" download><Icon name="download" />Descarcă produse.xlsx</a>
    </div>

    <div class="card actions">
      <div>
        <h3>Importați din Excel sau CSV</h3>
        <p class="muted">
          Doar produse <strong>la bucată</strong> (prețul pe kg se setează în Produse → La kilogram). Obligatorii:
          o coloană cu <strong>denumirea</strong> (Denumire, Denumire Produs…) și una cu <strong>prețul</strong>
          (Preț, Pret Vanzare…); opționale: Cod, Cod de bare, Stoc / Cantitate, Stoc minim, Activ.
        </p>
        <p class="muted">
          Cu coloana Cod, produsele se potrivesc după cod; fără ea, după denumire, iar produsele noi primesc coduri
          1, 2, 3… Cele existente se actualizează, restul rămân neatinse; stocul din fișier contează doar la
          produsele noi. Dacă un rând are o greșeală, nu se importă nimic — corectați rândurile arătate și reîncercați.
        </p>
      </div>
      <label class="button primary" :aria-disabled="importing">
        <Icon name="upload" />{{ importing ? 'Se importă…' : 'Alege fișierul (.xlsx sau .csv)' }}
        <input type="file" accept=".xlsx,.csv" hidden :disabled="importing" @change="importFile" />
      </label>
    </div>

    <div v-if="imported" class="notice ok" role="status">
      <Icon name="check" />
      <div>
        <p>
          <strong>Import reușit:</strong> {{ imported.created }} produse noi, {{ imported.updated }} actualizate,
          {{ imported.unchanged }} neschimbate.
        </p>
        <p v-if="imported.auto_codes">
          Coduri date automat produselor noi:
          {{ imported.auto_codes.count === 1 ? imported.auto_codes.first : `${imported.auto_codes.first}–${imported.auto_codes.last}` }}
          (se văd în lista de produse; la casă se pot tasta).
        </p>
        <p v-if="imported.stock_ignored">
          Stocul din fișier a fost ignorat la {{ imported.stock_ignored }} produse existente — stocul lor se schimbă
          doar prin recepții și ajustări.
        </p>
        <p v-if="imported.ignored_columns.length">Coloane ignorate: {{ imported.ignored_columns.join(', ') }}.</p>
      </div>
    </div>

    <div v-if="importError" class="notice error" role="alert">
      <Icon name="warning" />
      <div>
        <p><strong>{{ importError.message }}</strong></p>
        <table v-if="importError.rows.length" class="data errors">
          <thead><tr><th>Rând</th><th>Problemă</th></tr></thead>
          <tbody>
            <tr v-for="e in importError.rows" :key="`${e.row}-${e.message}`"><td>{{ e.row }}</td><td>{{ e.message }}</td></tr>
          </tbody>
        </table>
        <p v-if="importError.count > importError.rows.length">… și încă {{ importError.count - importError.rows.length }}.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.excel-panel {
  display: grid;
  gap: 1rem;
  max-width: 900px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.actions > div {
  flex: 1 1 360px;
}

.actions h3 {
  margin-bottom: 0.35rem;
}

.errors {
  margin-top: 0.5rem;
  color: var(--ink);
  background: var(--surface);
  border-radius: 8px;
}

.errors td:first-child,
.errors th:first-child {
  width: 4.5rem;
}

.notice > div {
  flex: 1;
}
</style>
