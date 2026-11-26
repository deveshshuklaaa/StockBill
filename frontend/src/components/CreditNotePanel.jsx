import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { createCreditNote } from '../api/invoices'
import { fetchWarehouses } from '../api/warehouses'
import { formatQuantityWithUnit } from '../utils/format'

// Warehouses returned goods may go to, besides the default Main (empty
// selection). Non-sellable ones (Damaged / Quarantine) are offered here on
// purpose: that is where damaged route returns are held for the supplier.
function returnDestinationOptions(warehouses) {
  return (warehouses || []).filter(
    (w) => w.is_active !== false && String(w.code || '').toUpperCase() !== 'MAIN'
  )
}

/**
 * Minimal sales-return (credit note) form for a POSTED invoice.
 * Quantities are in base units (pieces); the server checks they do not
 * exceed what is still un-returned on each line.
 */
export default function CreditNotePanel({ invoice, onCreated, onClose }) {
  const [warehouses, setWarehouses] = useState([])
  const [destination, setDestination] = useState('')
  const [reason, setReason] = useState('')
  const [quantities, setQuantities] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.resolve()
      .then(() => fetchWarehouses({ is_active: 'true' }))
      .then((list) => { if (active) setWarehouses(Array.isArray(list) ? list : []) })
      .catch(() => { if (active) setWarehouses([]) })
    return () => { active = false }
  }, [])

  const options = returnDestinationOptions(warehouses)

  async function submit() {
    const lineItems = (invoice.line_items || [])
      .filter((line) => Number(quantities[line.id] || 0) > 0)
      .map((line) => ({ invoice_line_item: line.id, product: line.product, quantity: Number(quantities[line.id]) }))
    if (!lineItems.length) { setError('Enter a return quantity on at least one line.'); return }
    setBusy(true)
    setError('')
    try {
      const payload = { original_invoice: invoice.id, reason: reason.trim(), line_items: lineItems }
      if (destination) payload.destination_warehouse = Number(destination)
      const note = await createCreditNote(payload)
      onCreated?.(note)
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'creating credit note' }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="record-form" style={{ marginBottom: 16 }}>
      <div className="form-heading"><div><p className="eyebrow">Sales return</p><h2>Issue credit note</h2></div></div>
      {error && <p className="field-help" role="alert" style={{ color: 'var(--red)', fontSize: 12 }}>{error}</p>}
      <table className="data-table" style={{ marginBottom: 12 }}>
        <thead><tr><th>Item</th><th>Billed</th><th>Return qty (pieces)</th></tr></thead>
        <tbody>
          {(invoice.line_items || []).map((line) => (
            <tr key={line.id}>
              <td>{line.product_name}</td>
              <td>{formatQuantityWithUnit(line.base_quantity, line.base_unit_snapshot || 'piece')}</td>
              <td>
                <input
                  type="number"
                  min="0"
                  step="any"
                  max={line.base_quantity}
                  aria-label={`Return quantity for ${line.product_name}`}
                  value={quantities[line.id] ?? ''}
                  onChange={(e) => setQuantities((q) => ({ ...q, [line.id]: e.target.value }))}
                  style={{ width: 110 }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="form-grid">
        <label>
          Returned stock goes to
          <select value={destination} onChange={(e) => setDestination(e.target.value)} aria-label="Return destination warehouse">
            <option value="">Main (default)</option>
            {options.map((w) => (
              <option key={w.id} value={String(w.id)}>
                {w.name} ({w.code}){w.is_sellable === false ? ' — not sellable' : ''}
              </option>
            ))}
          </select>
        </label>
        <label style={{ gridColumn: 'span 3' }}>
          Reason
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Route 1 damaged pile" aria-label="Credit note reason" />
        </label>
      </div>
      <p className="field-help">Damaged goods: choose the Damaged / Quarantine warehouse. They are held there for 1:1 supplier replacement and are not counted as sellable stock.</p>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={onClose}>Close</button>
        <button type="button" className="primary-button" onClick={submit} disabled={busy}>{busy ? 'Saving...' : 'Create credit note'}</button>
      </div>
    </div>
  )
}
