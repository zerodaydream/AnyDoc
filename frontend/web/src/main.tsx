import '@fontsource-variable/hanken-grotesk'
import '@fontsource-variable/source-serif-4'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { FileDrop } from './features/home/FileDrop'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <FileDrop>
        <App />
      </FileDrop>
    </QueryClientProvider>
  </StrictMode>,
)
