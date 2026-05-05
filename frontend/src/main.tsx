import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'
import { useThemeStore } from './store/useThemeStore'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30000, retry: 2 } },
})

// Apply stored theme before first render to avoid flash
useThemeStore.getState().apply()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
)
