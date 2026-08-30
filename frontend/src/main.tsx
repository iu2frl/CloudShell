import ReactDOM from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App.tsx'
import './index.css'
import { initPwa } from './pwa'

initPwa(registerSW)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <App />
)
