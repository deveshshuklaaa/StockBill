import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api, { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import { cancelInvoice, fetchInvoice, printInvoicePdf } from '../api/invoices'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatQuantity, formatQuantityWithUnit } from '../utils/format'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const STATE_BADGE = {
  DRAFT: 'type-chip',
  POSTED: 'tax-chip',
  CANCELLED: 'state-cancelled',
}

export default function InvoiceDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [invoice, setInvoice] = useState(null)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(null)
  const [showCancel, setShowCancel] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchInvoice(id)
      .then((data) => { if (!cancelled) setInvoice(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
    return () => { cancelled = true }
  }, [id])

  async function handlePrint(copy = 'original') {
    setDownloading(copy)
    setError('')
    try {
      await printInvoicePdf(id, { copy, invoiceNumber: invoice?.invoice_number })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setDownloading(null)
    }
  }

  async function cancel() {
    if (!reason.trim()) { setError('Enter a cancellation reason.'); return }
    setBusy(true)
    setError('')
    try {
      const updated = await cancelInvoice(id, reason.trim())
      setInvoice(updated)
      setShowCancel(false)
      setReason('')
    } catch (err) {
      if (err.response?.status === 403) {
        setError(apiForbiddenMessage(err, 'cancel invoices'))
      } else {
        setError(apiErrorMessage(err, { action: 'cancelling invoice' }))
      }
    } finally {
      setBusy(false)
    }
  }

  if (error && !invoice) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/invoices">Back to invoices</Link></section>
  if (!invoice) return <section className="page-section"><div className="empty-state">Loading invoice...</div></section>

  const isCancelled = invoice.state === 'CANCELLED'
  const isPosted = invoice.state === 'POSTED'
  const totalDiscount = (invoice.line_items || []).reduce((sum, line) => sum + Number(line.discount_amount || 0), 0)
  const totalTaxable = (invoice.line_items || []).reduce((sum, line) => sum + Number(line.taxable_value_snapshot || 0), 0)
  const totalCgst = (invoice.line_items || []).reduce((sum, line) => sum + Number(line.cgst_amount || 0), 0)
  const totalSgst = (invoice.line_items || []).reduce((sum, line) => sum + Number(line.sgst_amount || 0), 0)
  const totalIgst = (invoice.line_items || []).reduce((sum, line) => sum + Number(line.igst_amount || 0), 0)

  return <section className="page-section invoice-detail-page">
    <header className="detail-toolbar">
      <Link className="quiet-button" to="/invoices">← Invoices</Link>
      <div className="detail-actions">
        <button className="quiet-button" onClick={() => handlePrint('original')} disabled={Boolean(downloading)}>
          {downloading === 'original' ? 'Preparing...' : 'Print Original'}
        </button>
        <button className="quiet-button" onClick={() => handlePrint('duplicate')} disabled={Boolean(downloading)}>
          {downloading === 'duplicate' ? 'Preparing...' : 'Print Duplicate'}
        </button>
        <button className="quiet-button" onClick={() => handlePrint('reprint')} disabled={Boolean(downloading)}>
          {downloading === 'reprint' ? 'Preparing...' : 'Reprint'}
        </button>
        {isAdmin && isPosted && <button className="quiet-button" style={{ color: 'var(--red)' }} onClick={() => setShowCancel(true)} disabled={busy}>Cancel invoice</button>}
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showCancel && <div className="record-form">
      <div className="form-heading"><div><p className="eyebrow">Cancellation</p><h2>Cancel invoice {invoice.invoice_number}</h2></div></div>
      <p className="field-help" style={{ marginBottom: 10 }}>Cancellation reverses the stock movement with a compensating SALE_REVERSAL ledger entry. The original sale remains in history and the invoice becomes immutable.</p>
      <label className="filter-field" style={{ display: 'block' }}>Reason<textarea style={{ display: 'block', width: '100%', marginTop: 6, border: '1px solid #cbd5cd', padding: '10px 11px', fontFamily: 'inherit', resize: 'vertical' }} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this invoice being cancelled?" /></label>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowCancel(false)}>Keep invoice</button>
        <button type="button" className="primary-button" style={{ background: 'var(--red)' }} onClick={cancel} disabled={busy}>{busy ? 'Cancelling...' : 'Cancel invoice'}</button>
      </div>
    </div>}

    <div className="print-sheet">
      <div className="invoice-detail-head">
        <div>
          <p className="eyebrow">Divya Enterprises / Invoice</p>
          <h1>{invoice.invoice_number}</h1>
          <p>{invoice.invoice_date}{invoice.created_at ? ` · ${String(invoice.created_at).slice(11, 16)}` : ''}</p>
        </div>
        <div className="detail-status">
          <span className={STATE_BADGE[invoice.state] || 'type-chip'}>{invoice.state}</span>
          <strong>{invoice.payment_type} sale ({invoice.tax_mode})</strong><br />
          <span>Payment: {invoice.payment_status}</span><br />
          <span>Supply: {invoice.place_of_supply || '—'}</span>
        </div>
      </div>
      <div className="detail-parties">
        <div>
          <span>Bill to</span>
          <strong>{invoice.customer_name || 'Walk-in customer'}</strong>
          <span>{invoice.customer_gstin_snapshot || 'Unregistered'}</span>
          <span>{invoice.billing_address_snapshot || ''}</span>
          <span>{invoice.state_snapshot}{invoice.pincode_snapshot ? ` · ${invoice.pincode_snapshot}` : ''}</span>
        </div>
        <div>
          <span>Seller</span>
          <strong>{invoice.seller_business_name_snapshot || 'Divya Enterprises'}</strong>
          <span>{invoice.seller_gstin_snapshot || ''}</span>
          <span>{invoice.seller_address_snapshot || ''}</span>
        </div>
        <div>
          <span>Notes</span>
          <strong>{invoice.notes || '—'}</strong>
          {isCancelled && <span style={{ color: 'var(--red)' }}>Cancelled: {invoice.cancellation_reason}{invoice.cancelled_at ? ` (${String(invoice.cancelled_at).slice(0, 10)})` : ''}</span>}
        </div>
      </div>
      <table className="detail-table">
        <thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Discount</th><th>Taxable</th><th>GST</th><th>Total</th></tr></thead>
        <tbody>{(invoice.line_items || []).map((line) => <tr key={line.id}>
          <td>{line.product_name}<br /><small>HSN: {line.hsn_sac_snapshot || '-'}</small></td>
          <td>
          {formatQuantity(line.quantity, line.sales_unit_name === 'master box' ? 'piece' : (line.base_unit_snapshot || 'piece'))} {line.sales_unit_name === 'master box' ? `M.Box (×${Number(line.conversion_factor)})` : (line.base_unit_snapshot || 'pcs')}
          {line.base_quantity != null && Number(line.conversion_factor || 1) > 1 && (
            <> <br /><small>= {formatQuantityWithUnit(line.base_quantity, line.base_unit_snapshot || 'piece')}</small> </>
          )}
        </td>
          <td>{money(line.rate_charged)}</td>
          <td>{money(line.discount_amount)}</td>
          <td>{money(line.taxable_value_snapshot)}</td>
          <td>{Number(line.tax_rate)}%<br /><small>{Number(line.igst_amount) > 0 ? `I:${money(line.igst_amount)}` : `C:${money(line.cgst_amount)} S:${money(line.sgst_amount)}`}</small></td>
          <td>{money(line.line_total)}</td>
        </tr>)}</tbody>
      </table>
      <div className="detail-total">
        <span>
          Taxable {money(totalTaxable)}
          {totalDiscount > 0 ? ` · Discount ${money(totalDiscount)}` : ''}
          {totalCgst > 0 ? ` · CGST ${money(totalCgst)}` : ''}
          {totalSgst > 0 ? ` · SGST ${money(totalSgst)}` : ''}
          {totalIgst > 0 ? ` · IGST ${money(totalIgst)}` : ''}
        </span>
        <strong>{money(invoice.total_amount)}</strong>
      </div>
      {isCancelled && <p className="field-help" style={{ marginTop: 14 }}>This invoice was cancelled. Stock was restored through a sale-reversal movement; the original sale remains in the ledger.</p>}
    </div>
  </section>
}
