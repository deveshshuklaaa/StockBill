import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import {
  fetchWarehouseSummary,
  createWarehouse,
  updateWarehouse,
} from '../api/warehouses'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatQuantity } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

const emptyWarehouse = {
  name: '',
  code: '',
  address: '',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
}

export default function WarehousesPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [warehouses, setWarehouses] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Filter state
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all') // 'all', 'active', 'inactive'

  // Form state
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(emptyWarehouse)
  const [saving, setSaving] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({})

  // Deactivate confirmation state
  const [deactivatingWarehouse, setDeactivatingWarehouse] = useState(null)

  async function loadData() {
    setBusy(true)
    setError('')
    try {
      const data = await fetchWarehouseSummary()
      setWarehouses(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  function beginCreate() {
    setEditingId(null)
    setForm(emptyWarehouse)
    setFieldErrors({})
    setError('')
    setSuccess('')
    setShowForm(true)
  }

  function beginEdit(w) {
    setEditingId(w.id || w.warehouse)
    setForm({
      name: w.name || '',
      code: w.code || '',
      address: w.address || '',
      state: w.state || '',
      state_code: w.state_code || '',
      is_active: w.is_active !== false,
    })
    setFieldErrors({})
    setError('')
    setSuccess('')
    setShowForm(true)
  }

  function handleFormChange(e) {
    const { name, value, type, checked } = e.target
    setForm((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }))
    if (fieldErrors[name]) {
      setFieldErrors((prev) => {
        const next = { ...prev }
        delete next[name]
        return next
      })
    }
  }

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    setFieldErrors({})
    setSuccess('')

    const payload = {
      name: form.name.trim(),
      code: form.code.trim().toUpperCase(),
      address: form.address.trim(),
      state: form.state.trim(),
      state_code: form.state_code.trim(),
      is_active: Boolean(form.is_active),
    }

    try {
      if (editingId) {
        await updateWarehouse(editingId, payload)
        setSuccess(`Warehouse "${payload.name}" updated successfully.`)
      } else {
        await createWarehouse(payload)
        setSuccess(`Warehouse "${payload.name}" created successfully.`)
      }
      setShowForm(false)
      await loadData()
    } catch (err) {
      if (err?.response?.data && typeof err.response.data === 'object') {
        setFieldErrors(err.response.data)
      }
      setError(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function toggleStatus(w) {
    const targetId = w.id || w.warehouse
    const nextStatus = !w.is_active

    if (w.is_active) {
      // Prompt for confirmation before deactivation
      setDeactivatingWarehouse(w)
      return
    }

    // Direct reactivation
    setError('')
    setSuccess('')
    try {
      await updateWarehouse(targetId, { is_active: nextStatus })
      setSuccess(`Warehouse "${w.name}" activated successfully.`)
      await loadData()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  async function confirmDeactivate() {
    if (!deactivatingWarehouse) return
    const targetId = deactivatingWarehouse.id || deactivatingWarehouse.warehouse
    setError('')
    setSuccess('')
    try {
      await updateWarehouse(targetId, { is_active: false })
      setSuccess(`Warehouse "${deactivatingWarehouse.name}" deactivated successfully.`)
      setDeactivatingWarehouse(null)
      await loadData()
    } catch (err) {
      setError(apiErrorMessage(err))
      setDeactivatingWarehouse(null)
    }
  }

  // Filtered warehouses
  const filteredWarehouses = warehouses.filter((w) => {
    const matchesSearch =
      !search ||
      (w.name && w.name.toLowerCase().includes(search.toLowerCase())) ||
      (w.code && w.code.toLowerCase().includes(search.toLowerCase())) ||
      (w.address && w.address.toLowerCase().includes(search.toLowerCase())) ||
      (w.state && w.state.toLowerCase().includes(search.toLowerCase()))

    if (!matchesSearch) return false

    if (statusFilter === 'active') return w.is_active === true
    if (statusFilter === 'inactive') return w.is_active === false
    return true
  })

  const totalValue = warehouses.reduce((sum, w) => sum + Number(w.total_value || 0), 0)
  const totalProducts = warehouses.reduce((sum, w) => sum + Number(w.product_count || 0), 0)
  const activeCount = warehouses.filter((w) => w.is_active !== false).length

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Configuration</p>
          <h1>Warehouses</h1>
          <p className="page-subtitle">
            Manage storage facilities, view inventory valuation, and control active status.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            className="primary-button"
            onClick={beginCreate}
            id="btn-add-warehouse"
          >
            Add Warehouse
          </button>
        )}
      </header>

      <StatusMessage type={error ? 'error' : 'success'}>
        {error || success}
      </StatusMessage>

      {/* Summary Cards */}
      {!busy && warehouses.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '1rem',
            marginBottom: '2rem',
          }}
        >
          <div className="info-card">
            <div className="info-label">Total Warehouses</div>
            <div className="info-value">
              <strong>{warehouses.length}</strong>
              <span style={{ fontSize: '0.85rem', color: '#6b7280', marginLeft: '0.5rem' }}>
                ({activeCount} active)
              </span>
            </div>
          </div>
          <div className="info-card">
            <div className="info-label">Products in Stock</div>
            <div className="info-value">
              <strong>{totalProducts}</strong>
            </div>
          </div>
          <div className="info-card">
            <div className="info-label">Total Inventory Value</div>
            <div className="info-value">
              <strong>{money(totalValue)}</strong>
            </div>
          </div>
        </div>
      )}

      {/* Add / Edit Form Modal / Inline Section */}
      {showForm && isAdmin && (
        <form className="record-form" onSubmit={handleSave} id="warehouse-form">
          <div className="form-heading">
            <div>
              <p className="eyebrow">{editingId ? 'Edit record' : 'New record'}</p>
              <h2>{editingId ? 'Update Warehouse' : 'Add Warehouse'}</h2>
            </div>
            <button
              type="button"
              className="quiet-button"
              onClick={() => setShowForm(false)}
            >
              Close
            </button>
          </div>

          <div className="form-grid">
            <label>
              Warehouse Name *
              <input
                name="name"
                value={form.name}
                onChange={handleFormChange}
                placeholder="e.g. Bhiwandi Central Depot"
                required
                aria-required="true"
              />
              {fieldErrors.name && (
                <span className="field-error" style={{ color: '#ef4444', fontSize: '0.8rem' }}>
                  {Array.isArray(fieldErrors.name) ? fieldErrors.name.join(' ') : fieldErrors.name}
                </span>
              )}
            </label>

            <label>
              Warehouse Code *
              <input
                name="code"
                value={form.code}
                onChange={handleFormChange}
                placeholder="e.g. BHW-01"
                required
                aria-required="true"
              />
              {fieldErrors.code && (
                <span className="field-error" style={{ color: '#ef4444', fontSize: '0.8rem' }}>
                  {Array.isArray(fieldErrors.code) ? fieldErrors.code.join(' ') : fieldErrors.code}
                </span>
              )}
            </label>

            <label>
              State
              <input
                name="state"
                value={form.state}
                onChange={handleFormChange}
                placeholder="e.g. Maharashtra"
              />
              {fieldErrors.state && (
                <span className="field-error" style={{ color: '#ef4444', fontSize: '0.8rem' }}>
                  {Array.isArray(fieldErrors.state) ? fieldErrors.state.join(' ') : fieldErrors.state}
                </span>
              )}
            </label>

            <label>
              State Code
              <input
                name="state_code"
                value={form.state_code}
                onChange={handleFormChange}
                placeholder="e.g. 27"
              />
              {fieldErrors.state_code && (
                <span className="field-error" style={{ color: '#ef4444', fontSize: '0.8rem' }}>
                  {Array.isArray(fieldErrors.state_code) ? fieldErrors.state_code.join(' ') : fieldErrors.state_code}
                </span>
              )}
            </label>

            <label className="full-width">
              Address
              <textarea
                name="address"
                value={form.address}
                onChange={handleFormChange}
                rows={2}
                placeholder="Full physical warehouse address"
              />
              {fieldErrors.address && (
                <span className="field-error" style={{ color: '#ef4444', fontSize: '0.8rem' }}>
                  {Array.isArray(fieldErrors.address) ? fieldErrors.address.join(' ') : fieldErrors.address}
                </span>
              )}
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
              <input
                type="checkbox"
                name="is_active"
                checked={form.is_active}
                onChange={handleFormChange}
              />
              Active warehouse (available for new inventory transactions)
            </label>
          </div>

          <div className="form-actions">
            <button
              type="button"
              className="quiet-button"
              onClick={() => setShowForm(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="primary-button"
              disabled={saving}
              id="btn-save-warehouse"
            >
              {saving ? 'Saving...' : editingId ? 'Update Warehouse' : 'Save Warehouse'}
            </button>
          </div>
        </form>
      )}

      {/* Deactivate Confirmation Modal */}
      {deactivatingWarehouse && (
        <div
          className="modal-backdrop"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            className="modal-content"
            style={{
              backgroundColor: 'white',
              borderRadius: '8px',
              padding: '1.5rem',
              maxWidth: '450px',
              width: '90%',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.2)',
            }}
          >
            <h3 style={{ marginTop: 0, color: '#111827' }}>Deactivate Warehouse?</h3>
            <p style={{ color: '#4b5563', lineHeight: 1.5 }}>
              Are you sure you want to deactivate <strong>{deactivatingWarehouse.name}</strong> (
              <code>{deactivatingWarehouse.code}</code>)?
            </p>
            <p style={{ color: '#6b7280', fontSize: '0.875rem', lineHeight: 1.4 }}>
              Deactivated warehouses will no longer be selectable for new purchases, sales, or opening stock entries. Historical records and stock history will remain intact.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
              <button
                type="button"
                className="quiet-button"
                onClick={() => setDeactivatingWarehouse(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary-button"
                style={{ backgroundColor: '#dc2626', borderColor: '#dc2626' }}
                onClick={confirmDeactivate}
                id="btn-confirm-deactivate"
              >
                Yes, Deactivate
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div
        className="filter-bar"
        style={{
          display: 'flex',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '1rem',
          alignItems: 'center',
        }}
      >
        <div style={{ flex: '1 1 250px' }}>
          <input
            type="search"
            placeholder="Search warehouses by name, code, state..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: '100%' }}
            aria-label="Search warehouses"
          />
        </div>
        <div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label="Filter by status"
          >
            <option value="all">All statuses</option>
            <option value="active">Active only</option>
            <option value="inactive">Inactive only</option>
          </select>
        </div>
      </div>

      {/* Warehouse Table */}
      <div className="table-frame">
        <div className="table-meta">
          <span>
            {busy
              ? 'Loading warehouses...'
              : `${filteredWarehouses.length} warehouse${
                  filteredWarehouses.length === 1 ? '' : 's'
                }${filteredWarehouses.length !== warehouses.length ? ` (filtered from ${warehouses.length})` : ''}`}
          </span>
        </div>

        {busy ? (
          <div className="empty-state">Loading warehouses...</div>
        ) : filteredWarehouses.length === 0 ? (
          <div className="empty-state">
            {search || statusFilter !== 'all'
              ? 'No warehouses match the selected filters.'
              : 'No warehouses configured yet.'}
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Code</th>
                  <th>Location</th>
                  <th>Status</th>
                  <th style={{ textAlign: 'right' }}>Products in Stock</th>
                  <th style={{ textAlign: 'right' }}>Total Quantity</th>
                  <th style={{ textAlign: 'right' }}>Inventory Value</th>
                  {isAdmin && <th style={{ textAlign: 'center' }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {filteredWarehouses.map((warehouse) => {
                  const isActive = warehouse.is_active !== false
                  return (
                    <tr
                      key={warehouse.id || warehouse.warehouse}
                      style={{ opacity: isActive ? 1 : 0.65 }}
                    >
                      <td>
                        <strong>{warehouse.name}</strong>
                      </td>
                      <td>
                        <code>{warehouse.code}</code>
                      </td>
                      <td>
                        {warehouse.address ? (
                          <div>{warehouse.address}</div>
                        ) : null}
                        {warehouse.state && (
                          <div style={{ fontSize: '0.85rem', color: '#6b7280' }}>
                            {warehouse.state} {warehouse.state_code ? `(${warehouse.state_code})` : ''}
                          </div>
                        )}
                        {!warehouse.address && !warehouse.state && (
                          <span style={{ color: '#9ca3af' }}>—</span>
                        )}
                      </td>
                      <td>
                        <span
                          className={`badge ${isActive ? 'badge-success' : 'badge-neutral'}`}
                          style={{
                            padding: '0.2rem 0.5rem',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            backgroundColor: isActive ? '#ecfdf5' : '#f3f4f6',
                            color: isActive ? '#065f46' : '#6b7280',
                          }}
                        >
                          {isActive ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>{warehouse.product_count}</td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQuantity(warehouse.total_quantity, 'piece')}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <strong>{money(warehouse.total_value)}</strong>
                      </td>
                      {isAdmin && (
                        <td style={{ textAlign: 'center' }}>
                          <div
                            style={{
                              display: 'flex',
                              gap: '0.5rem',
                              justifyContent: 'center',
                            }}
                          >
                            <button
                              type="button"
                              className="text-button"
                              onClick={() => beginEdit(warehouse)}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className={`text-button ${isActive ? 'danger' : ''}`}
                              onClick={() => toggleStatus(warehouse)}
                            >
                              {isActive ? 'Deactivate' : 'Activate'}
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
