import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { fetchBusinessProfile, updateBusinessProfile } from '../api/settings'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

export default function BusinessProfilePage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [formData, setFormData] = useState({
    business_name: '',
    trade_name: '',
    gstin: '',
    registered_address: '',
    state: '',
    state_code: '',
    contact_details: '',
  })
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    setBusy(true); setError('')
    fetchBusinessProfile()
      .then((data) => {
        setFormData({
          business_name: data.business_name || '',
          trade_name: data.trade_name || '',
          gstin: data.gstin || '',
          registered_address: data.registered_address || '',
          state: data.state || '',
          state_code: data.state_code || '',
          contact_details: data.contact_details || '',
        })
      })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setBusy(false))
  }, [])

  function handleChange(e) {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(''); setSuccess(''); setSaving(true)
    try {
      await updateBusinessProfile(formData)
      setSuccess('Business profile updated successfully.')
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'updating business profile' }))
    } finally {
      setSaving(false)
    }
  }

  if (!isAdmin) {
    return <section className="page-section">
      <StatusMessage>You do not have permission to view business profile settings.</StatusMessage>
    </section>
  }

  if (busy) {
    return <section className="page-section"><div className="empty-state">Loading business profile...</div></section>
  }

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Settings / Business configuration</p>
        <h1>Business Profile</h1>
        <p className="page-subtitle">GST registration, invoice details, and place of supply configuration.</p>
      </div>
    </header>
    <StatusMessage type={success ? 'success' : 'error'}>{success || error}</StatusMessage>

    <form onSubmit={handleSubmit} className="record-form">
      <div className="form-heading">
        <div>
          <p className="eyebrow">Business Profile</p>
          <h2>Update details</h2>
        </div>
      </div>

      <div className="form-grid">
        <label>Business Name<input name="business_name" value={formData.business_name} onChange={handleChange} required aria-required="true" /></label>
        <label>Trade Name<input name="trade_name" value={formData.trade_name} onChange={handleChange} /></label>
        <label>GSTIN<input name="gstin" value={formData.gstin} onChange={handleChange} required aria-required="true" maxLength={15} placeholder="15-character GST identification number" /></label>
        <label>State<input name="state" value={formData.state} onChange={handleChange} required aria-required="true" /></label>
        <label>State Code<input name="state_code" value={formData.state_code} onChange={handleChange} required aria-required="true" placeholder="e.g. 27" /></label>
        <label className="full-width">Registered Address<textarea name="registered_address" value={formData.registered_address} onChange={handleChange} required rows={3} /></label>
        <label className="full-width">Contact Details<input name="contact_details" value={formData.contact_details} onChange={handleChange} placeholder="Phone, email, or other contact information" /></label>
      </div>

      <div className="form-actions">
        <button type="submit" className="primary-button" disabled={saving}>
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </form>
  </section>
}
