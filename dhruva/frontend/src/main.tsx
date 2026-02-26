import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/index.css'

// Cesium Ion token is optional — we use CartoDB Dark tiles by default (no token needed).
// If you have a Cesium Ion token, set VITE_CESIUM_ION_TOKEN in .env for terrain/3D tiles.
import { Ion } from 'cesium';
const token = import.meta.env.VITE_CESIUM_ION_TOKEN;
if (token) {
  Ion.defaultAccessToken = token;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
