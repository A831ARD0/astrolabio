import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'

// El orden importa: los estilos de React Flow primero y los nuestros después,
// para que nuestras reglas ganen. Al contrario, el minimapa sale en blanco.
import '@xyflow/react/dist/style.css'
import './estilos.css'

const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      // Un modelo semántico no cambia solo. Reconsultar al volver a la pestaña
      // sería tirar trabajo sin editar: se reconsulta cuando algo se guarda.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={cliente}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
