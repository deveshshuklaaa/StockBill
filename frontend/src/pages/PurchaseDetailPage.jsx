import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import { fetchPurchase } from '../api/purchases'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

export default function PurchaseDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [purchase, setPurchase] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showCancel, setShowCancel] = useState(false)
  const [reason, setReason] = useState('')

  function load() {
    fetchPurchase(id)
      .then(setPurchase)
      .catch((err) => setError(apiErrorMessage(err)))
  }

  useEffect(load, [id])

  async function post() {
    setBusy(true); setError('')
    try {
      const { data } = await api.post(`/purchase-invoices/${id}/post/`)
      setPurchase(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally { setBusy(false) }
  }

  async function cancel() {
    if (!reason.trim()) { setError('Enter a cancellation reason.'); return }
    setBusy(true); setError('')
    try {
      const { data } = await api.post(`/purchase-invoices/${id}/cancel/`, { reason: reason.trim() })
      setPurchase(data)
      setShowCancel(false)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally { setBusy(false) }
  }

  if (error && !purchase) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/purchases">Back to purchases</Link></section>
  if (!purchase) return <section className="page-section"><div className="empty-state">Loading purchase...</div></section>

  const isDraft = purchase.state === 'DRAFT'
  const isPosted = purchase.state === 'POSTED'

  return <section className="page-section invoice-detail-page">
    <header className="detail-toolbar">
      <Link className="quiet-button" to="/purchases">← Purchases</Link>
      {isAdmin && purchase.state !== 'CANCELLED' && <div className="detail-actions">
        {isDraft && <button className="primary-button" onClick={post} disabled={busy}>{busy ? 'Receiving...' : 'Post & receive stock'}</button>}
        {isPosted && <button className="quiet-button" style={{ color: 'var(--red)' }} onClick={() => setShowCancel(true)} disabled={busy}>Cancel purchase</button>}
      </div>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showCancel && <div className="record-form">
      <div className="form-heading"><div><p className="eyebrow">Cancellation</p><h2>Cancel purchase {purchase.purchase_number}</h2></div></div>
      <p className="field-help" style={{ marginBottom: 10 }}>Cancellation reverses stock with compensating ledger movements. It is blocked if the goods have already been sold.</p>
      <label className="filter-field" style={{ display: 'block' }}>Reason<textarea style={{ display: 'block', width: '100%', marginTop: 6, border: '1px solid #cbd5cd', padding: '10px 11px', fontFamily: 'inherit', resize: 'vertical' }} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this purchase being cancelled?" /></label>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowCancel(false)}>Keep purchase</button>
        <button type="button" className="primary-button" style={{ background: 'var(--red)' }} onClick={cancel} disabled={busy}>Cancel purchase</button>
      </div>
    </div>}

    <div className="print-sheet">
      <div className="invoice-detail-head">
        <div>
          <p className="eyebrow">Divya Enterprises / Purchase</p>
          <h1>{purchase.purchase_number || `Draft #${purchase.id}`}</h1>
          <p>{purchase.invoice_date}{purchase.posted_at ? ` · posted ${String(purchase.posted_at).slice(0, 10)}` : ''}</p>
        </div>
        <div className="detail-status">
          <span>{purchase.state}</span>
          <strong>{purchase.tax_mode} tax</strong><br />
          <span>Supplier: {purchase.supplier_name}</span>
        </div>
      </div>
      <div className="detail-parties">
        <div>
          <span>Supplier</span>
          <strong>{purchase.supplier_name_snapshot || purchase.supplier_name}</strong>
          <span>{purchase.supplier_gstin_snapshot || 'Unregistered'}</span>
          <span>{purchase.supplier_state_snapshot}{purchase.supplier_state_code_snapshot ? ` (${purchase.supplier_state_code_snapshot})` : ''}</span>
        </div>
        <div>
          <span>Supplier bill</span>
          <strong>{purchase.supplier_invoice_no || '—'}</strong>
          <span>Warehouse: {purchase.warehouse_name}</span>
          {purchase.cancellation_reason && <span style={{ color: 'var(--red)' }}>Cancelled: {purchase.cancellation_reason}</span>}
        </div>
      </div>
      <table className="detail-table">
        <thead><tr><th>Item</th><th>Qty</th><th>Base qty</th><th>Rate</th><th>Disc</th><th>Taxable</th><th>GST</th><th>Total</th><th>Cost/pc</th></tr></thead>
        <tbody>{(purchase.line_items || []).map((line) => <tr key={line.id}>
          <td><strong>{line.product_name_snapshot}</strong><small>HSN: {line.hsn_sac_snapshot || '-'}{line.sku_snapshot ? ` · ${line.sku_snapshot}` : ''}</small></td>
          <td>{line.quantity} {line.purchase_unit_name === 'master box' ? `M.Box (×${Number(line.conversion_factor)})` : line.base_unit_snapshot}</td>
          <td>{line.base_quantity}</td>
          <td>{money(line.rate)}</td>
          <td>{money(line.discount_amount)}</td>
          <td>{money(line.taxable_value)}</td>
          <td>{Number(line.tax_rate).toFixed(0)}%<br /><small>{Number(line.igst_amount) > 0 ? `I:${money(line.igst_amount)}` : `C:${money(line.cgst_amount)} S:${money(line.sgst_amount)}`}</small></td>
          <td>{money(line.line_total)}</td>
          <td><strong>{money(line.unit_cost_snapshot)}</strong></td>
        </tr>)}</tbody>
      </table>
      <div className="detail-total">
        <span>Taxable {money(purchase.taxable_total)} · GST {money(Number(purchase.cgst_total) + Number(purchase.sgst_total) + Number(purchase.igst_total))}</span>
        <strong>{money(purchase.total_amount)}</strong>
      </div>
    </div>
  </section>
}
