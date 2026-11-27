import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// StockBill wordmark font, bundled (the shop laptop may be offline): weight 600 only.
import '@fontsource/space-grotesk/600.css'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
