import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import { fetchCustomer, fetchCustomerReport, recordPayment, reversePayment } from '../api/customers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const STATE_BADGE = {
  DRAFT: 'type-chip',
  POSTED: 'tax-chip',
  CANCELLED: 'state-cancelled',
}

const PAYMENT_STATUS_BADGE = {
  paid: 'tax-chip',
  credit: 'balance due',
  partially_paid: 'balance due',
}

const PAYMENT_METHODS = [
  ['cash', 'Cash'],
  ['upi', 'UPI'],
  ['bank', 'Bank Transfer'],
  ['card', 'Card'],
  ['cheque', 'Cheque'],
]

const STATEMENT_TYPE_LABELS = {
  OPENING: 'Opening Balance',
  INVOICE: 'Invoice',
  PAYMENT: 'Payment',
  PAYMENT_REVERSAL: 'Payment Reversal',
  CREDIT_NOTE: 'Credit Note',
  DEBIT_NOTE: 'Debit Note',
}

export default function CustomerDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [customer, setCustomer] = useState(null)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [showPaymentForm, setShowPaymentForm] = useState(false)
  const [paymentAmount, setPaymentAmount] = useState('')
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [paymentReference, setPaymentReference] = useState('')
  const [paymentNotes, setPaymentNotes] = useState('')
  const [paymentInvoice, setPaymentInvoice] = useState('')
  const [reversingId, setReversingId] = useState(null)
  const [reversalAmount, setReversalAmount] = useState('')
  const [reversalReason, setReversalReason] = useState('')

  useEffect(() => {
    let cancelled = false
    setCustomer(null); setReport(null); setError(''); setShowPaymentForm(false)
    fetchCustomer(id)
      .then((data) => { if (!cancelled) setCustomer(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
    fetchCustomerReport(id)
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
    return () => { cancelled = true }
  }, [id])

  async function refreshReport() {
    try {
      const data = await fetchCustomerReport(id)
      setReport(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  async function submitPayment(event) {
    event.preventDefault()
    if (!paymentAmount || Number(paymentAmount) <= 0) { setError('Enter a payment amount greater than zero.'); return }
    setBusy(true); setError('')
    try {
      await recordPayment({
        customer: Number(id),
        invoice: paymentInvoice ? Number(paymentInvoice) : null,
        amount: paymentAmount,
        paymentMethod,
        referenceNumber: paymentReference.trim(),
        notes: paymentNotes.trim(),
      })
      setShowPaymentForm(false)
      setPaymentAmount(''); setPaymentReference(''); setPaymentNotes(''); setPaymentInvoice('')
      await refreshReport()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally { setBusy(false) }
  }

  async function submitReversal() {
    if (!reversalAmount || Number(reversalAmount) <= 0) { setError('Enter a reversal amount greater than zero.'); return }
    if (!reversalReason.trim()) { setError('Enter a reversal reason.'); return }
    setBusy(true); setError('')
    try {
      await reversePayment(reversingId, reversalAmount, reversalReason.trim())
      setReversingId(null); setReversalAmount(''); setReversalReason('')
      await refreshReport()
    } catch (err) {
      setError(apiForbiddenMessage(err, 'reverse payments', 'reversing payment'))
    } finally { setBusy(false) }
  }

  if (error && !customer) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/customers">Back to customers</Link></section>
  if (!customer) return <section className="page-section"><div className="empty-state">Loading customer...</div></section>

  const invoices = report?.invoices || []
  const payments = report?.payments || []
  const statement = report?.statement || []
  const outstanding = report ? report.outstanding_balance : customer.outstanding_balance
  const availableCredit = report ? report.available_credit : customer.available_credit
  const openInvoices = invoices.filter((invoice) => invoice.state === 'POSTED' && invoice.payment_status !== 'paid')

  return <section className="page-section invoice-detail-page">
    <header className="detail-toolbar">
      <Link className="quiet-button" to="/customers">← Customers</Link>
      <div className="detail-actions">
        <button className="primary-button" onClick={() => setShowPaymentForm((v) => !v)} disabled={busy}>{showPaymentForm ? 'Close payment form' : 'Record payment'}</button>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showPaymentForm && <form className="record-form" onSubmit={submitPayment}>
      <div className="form-heading"><div><p className="eyebrow">Receipt</p><h2>Record payment for {customer.name}</h2></div></div>
      <p className="field-help" style={{ marginBottom: 10 }}>Payments are append-only. A mistake requires a reversal; records are never edited or deleted.</p>
      <div className="form-grid">
        <label>Amount<input type="number" min="0.01" step="0.01" value={paymentAmount} onChange={(e) => setPaymentAmount(e.target.value)} aria-required="true" placeholder="e.g. 5000" /></label>
        <label>Payment method<select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>{PAYMENT_METHODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Reference number<input value={paymentReference} onChange={(e) => setPaymentReference(e.target.value)} placeholder="UPI ref / cheque no (optional)" /></label>
        <label>Against invoice<select value={paymentInvoice} onChange={(e) => setPaymentInvoice(e.target.value)}>
          <option value="">Customer account (no specific invoice)</option>
          {openInvoices.map((invoice) => <option key={invoice.id} value={invoice.id}>{invoice.invoice_number} · {money(invoice.total_amount)}</option>)}
        </select></label>
      </div>
      <div className="form-grid" style={{ marginTop: 12 }}>
        <label className="full-width">Notes<textarea rows={2} value={paymentNotes} onChange={(e) => setPaymentNotes(e.target.value)} placeholder="Optional note" /></label>
      </div>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowPaymentForm(false)}>Cancel</button>
        <button className="primary-button" disabled={busy}>{busy ? 'Saving...' : 'Save payment'}</button>
      </div>
    </form>}

    {reversingId && isAdmin && <div className="record-form">
      <div className="form-heading"><div><p className="eyebrow">Correction</p><h2>Reverse payment #{reversingId}</h2></div></div>
      <p className="field-help" style={{ marginBottom: 10 }}>The original payment stays in history; the reversal restores what the customer owes and is audited.</p>
      <div className="form-grid">
        <label>Reversal amount<input type="number" min="0.01" step="0.01" value={reversalAmount} onChange={(e) => setReversalAmount(e.target.value)} aria-label="Reversal amount" /></label>
        <label className="full-width">Reason<input value={reversalReason} onChange={(e) => setReversalReason(e.target.value)} placeholder="Why is this payment being reversed?" aria-label="Reversal reason" /></label>
      </div>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => { setReversingId(null); setReversalAmount(''); setReversalReason('') }}>Keep payment</button>
        <button type="button" className="primary-button" style={{ background: 'var(--red)' }} onClick={submitReversal} disabled={busy}>{busy ? 'Reversing...' : 'Reverse payment'}</button>
      </div>
    </div>}

    <div className="print-sheet">
      <div className="invoice-detail-head">
        <div>
          <p className="eyebrow">Divya Enterprises / Customer account</p>
          <h1>{customer.name}</h1>
          <p>{customer.customer_type}{customer.is_regular ? ' · Regular' : ''}{customer.is_active ? '' : ' · ARCHIVED'}</p>
        </div>
        <div className="detail-status">
          <span className={customer.is_active ? 'tax-chip' : 'state-cancelled'}>{customer.is_active ? 'Active' : 'Archived'}</span>
        </div>
      </div>

      <div className="detail-parties">
        <div>
          <span>Contact</span>
          <strong>{customer.contact_info || '—'}</strong>
          <span>{customer.billing_address || ''}</span>
          <span>{customer.state}{customer.state_code ? ` (${customer.state_code})` : ''}{customer.pincode ? ` · ${customer.pincode}` : ''}</span>
        </div>
        <div>
          <span>GST</span>
          <strong>{customer.gstin || 'Unregistered'}</strong>
          <span>{customer.gst_registration_type}</span>
        </div>
        <div>
          <span>Credit</span>
          <strong>Limit {Number(customer.credit_limit) > 0 ? money(customer.credit_limit) : '—'}</strong>
          <span>Outstanding <b className={Number(outstanding) > 0 ? 'balance due' : ''}>{money(outstanding)}</b></span>
          <span>Available {Number(customer.credit_limit) > 0 ? money(availableCredit) : '—'}</span>
        </div>
      </div>

      <p className="eyebrow" style={{ margin: '26px 0 12px' }}>Invoices</p>
      {invoices.length === 0 ? <div className="empty-state">No invoices for this customer yet.</div> : <div className="table-scroll"><table>
        <thead><tr><th>Invoice</th><th>Date</th><th>Payment</th><th>Payment status</th><th>Total</th><th>State</th><th aria-label="Actions" /></tr></thead>
        <tbody>{invoices.map((invoice) => <tr key={invoice.id} className={invoice.state === 'CANCELLED' ? 'archived-row' : ''}>
          <td><strong>{invoice.invoice_number}</strong></td>
          <td>{invoice.invoice_date}</td>
          <td><span className="type-chip">{invoice.payment_type}</span></td>
          <td><span className={PAYMENT_STATUS_BADGE[invoice.payment_status] || 'type-chip'}>{invoice.payment_status}</span></td>
          <td><strong>{money(invoice.total_amount)}</strong></td>
          <td><span className={STATE_BADGE[invoice.state] || 'type-chip'}>{invoice.state}</span></td>
          <td><Link className="text-button" to={`/invoices/${invoice.id}`}>View</Link></td>
        </tr>)}</tbody>
      </table></div>}

      <p className="eyebrow" style={{ margin: '26px 0 12px' }}>Payments</p>
      {payments.length === 0 ? <div className="empty-state">No payments recorded for this customer yet.</div> : <div className="table-scroll"><table>
        <thead><tr><th>Date</th><th>Invoice</th><th>Amount</th><th>Reversed</th><th>Net</th><th>Notes</th>{isAdmin && <th aria-label="Actions" />}</tr></thead>
        <tbody>{payments.map((payment) => {
          const net = Number(payment.amount) - Number(payment.reversed_amount)
          return <tr key={payment.id}>
            <td>{payment.payment_date}</td>
            <td>{payment.invoice_number ? <Link className="text-button" to={`/invoices/${payment.invoice_id}`}>{payment.invoice_number}</Link> : 'On account'}</td>
            <td><strong>{money(payment.amount)}</strong></td>
            <td>{Number(payment.reversed_amount) > 0 ? <span className="state-cancelled">{money(payment.reversed_amount)}</span> : '—'}</td>
            <td className="stock-value">{money(net)}</td>
            <td>{payment.notes || '—'}</td>
            {isAdmin && <td>{Number(payment.reversed_amount) < Number(payment.amount) && <button className="text-button danger" onClick={() => { setReversingId(payment.id); setReversalAmount(''); setReversalReason('') }}>Reverse</button>}</td>}
          </tr>
        })}</tbody>
      </table></div>}

      <p className="eyebrow" style={{ margin: '26px 0 12px' }}>Account statement</p>
      {statement.length === 0 ? <div className="empty-state">No transactions yet.</div> : <div className="table-scroll"><table>
        <thead><tr><th>Date</th><th>Reference</th><th>Type</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead>
        <tbody>{statement.map((row, index) => <tr key={index} className={row.type === 'PAYMENT_REVERSAL' || row.type === 'DEBIT_NOTE' ? 'archived-row' : ''}>
          <td>{row.date || '—'}</td>
          <td><strong>{row.reference}</strong></td>
          <td><span className="type-chip">{STATEMENT_TYPE_LABELS[row.type] || row.type}</span></td>
          <td className="stock-value">{row.debit != null ? money(row.debit) : '—'}</td>
          <td className="stock-value">{row.credit != null ? money(row.credit) : '—'}</td>
          <td><strong className="balance due">{money(row.balance)}</strong></td>
        </tr>)}</tbody>
      </table></div>}
      {statement.length > 0 && <div className="detail-total">
        <span>Closing balance {money(report.statement_closing_balance)}</span>
        <strong>{money(outstanding)} outstanding</strong>
      </div>}
    </div>
  </section>
}
