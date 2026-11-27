import { useEffect, useState } from 'react'
import api from '../api/client'

// Asks the backend which installation this is (GET /api/meta/) once at app
// start. Outside production it shows a fixed red bar on every screen,
// including login, so a dev or staging copy cannot be mistaken for the
// shop. Hidden when printing; server-generated PDFs never include it.
// Any failure shows nothing: the bar must never break the app.
export const BANNER_CLASS = 'env-banner-on'

export function bannerText(meta) {
  if (!meta?.environment || meta.environment === 'production') return ''
  const parts = [`${meta.environment.toUpperCase()} — test data`]
  if (meta.database) parts.push(meta.database)
  return parts.join(' · ')
}

export default function EnvironmentBanner() {
  const [meta, setMeta] = useState(null)

  useEffect(() => {
    let active = true
    api.get('/meta/')
      .then(({ data }) => { if (active) setMeta(data) })
      .catch(() => { if (active) setMeta(null) })
    return () => { active = false }
  }, [])

  const text = bannerText(meta)

  useEffect(() => {
    if (!text) return undefined
    document.documentElement.classList.add(BANNER_CLASS)
    return () => document.documentElement.classList.remove(BANNER_CLASS)
  }, [text])

  if (!text) return null
  return <div className="env-banner" role="status" aria-label="Environment">{text}</div>
}
