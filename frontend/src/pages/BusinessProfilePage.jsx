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

    <form onSubmit={handleSubmit} style={{ maxWidth: '800px' }}>
      <div style={{ display: 'grid', gap: '1.5rem' }}>
        <label className="form-field">
          <span className="form-label">Business Name <span style={{ color: 'red' }}>*</span></span>
          <input
            type="text"
            name="business_name"
            value={formData.business_name}
            onChange={handleChange}
            required
            className="form-input"
          />
        </label>

        <label className="form-field">
          <span className="form-label">Trade Name</span>
          <input
            type="text"
            name="trade_name"
            value={formData.trade_name}
            onChange={handleChange}
            className="form-input"
          />
        </label>

        <label className="form-field">
          <span className="form-label">GSTIN <span style={{ color: 'red' }}>*</span></span>
          <input
            type="text"
            name="gstin"
            value={formData.gstin}
            onChange={handleChange}
            required
            maxLength={15}
            className="form-input"
            placeholder="15-character GST identification number"
          />
        </label>

        <label className="form-field">
          <span className="form-label">Registered Address <span style={{ color: 'red' }}>*</span></span>
          <textarea
            name="registered_address"
            value={formData.registered_address}
            onChange={handleChange}
            required
            rows={3}
            className="form-input"
          />
        </label>

        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1rem' }}>
          <label className="form-field">
            <span className="form-label">State <span style={{ color: 'red' }}>*</span></span>
            <input
              type="text"
              name="state"
              value={formData.state}
              onChange={handleChange}
              required
              className="form-input"
            />
          </label>

          <label className="form-field">
            <span className="form-label">State Code <span style={{ color: 'red' }}>*</span></span>
            <input
              type="text"
              name="state_code"
              value={formData.state_code}
              onChange={handleChange}
              required
              className="form-input"
              placeholder="e.g. 27"
            />
          </label>
        </div>

        <label className="form-field">
          <span className="form-label">Contact Details</span>
          <input
            type="text"
            name="contact_details"
            value={formData.contact_details}
            onChange={handleChange}
            className="form-input"
            placeholder="Phone, email, or other contact information"
          />
        </label>
      </div>

      <div style={{ marginTop: '2rem', display: 'flex', gap: '1rem' }}>
        <button type="submit" className="primary-button" disabled={saving}>
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </form>
  </section>
}
