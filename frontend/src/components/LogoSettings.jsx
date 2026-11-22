import { useEffect, useRef, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { deleteBusinessLogo, fetchBusinessLogoBlob, uploadBusinessLogo } from '../api/settings'
import StatusMessage from './StatusMessage'

// Shop logo printed on invoices. Stored in the database (so backups carry
// it); the server validates PNG/JPEG, max 2 MB, and stores a resized PNG.
export default function LogoSettings({ hasLogo: initialHasLogo }) {
  const [hasLogo, setHasLogo] = useState(Boolean(initialHasLogo))
  const [previewUrl, setPreviewUrl] = useState('')
  const [version, setVersion] = useState(0) // bump to reload the preview after a replace
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const fileInput = useRef(null)

  useEffect(() => {
    if (!hasLogo) {
      setPreviewUrl('')
      return undefined
    }
    let active = true
    let url = ''
    fetchBusinessLogoBlob()
      .then((blob) => {
        if (!active) return
        url = URL.createObjectURL(blob)
        setPreviewUrl(url)
      })
      .catch(() => { if (active) setPreviewUrl('') })
    return () => {
      active = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [hasLogo, version])

  async function upload(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setBusy(true); setError(''); setSuccess('')
    try {
      await uploadBusinessLogo(file)
      setHasLogo(true)
      setVersion((v) => v + 1)
      setSuccess('Logo uploaded. It prints on every invoice, including reprints.')
    } catch (err) {
      const detail = err?.response?.data?.logo?.[0]
      setError(detail || apiErrorMessage(err, { action: 'uploading the logo' }))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true); setError(''); setSuccess('')
    try {
      await deleteBusinessLogo()
      setHasLogo(false)
      setSuccess('Logo removed. Invoices print without a logo.')
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'removing the logo' }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="record-form logo-settings" aria-label="Shop logo">
      <div className="form-heading">
        <div>
          <p className="eyebrow">Invoices</p>
          <h2>Shop logo</h2>
        </div>
      </div>
      <StatusMessage type={success ? 'success' : 'error'}>{success || error}</StatusMessage>
      <div className="logo-settings-body">
        <div className="logo-preview">
          {previewUrl
            ? <img src={previewUrl} alt="Current shop logo" />
            : <span>{hasLogo ? 'Loading…' : 'No logo'}</span>}
        </div>
        <div>
          <p className="field-help">PNG or JPEG, up to 2 MB. It is resized to at most 600 px and printed at the top left of every invoice.</p>
          <div className="logo-actions">
            <button type="button" className="primary-button" disabled={busy} onClick={() => fileInput.current?.click()}>
              {busy ? 'Working…' : hasLogo ? 'Replace logo' : 'Upload logo'}
            </button>
            {hasLogo && (
              <button type="button" className="quiet-button" disabled={busy} onClick={remove}>Remove logo</button>
            )}
            <input
              ref={fileInput}
              type="file"
              accept="image/png,image/jpeg"
              aria-label="Logo file"
              onChange={upload}
              style={{ display: 'none' }}
            />
          </div>
        </div>
      </div>
    </section>
  )
}
