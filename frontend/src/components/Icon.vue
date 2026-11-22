<script setup>
// Pictograme simple, desenate pe o grilă de 24 px cu linie de 2 px — fără bibliotecă externă
defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 22 },
})

const circle = (cx, cy, r) => `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`

const PATHS = {
  search: `${circle(11, 11, 7)}M16.5 16.5L21 21`,
  close: 'M6 6l12 12M18 6L6 18',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  cash: `M3 6h18v12H3zM${12 - 2.5} 12a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M6 9v.01M18 15v.01`,
  card: 'M3 5h18v14H3zM3 10h18M7 15h4',
  warning: 'M12 3l10 17H2zM12 9v5M12 17v.01',
  check: 'M5 12l5 5 9-10',
  receipt: 'M6 2h12v20l-3-2-3 2-3-2-3 2zM9 7h6M9 11h6M9 15h4',
  edit: 'M4 20h4L19 9l-4-4L4 16zM13 7l4 4',
  backspace: 'M9 5h12v14H9l-7-7zM13 9l5 5M18 9l-5 5',
  company: 'M4 21V5l8-3 8 3v16M9 8h1M14 8h1M9 12h1M14 12h1M10 21v-5h4v5',
  up: 'M6 15l6-6 6 6',
  down: 'M6 9l6 6 6-6',
  download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
  upload: 'M12 20V9M7 14l5-5 5 5M5 4h14',
  file: 'M6 2h9l5 5v15H6zM14 2v6h6',
  info: `${circle(12, 12, 9)}M12 11v6M12 7.5v.01`,
  printer: 'M7 9V3h10v6M7 17H4v-7h16v7h-3M7 14h10v7H7z',
  piece: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
  weight: `${circle(12, 6, 2.5)}M7.5 9.5h9l3.5 10.5H4z`,
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path :d="PATHS[name]" />
  </svg>
</template>
