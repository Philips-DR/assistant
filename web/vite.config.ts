import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the page is served by Vite, so the server cannot inject the token into it:
// set VITE_ASSISTANT_TOKEN to match ASSISTANT_TOKEN on the server. In production the server
// serves the built page and injects a fresh token itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8750' },
  },
})
