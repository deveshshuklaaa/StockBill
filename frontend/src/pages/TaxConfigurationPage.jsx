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
      <form className="record-form" onSubmit={handleSubmit}>
        <div className="form-heading">
          <div>
            <p className="eyebrow">Tax Configuration</p>
            <h2>{editingId ? 'Edit Tax Rate' : 'New Tax Rate'}</h2>
          </div>
          <button type="button" className="quiet-button" onClick={handleCancel}>Close</button>
        </div>
        <div className="form-grid">
          <label>Name<input type="text" value={formData.name} onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))} required placeholder="e.g. GST 18%" /></label>
          <label>Rate (%)<input type="number" step="0.01" value={formData.rate} onChange={(e) => setFormData((prev) => ({ ...prev, rate: e.target.value }))} required placeholder="e.g. 18.00" /></label>
          <label className="checkbox-label"><input type="checkbox" checked={formData.is_active} onChange={(e) => setFormData((prev) => ({ ...prev, is_active: e.target.checked }))} /> Active</label>
        </div>
        <div className="form-actions">
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? 'Saving...' : editingId ? 'Update' : 'Create'}
          </button>
          <button type="button" className="quiet-button" onClick={handleCancel}>Cancel</button>
        </div>
      </form>
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
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {taxRates.map((rate) => (
                <tr key={rate.id} className={!rate.is_active ? 'archived-row' : ''}>
                  <td><strong>{rate.name}</strong></td>
                  <td style={{ textAlign: 'right' }}>{Number(rate.rate).toFixed(2)}</td>
                  <td>
                    <span className={rate.is_active ? 'badge badge-active' : 'badge badge-archived'}>
                      {rate.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <button className="text-button" onClick={() => handleEdit(rate)}>Edit</button>
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
