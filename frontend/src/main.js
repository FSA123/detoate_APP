import { createApp } from 'vue'

// Poppins (fontul magazinului) inclus în aplicație: casa merge și fără internet.
// Doar latin + latin-ext (ă, â, î, ș, ț sunt în latin-ext).
import '@fontsource/poppins/latin-400.css'
import '@fontsource/poppins/latin-ext-400.css'
import '@fontsource/poppins/latin-500.css'
import '@fontsource/poppins/latin-ext-500.css'
import '@fontsource/poppins/latin-600.css'
import '@fontsource/poppins/latin-ext-600.css'
import '@fontsource/poppins/latin-700.css'
import '@fontsource/poppins/latin-ext-700.css'

import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
