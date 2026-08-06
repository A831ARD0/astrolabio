import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // El frontend nunca sabe donde vive la API: pide a /api y el proxy lo lleva.
    // Asi el mismo codigo sirve en desarrollo y detras de Caddy en el servidor.
    proxy: {
      '/api': {
        target: process.env.ASTROLABIO_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
