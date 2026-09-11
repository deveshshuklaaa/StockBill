import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { createTaxRate, fetchTaxRates, updateTaxRate } from '../api/settings'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

export default function TaxConfigurationPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [taxRates, setTaxRates] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [formData, setFormData] = useState({ name: '', rate: '', is_active: true })
  const [saving, setSaving] = useState(false)

  async function loadTaxRates() {
    setBusy(true); setError('')
    try {
      const data = await fetchTaxRates()
      setTaxRates(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    loadTaxRates()
  }, [])

  function handleEdit(rate) {
    setEditingId(rate.id)
    setFormData({ name: rate.name, rate: rate.rate, is_active: rate.is_active })
    setShowForm(true)
    setError('')
    setSuccess('')
  }

  function handleCancel() {
    setShowForm(false)
    setEditingId(null)
    setFormData({ name: '', rate: '', is_active: true })
    setError('')
    setSuccess('')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(''); setSuccess(''); setSaving(true)
    try {
      if (editingId) {
        await updateTaxRate(editingId, formData)
        setSuccess('Tax rate updated successfully.')
      } else {
        await createTaxRate(formData)
        setSuccess('Tax rate created successfully.')
      }
      await loadTaxRates()
      handleCancel()
    } catch (err) {
      setError(apiErrorMessage(err, { action: editingId ? 'updating tax rate' : 'creating tax rate' }))
    } finally {
      setSaving(false)
    }
  }

  if (!isAdmin) {
    return <section className="page-section">
      <StatusMessage>You do not have permission to manage tax configuration.</StatusMessage>
    </section>
  }

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Settings / GST configuration</p>
        <h1>Tax Rates</h1>
        <p className="page-subtitle">Manage GST tax rates applied to products and invoices.</p>
      </div>
      {!showForm && <button className="primary-button" onClick={() => setShowForm(true)}>Add Tax Rate</button>}
    </header>
    <StatusMessage type={success ? 'success' : 'error'}>{success || error}</StatusMessage>

    {showForm && (
      <div style={{ marginBottom: '2rem', padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#f9fafb' }}>
        <h2 style={{ marginBottom: '1rem' }}>{editingId ? 'Edit Tax Rate' : 'New Tax Rate'}</h2>
        <form onSubmit={handleSubmit} style={{ maxWidth: '600px' }}>
          <div style={{ display: 'grid', gap: '1rem' }}>
            <label className="form-field">
              <span className="form-label">Name <span style={{ color: 'red' }}>*</span></span>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
                required
                className="form-input"
                placeholder="e.g. GST 18%"
              />
            </label>

            <label className="form-field">
              <span className="form-label">Rate (%) <span style={{ color: 'red' }}>*</span></span>
              <input
                type="number"
                step="0.01"
                value={formData.rate}
                onChange={(e) => setFormData((prev) => ({ ...prev, rate: e.target.value }))}
                required
                className="form-input"
                placeholder="e.g. 18.00"
              />
            </label>

            <label className="form-field" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={formData.is_active}
                onChange={(e) => setFormData((prev) => ({ ...prev, is_active: e.target.checked }))}
              />
              <span className="form-label" style={{ margin: 0 }}>Active</span>
            </label>
          </div>

          <div style={{ marginTop: '1.5rem', display: 'flex', gap: '1rem' }}>
            <button type="submit" className="primary-button" disabled={saving}>
              {saving ? 'Saving...' : editingId ? 'Update' : 'Create'}
            </button>
            <button type="button" className="secondary-button" onClick={handleCancel}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    )}

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading tax rates...' : `${taxRates.length} tax rate${taxRates.length === 1 ? '' : 's'}`}</span>
      </div>
      {busy ? <div className="empty-state">Loading tax rates...</div> : taxRates.length === 0 ? (
        <div className="empty-state">No tax rates configured yet.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th style={{ textAlign: 'right' }}>Rate (%)</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {taxRates.map((rate) => (
                <tr key={rate.id} className={!rate.is_active ? 'archived-row' : ''}>
                  <td><strong>{rate.name}</strong></td>
                  <td style={{ textAlign: 'right' }}>{Number(rate.rate).toFixed(2)}</td>
                  <td>
                    <span className={rate.is_active ? 'tax-chip' : 'state-cancelled'}>
                      {rate.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <button className="secondary-button" onClick={() => handleEdit(rate)} style={{ padding: '0.25rem 0.75rem', fontSize: '0.875rem' }}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  </section>
}
