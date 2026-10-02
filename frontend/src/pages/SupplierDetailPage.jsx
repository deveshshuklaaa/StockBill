import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import {
  archiveSupplier,
  deleteSupplierPricing,
  fetchSupplier,
  fetchSupplierPricing,
  fetchSupplierPurchases,
  reactivateSupplier,
  saveSupplierPricing,
  updateSupplier,
} from '../api/suppliers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const STATE_BADGE = {
  DRAFT: 'type-chip',
  POSTED: 'tax-chip',
  CANCELLED: 'state-cancelled',
}

export default function SupplierDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [supplier, setSupplier] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [purchases, setPurchases] = useState([])
  const [purchasePage, setPurchasePage] = useState(1)
  const [purchaseTotal, setPurchaseTotal] = useState(0)
  const [purchaseHasNext, setPurchaseHasNext] = useState(false)
  const [purchaseHasPrevious, setPurchaseHasPrevious] = useState(false)
  const [purchasesBusy, setPurchasesBusy] = useState(true)
  const latestHistoryLoad = useRef(0)

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '', contact_info: '', gstin: '', address: '', state: '', state_code: '',
  })

  // Supplier MRP Purchase Pricing state
  const [pricingData, setPricingData] = useState(null)
  const [pricingLoading, setPricingLoading] = useState(true)
  const [pricingDrafts, setPricingDrafts] = useState({})
  const [pricingSaving, setPricingSaving] = useState({})
  const [pricingMsg, setPricingMsg] = useState('')
  const [pricingError, setPricingError] = useState('')
  const [showAddCustomSlab, setShowAddCustomSlab] = useState(false)
  const [customMrp, setCustomMrp] = useState('')
  const [customRate, setCustomRate] = useState('')

  async function loadPricing() {
    setPricingLoading(true)
    try {
      const data = await fetchSupplierPricing(id)
      setPricingData(data)
      const drafts = {}
      ;(data?.pricing || []).forEach((p) => {
        drafts[Number(p.mrp).toFixed(2)] = String(p.rate_per_piece)
      })
      setPricingDrafts(drafts)
    } catch (err) {
      setPricingError(apiErrorMessage(err))
    } finally {
      setPricingLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    setSupplier(null); setError(''); setShowForm(false); setPurchasePage(1)
    fetchSupplier(id)
      .then((data) => {
        if (!cancelled) {
          setSupplier(data)
          loadPricing()
        }
      })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
    return () => { cancelled = true }
  }, [id])

  async function savePricingSlab(mrp, rateValue) {
    const rateNum = Number(rateValue)
    if (!rateNum || rateNum <= 0) {
      setPricingError(`Please enter a valid rate greater than 0 for MRP ₹${Number(mrp).toFixed(2)}.`)
      return
    }
    const mrpStr = Number(mrp).toFixed(2)
    setPricingSaving((prev) => ({ ...prev, [mrpStr]: true }))
    setPricingError('')
    setPricingMsg('')
    try {
      await saveSupplierPricing(id, {
        mrp: Number(mrp),
        rate_per_piece: rateNum,
      })
      setPricingMsg(`Saved rate ₹${rateNum.toFixed(2)}/pc for MRP ₹${mrpStr}.`)
      await loadPricing()
    } catch (err) {
      setPricingError(apiErrorMessage(err))
    } finally {
      setPricingSaving((prev) => ({ ...prev, [mrpStr]: false }))
    }
  }

  async function removePricingSlab(pricingId, mrp) {
    const mrpStr = Number(mrp).toFixed(2)
    setPricingSaving((prev) => ({ ...prev, [mrpStr]: true }))
    setPricingError('')
    setPricingMsg('')
    try {
      await deleteSupplierPricing(id, pricingId)
      setPricingMsg(`Removed pricing for MRP ₹${mrpStr}.`)
      await loadPricing()
    } catch (err) {
      setPricingError(apiErrorMessage(err))
    } finally {
      setPricingSaving((prev) => ({ ...prev, [mrpStr]: false }))
    }
  }

  async function addCustomSlab(e) {
    e.preventDefault()
    if (!customMrp || Number(customMrp) <= 0) {
      setPricingError('Enter a valid MRP greater than 0.')
      return
    }
    if (!customRate || Number(customRate) <= 0) {
      setPricingError('Enter a valid purchase rate per piece greater than 0.')
      return
    }
    await savePricingSlab(customMrp, customRate)
    setCustomMrp('')
    setCustomRate('')
    setShowAddCustomSlab(false)
  }

  // Purchase history is fetched server-scoped: ?supplier=<id> on the
  // existing purchase list endpoint, never filtered client-side.
  useEffect(() => {
    const requestId = ++latestHistoryLoad.current
    setPurchasesBusy(true)
    fetchSupplierPurchases({ supplier: id, page: purchasePage })
      .then((data) => {
        if (requestId !== latestHistoryLoad.current) return
        setPurchases(data.results || [])
        setPurchaseTotal(Number(data.count ?? 0))
        setPurchaseHasNext(Boolean(data.next))
        setPurchaseHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestHistoryLoad.current) return
        if (err?.response?.status === 404 && purchasePage > 1) { setPurchasePage(1); return }
        // Purchase history is admin-only; staff still see supplier info.
        if (err?.response?.status === 403) return
        setError(apiErrorMessage(err))
      })
      .finally(() => {
        if (requestId === latestHistoryLoad.current) setPurchasesBusy(false)
      })
  }, [id, purchasePage])

  function openEditForm() {
    setForm({
      name: supplier.name || '',
      contact_info: supplier.contact_info || '',
      gstin: supplier.gstin || '',
      address: supplier.address || '',
      state: supplier.state || '',
      state_code: supplier.state_code || '',
    })
    setShowForm(true)
  }

  async function submitUpdate(event) {
    event.preventDefault()
    if (!form.name.trim()) { setError('Supplier name is required.'); return }
    setBusy(true); setError('')
    try {
      const updated = await updateSupplier(id, form)
      setSupplier(updated)
      setShowForm(false)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally { setBusy(false) }
  }

  async function handleArchiveToggle() {
    const actionLabel = supplier.is_active ? 'archive' : 'reactivate'
    if (!window.confirm(`Are you sure you want to ${actionLabel} ${supplier.name}?`)) return
    setBusy(true); setError('')
    try {
      const updated = supplier.is_active
        ? await archiveSupplier(id)
        : await reactivateSupplier(id)
      setSupplier(updated)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally { setBusy(false) }
  }

  if (error && !supplier) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/suppliers">Back to suppliers</Link></section>
  if (!supplier) return <section className="page-section"><div className="empty-state">Loading supplier...</div></section>

  const purchasePageSize = 25
  const purchaseTotalPages = Math.max(1, Math.ceil(purchaseTotal / purchasePageSize))

  return <section className="page-section invoice-detail-page">
    <header className="detail-toolbar">
      <Link className="quiet-button" to="/suppliers">← Suppliers</Link>
      <div className="detail-actions">
        {isAdmin && supplier.is_active && !showForm && (
          <button className="secondary-button" onClick={openEditForm} disabled={busy}>Edit supplier</button>
        )}
        {isAdmin && (
          <button className="quiet-button danger" onClick={handleArchiveToggle} disabled={busy}>
            {supplier.is_active ? 'Archive supplier' : 'Reactivate supplier'}
          </button>
        )}
      </div>
    </header>

    <StatusMessage>{error}</StatusMessage>

    {showForm && (
      <form className="record-form" onSubmit={submitUpdate}>
        <div className="form-heading">
          <div>
            <p className="eyebrow">Supplier Master</p>
            <h2>Edit {supplier.name}</h2>
          </div>
        </div>
        <div className="form-grid">
          <label>
            Supplier name
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </label>
          <label>
            Contact info
            <input
              value={form.contact_info}
              onChange={(e) => setForm({ ...form, contact_info: e.target.value })}
              placeholder="Phone, email, or contact person"
            />
          </label>
          <label>
            GSTIN
            <input
              value={form.gstin}
              onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })}
              placeholder="15-character GSTIN"
              maxLength={15}
            />
          </label>
          <label>
            State
            <input
              value={form.state}
              onChange={(e) => setForm({ ...form, state: e.target.value })}
              placeholder="e.g. Maharashtra"
            />
          </label>
          <label>
            State code
            <input
              value={form.state_code}
              onChange={(e) => setForm({ ...form, state_code: e.target.value })}
              placeholder="2-digit code, e.g. 27"
              maxLength={2}
            />
          </label>
        </div>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="full-width">
            Address
            <textarea
              rows={2}
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              placeholder="Registered business address"
            />
          </label>
        </div>
        <div className="form-actions">
          <button type="button" className="quiet-button" onClick={() => setShowForm(false)} disabled={busy}>Cancel</button>
          <button className="primary-button" disabled={busy}>{busy ? 'Saving...' : 'Save changes'}</button>
        </div>
      </form>
    )}

    <div className="detail-card">
      <div className="detail-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0 }}>{supplier.name}</h1>
            <span className={supplier.is_active ? 'tax-chip' : 'type-chip'}>
              {supplier.is_active ? 'Active' : 'Archived'}
            </span>
          </div>
          <p className="field-help" style={{ margin: '6px 0 0' }}>
            {supplier.state ? `${supplier.state}${supplier.state_code ? ` (Code: ${supplier.state_code})` : ''}` : 'No state specified'}
          </p>
        </div>
      </div>

      <div className="detail-meta-grid">
        <div>
          <span>GSTIN</span>
          <strong>{supplier.gstin ? <code>{supplier.gstin}</code> : 'Unregistered'}</strong>
        </div>
        <div>
          <span>Contact</span>
          <strong>{supplier.contact_info || '—'}</strong>
        </div>
        <div>
          <span>Total purchases</span>
          <strong>{purchaseTotal}</strong>
        </div>
        <div>
          <span>Registered address</span>
          <strong className="address-cell">{supplier.address || '—'}</strong>
        </div>
      </div>

      {/* Supplier Purchase Pricing Section (MRP-based) */}
      <div className="supplier-pricing-section" style={{ margin: '28px 0 16px' }} id="supplier-pricing">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <div>
            <p className="eyebrow" style={{ margin: 0 }}>Purchase Rates</p>
            <h2 style={{ fontSize: '1.25rem', margin: '4px 0 0' }}>Supplier MRP Pricing</h2>
          </div>
          {isAdmin && supplier.is_active && (
            <button
              type="button"
              className="quiet-button"
              onClick={() => setShowAddCustomSlab((prev) => !prev)}
              id="btn-toggle-add-pricing"
            >
              {showAddCustomSlab ? 'Cancel' : '+ Add Custom MRP'}
            </button>
          )}
        </div>

        <p style={{ fontSize: '0.875rem', color: '#4b5563', margin: '0 0 12px' }}>
          Configure default purchase rates per piece by MRP slab. <strong>Rate is per piece/base unit.</strong> Products sharing the same MRP automatically receive that rate on purchase entry.
        </p>

        {pricingMsg && (
          <div style={{ padding: '0.5rem 0.75rem', backgroundColor: '#f0fdf4', color: '#166534', borderRadius: '4px', fontSize: '0.85rem', marginBottom: '10px' }}>
            {pricingMsg}
          </div>
        )}
        {pricingError && (
          <div style={{ padding: '0.5rem 0.75rem', backgroundColor: '#fef2f2', color: '#b91c1c', borderRadius: '4px', fontSize: '0.85rem', marginBottom: '10px' }}>
            {pricingError}
          </div>
        )}

        {/* Custom MRP Slab Form (Admin only) */}
        {showAddCustomSlab && isAdmin && supplier.is_active && (
          <form
            onSubmit={addCustomSlab}
            style={{
              display: 'flex',
              gap: '10px',
              alignItems: 'center',
              padding: '12px',
              backgroundColor: '#f9fafb',
              borderRadius: '6px',
              marginBottom: '12px',
              flexWrap: 'wrap',
            }}
          >
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              MRP (₹):
              <input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="e.g. 5.00"
                value={customMrp}
                onChange={(e) => setCustomMrp(e.target.value)}
                style={{ width: '100px' }}
                required
                aria-label="Custom MRP"
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              Rate / Piece (₹):
              <input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="e.g. 3.20"
                value={customRate}
                onChange={(e) => setCustomRate(e.target.value)}
                style={{ width: '100px' }}
                required
                aria-label="Custom rate per piece"
              />
            </label>
            <button type="submit" className="primary-button" style={{ padding: '0.4rem 0.8rem' }} id="btn-save-custom-slab">
              Add Slab
            </button>
          </form>
        )}

        {/* Pricing Table */}
        {pricingLoading ? (
          <div className="empty-state" style={{ padding: '1.5rem' }}>Loading supplier rates...</div>
        ) : !pricingData ? null : (() => {
          const configuredMap = new Map()
          ;(pricingData.pricing || []).forEach((p) => {
            configuredMap.set(Number(p.mrp).toFixed(2), p)
          })

          const allMrpSet = new Set(
            (pricingData.available_mrps || []).map((m) => Number(m).toFixed(2))
          )
          ;(pricingData.pricing || []).forEach((p) => {
            allMrpSet.add(Number(p.mrp).toFixed(2))
          })

          const sortedMrps = Array.from(allMrpSet).sort((a, b) => Number(a) - Number(b))

          if (sortedMrps.length === 0) {
            return (
              <div className="empty-state" style={{ padding: '1.5rem' }}>
                No active MRP slabs found in catalogue.
              </div>
            )
          }

          return (
            <div className="table-scroll" style={{ border: '1px solid #e5e7eb', borderRadius: '6px' }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: '140px' }}>MRP</th>
                    <th style={{ width: '220px' }}>Rate / Piece (₹)</th>
                    <th style={{ width: '130px' }}>Status</th>
                    {isAdmin && <th style={{ textAlign: 'right', width: '180px' }}>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {sortedMrps.map((mrpStr) => {
                    const existing = configuredMap.get(mrpStr)
                    const draftRate =
                      pricingDrafts[mrpStr] !== undefined
                        ? pricingDrafts[mrpStr]
                        : existing?.rate_per_piece || ''
                    const isSaving = Boolean(pricingSaving[mrpStr])
                    const isConfigured = Boolean(existing && existing.is_active)

                    return (
                      <tr key={mrpStr}>
                        <td>
                          <strong>₹{Number(mrpStr).toFixed(2)}</strong>
                        </td>
                        <td>
                          {isAdmin && supplier.is_active ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span>₹</span>
                              <input
                                type="number"
                                step="0.01"
                                min="0.01"
                                value={draftRate}
                                onChange={(e) =>
                                  setPricingDrafts((prev) => ({
                                    ...prev,
                                    [mrpStr]: e.target.value,
                                  }))
                                }
                                placeholder="e.g. 3.20"
                                style={{ width: '120px' }}
                                aria-label={`Rate for MRP ₹${mrpStr}`}
                              />
                              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>/ pc</span>
                            </div>
                          ) : (
                            <span>
                              {isConfigured ? (
                                <strong>₹{Number(existing.rate_per_piece).toFixed(2)} / pc</strong>
                              ) : (
                                <span style={{ color: '#9ca3af' }}>Not configured</span>
                              )}
                            </span>
                          )}
                        </td>
                        <td>
                          {isConfigured ? (
                            <span className="badge badge-configured">Configured</span>
                          ) : existing && !existing.is_active ? (
                            <span className="badge badge-inactive">Inactive</span>
                          ) : (
                            <span className="badge badge-not-set">Not Set</span>
                          )}
                        </td>
                        {isAdmin && (
                          <td style={{ textAlign: 'right' }}>
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                              {supplier.is_active && (
                                <button
                                  type="button"
                                  className="text-button"
                                  disabled={isSaving}
                                  onClick={() => savePricingSlab(mrpStr, draftRate)}
                                  id={`btn-save-pricing-${mrpStr}`}
                                >
                                  {isSaving ? 'Saving...' : existing ? 'Update' : 'Save'}
                                </button>
                              )}
                              {supplier.is_active && existing && (
                                <button
                                  type="button"
                                  className="text-button danger"
                                  disabled={isSaving}
                                  onClick={() => removePricingSlab(existing.id, mrpStr)}
                                  id={`btn-remove-pricing-${mrpStr}`}
                                >
                                  Remove
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
        })()}
      </div>

      <p className="eyebrow" style={{ margin: '26px 0 12px' }}>Purchase history</p>
      {!isAdmin ? <div className="empty-state">Purchase history is available to administrators.</div>
        : purchasesBusy ? <div className="empty-state">Loading purchases...</div>
          : purchases.length === 0 ? <div className="empty-state">No purchases from this supplier yet.</div>
            : <div className="table-scroll"><table>
              <thead><tr><th>Purchase</th><th>Bill no</th><th>Date</th><th>Warehouse</th><th>Total</th><th>Status</th><th aria-label="Actions" /></tr></thead>
              <tbody>{purchases.map((purchase) => <tr key={purchase.id} className={purchase.state === 'CANCELLED' ? 'archived-row' : ''}>
                <td><strong>{purchase.purchase_number || `Draft #${purchase.id}`}</strong></td>
                <td><code>{purchase.supplier_invoice_no || '-'}</code></td>
                <td>{purchase.invoice_date}</td>
                <td>{purchase.warehouse_name}</td>
                <td><strong>{money(purchase.total_amount)}</strong></td>
                <td><span className={STATE_BADGE[purchase.state] || 'type-chip'}>{purchase.state}</span></td>
                <td><Link className="text-button" to={`/purchases/${purchase.id}`}>View Purchase</Link></td>
              </tr>)}</tbody>
            </table></div>}
      {isAdmin && purchases.length > 0 && <div className="table-meta pager" role="navigation" aria-label="Supplier purchase pagination">
        <button className="pager-button" onClick={() => setPurchasePage((c) => Math.max(1, c - 1))} disabled={!purchaseHasPrevious || purchasesBusy}>← Previous</button>
        <span>Page {purchasePage} of {purchaseTotalPages}{purchaseTotal > 0 ? ` · ${purchaseTotal} purchases` : ''}</span>
        <button className="pager-button" onClick={() => setPurchasePage((c) => c + 1)} disabled={!purchaseHasNext || purchasesBusy}>Next →</button>
      </div>}

      <div className="detail-total">
        <span>Purchase history is immutable — supplier master edits never change posted documents.</span>
      </div>
    </div>
  </section>
}
