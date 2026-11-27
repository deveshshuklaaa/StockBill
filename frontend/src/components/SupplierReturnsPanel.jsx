import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { searchPurchaseProducts } from '../api/purchases'
import { createSupplierReturn, fetchSupplierReturns, receiveReplacement } from '../api/supplierReturns'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }
function qty(value) { return Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 3 }) }

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

/**
 * Damaged goods out of the Damaged / Quarantine warehouse back to this
 * supplier, and the 1:1 replacement receipts into Main. Admin-only writes;
 * the list is read-only for staff.
 */
export default function SupplierReturnsPanel({ supplierId, canEdit }) {
  const [returns, setReturns] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [product, setProduct] = useState(null)
  const [form, setForm] = useState({ quantity: '', unit_cost: '', reference: '' })
  const [replacing, setReplacing] = useState(null) // { id, quantity, reference }

  async function load() {
    try {
      setReturns(await fetchSupplierReturns(supplierId))
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  useEffect(() => {
    let active = true
    fetchSupplierReturns(supplierId)
      .then((list) => { if (active) setReturns(list) })
      .catch(() => { if (active) setReturns([]) })
    return () => { active = false }
  }, [supplierId])

  useEffect(() => {
    const query = search.trim()
    if (!query || product) return undefined
    let cancelled = false
    const timer = setTimeout(() => {
      searchPurchaseProducts(query)
        .then(({ data }) => { if (!cancelled) setResults(rows(data).slice(0, 8)) })
        .catch(() => { if (!cancelled) setResults([]) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [search, product])

  async function submitReturn(event) {
    event.preventDefault()
    if (!product) { setError('Choose the product being returned.'); return }
    setBusy(true)
    setError('')
    try {
      const payload = { supplier: Number(supplierId), product: product.id, quantity: form.quantity, reference: form.reference.trim() }
      if (form.unit_cost) payload.unit_cost = form.unit_cost
      await createSupplierReturn(payload)
      setProduct(null)
      setSearch('')
      setForm({ quantity: '', unit_cost: '', reference: '' })
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'recording supplier return' }))
    } finally {
      setBusy(false)
    }
  }

  async function submitReplacement() {
    setBusy(true)
    setError('')
    try {
      await receiveReplacement(replacing.id, { quantity: replacing.quantity, reference: replacing.reference.trim() })
      setReplacing(null)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'recording replacement' }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="record-form" style={{ marginTop: 20 }}>
      <div className="form-heading"><div><p className="eyebrow">Damaged goods</p><h2>Returns for 1:1 replacement</h2></div></div>
      <p className="field-help" style={{ marginBottom: 10 }}>
        Goods leave the Damaged / Quarantine warehouse to this supplier; the replacement is received into Main. Each return is a debit on the supplier ledger and its replacement a credit of the same value, so a full 1:1 replacement nets to zero.
      </p>
      {error && <p className="field-help" role="alert" style={{ color: 'var(--red)', fontSize: 12 }}>{error}</p>}

      {canEdit && (
        <form onSubmit={submitReturn} className="form-grid" style={{ marginBottom: 14 }}>
          <label style={{ position: 'relative' }}>
            Product
            <input
              value={product ? product.name : search}
              onChange={(e) => { setProduct(null); setSearch(e.target.value) }}
              placeholder="Search product..."
              aria-label="Return product"
            />
            {!product && search && results.length > 0 && (
              <div className="suggestion-list">
                {results.map((item) => (
                  <button type="button" key={item.id} onClick={() => { setProduct(item); setResults([]) }}>
                    <strong>{item.name}</strong>
                    <span>{item.mrp != null ? `MRP ₹${Number(item.mrp).toFixed(2)}` : ''}</span>
                  </button>
                ))}
              </div>
            )}
          </label>
          <label>Quantity (pieces)<input type="number" min="0.001" step="any" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} aria-label="Return quantity" required /></label>
          <label>Unit cost (₹, optional)<input type="number" min="0" step="0.01" value={form.unit_cost} onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} placeholder="Last purchase cost" aria-label="Return unit cost" /></label>
          <label>Reference<input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} placeholder="Challan / note no." aria-label="Return reference" /></label>
          <div className="form-actions" style={{ gridColumn: 'span 4', marginTop: 0 }}>
            <button type="submit" className="primary-button" disabled={busy}>Send back to supplier</button>
          </div>
        </form>
      )}

      {replacing && (
        <div className="form-grid" style={{ marginBottom: 14 }}>
          <label>Replacement quantity<input type="number" min="0.001" step="any" value={replacing.quantity} onChange={(e) => setReplacing({ ...replacing, quantity: e.target.value })} aria-label="Replacement quantity" /></label>
          <label style={{ gridColumn: 'span 2' }}>Reference<input value={replacing.reference} onChange={(e) => setReplacing({ ...replacing, reference: e.target.value })} aria-label="Replacement reference" /></label>
          <div className="form-actions" style={{ marginTop: 0 }}>
            <button type="button" className="quiet-button" onClick={() => setReplacing(null)}>Cancel</button>
            <button type="button" className="primary-button" onClick={submitReplacement} disabled={busy}>Receive into Main</button>
          </div>
        </div>
      )}

      <table className="data-table">
        <thead><tr><th>Return</th><th>Date</th><th>Product</th><th>Returned</th><th>Replaced</th><th>Pending</th><th>Value</th><th /></tr></thead>
        <tbody>
          {returns.map((item) => (
            <tr key={item.id}>
              <td>{item.display_number}</td>
              <td>{item.return_date}</td>
              <td>{item.product_name}</td>
              <td>{qty(item.quantity)}</td>
              <td>{qty(item.replaced_quantity)}</td>
              <td>{qty(item.outstanding_quantity)}</td>
              <td>{money(item.value)}</td>
              <td>
                {canEdit && Number(item.outstanding_quantity) > 0 && (
                  <button type="button" className="quiet-button" onClick={() => setReplacing({ id: item.id, quantity: item.outstanding_quantity, reference: '' })}>Receive replacement</button>
                )}
              </td>
            </tr>
          ))}
          {!returns.length && <tr><td colSpan={8} className="empty-state">No damaged-goods returns to this supplier.</td></tr>}
        </tbody>
      </table>
    </section>
  )
}
