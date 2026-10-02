import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import {
  fetchCustomer,
  fetchCustomerReport,
  fetchCustomerMRPPricing,
  saveCustomerMRPPricing,
  deleteCustomerMRPPricing,
  recordPayment,
  reversePayment,
} from '../api/customers'
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

  // Customer MRP Pricing State
  const [pricingData, setPricingData] = useState({ pricing: [], available_mrps: [] })
  const [pricingDrafts, setPricingDrafts] = useState({})
  const [pricingSaving, setPricingSaving] = useState({})
  const [pricingMsg, setPricingMsg] = useState('')
  const [pricingError, setPricingError] = useState('')
  const [showAddCustomSlab, setShowAddCustomSlab] = useState(false)
  const [customMrp, setCustomMrp] = useState('')
  const [customRate, setCustomRate] = useState('')

  useEffect(() => {
    let cancelled = false
    setCustomer(null); setReport(null); setError(''); setShowPaymentForm(false)
    fetchCustomer(id)
      .then((data) => { if (!cancelled) setCustomer(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
    fetchCustomerReport(id)
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })

    fetchCustomerMRPPricing(id)
      .then((data) => {
        if (cancelled) return
        setPricingData(data)
        const drafts = {}
        data.pricing.forEach((p) => {
          drafts[String(p.mrp)] = p.rate_per_piece
        })
        setPricingDrafts(drafts)
      })
      .catch(() => {})

    return () => { cancelled = true }
  }, [id])

  async function refreshPricing() {
    try {
      const data = await fetchCustomerMRPPricing(id)
      setPricingData(data)
      const drafts = {}
      data.pricing.forEach((p) => {
        drafts[String(p.mrp)] = p.rate_per_piece
      })
      setPricingDrafts(drafts)
    } catch (err) {
      setPricingError(apiErrorMessage(err))
    }
  }

  async function savePricingSlab(mrp, rateValue) {
    if (rateValue === undefined || rateValue === '' || Number(rateValue) < 0) {
      setPricingError(`Please enter a valid non-negative rate for MRP ₹${mrp}.`)
      return
    }
    setPricingSaving((prev) => ({ ...prev, [mrp]: true }))
    setPricingError('')
    setPricingMsg('')
    try {
      await saveCustomerMRPPricing(id, {
        mrp: Number(mrp),
        rate_per_piece: Number(rateValue),
      })
      setPricingMsg(`Saved rate ₹${rateValue}/pc for MRP ₹${mrp}.`)
      await refreshPricing()
    } catch (err) {
      setPricingError(apiErrorMessage(err))
    } finally {
      setPricingSaving((prev) => ({ ...prev, [mrp]: false }))
    }
  }

  async function removePricingSlab(pricingId, mrp) {
    setPricingSaving((prev) => ({ ...prev, [mrp]: true }))
    setPricingError('')
    setPricingMsg('')
    try {
      await deleteCustomerMRPPricing(id, pricingId)
      setPricingMsg(`Removed pricing for MRP ₹${mrp}.`)
      await refreshPricing()
    } catch (err) {
      setPricingError(apiErrorMessage(err))
    } finally {
      setPricingSaving((prev) => ({ ...prev, [mrp]: false }))
    }
  }

  async function addCustomSlab(e) {
    e.preventDefault()
    if (!customMrp || Number(customMrp) <= 0) {
      setPricingError('Enter a valid MRP greater than 0.')
      return
    }
    if (!customRate || Number(customRate) < 0) {
      setPricingError('Enter a valid selling rate per piece.')
      return
    }
    await savePricingSlab(customMrp, customRate)
    setCustomMrp('')
    setCustomRate('')
    setShowAddCustomSlab(false)
  }

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

      {/* Customer-wise MRP Pricing Section */}
      <div className="customer-pricing-section" style={{ margin: '28px 0 16px' }} id="customer-pricing">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <div>
            <p className="eyebrow" style={{ margin: 0 }}>Selling Rates</p>
            <h2 style={{ fontSize: '1.25rem', margin: '4px 0 0' }}>Customer MRP Pricing</h2>
          </div>
          {isAdmin && (
            <button
              type="button"
              className="quiet-button"
              onClick={() => setShowAddCustomSlab((v) => !v)}
              id="btn-add-custom-mrp"
            >
              {showAddCustomSlab ? 'Cancel' : '+ Add Custom MRP'}
            </button>
          )}
        </div>

        <p style={{ fontSize: '0.875rem', color: '#4b5563', margin: '0 0 12px' }}>
          Fixed selling rate per MRP slab for this customer. <strong>Rate is per piece/base unit.</strong> All products with the matching MRP will automatically receive this rate on new invoices.
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

        {showAddCustomSlab && isAdmin && (
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
                placeholder="e.g. 25.00"
                value={customMrp}
                onChange={(e) => setCustomMrp(e.target.value)}
                style={{ width: '100px' }}
                required
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              Rate / Piece (₹):
              <input
                type="number"
                step="0.01"
                min="0.00"
                placeholder="e.g. 18.00"
                value={customRate}
                onChange={(e) => setCustomRate(e.target.value)}
                style={{ width: '100px' }}
                required
              />
            </label>
            <button type="submit" className="primary-button" style={{ padding: '0.4rem 0.8rem' }}>
              Add Slab
            </button>
          </form>
        )}

        {/* Pricing Slabs Table */}
        {(() => {
          // Merge available MRPs from catalogue with any existing configured MRPs
          const configuredMap = new Map()
          pricingData.pricing.forEach((p) => {
            configuredMap.set(Number(p.mrp).toFixed(2), p)
          })

          const allMrpSet = new Set(
            (pricingData.available_mrps || []).map((m) => Number(m).toFixed(2))
          )
          pricingData.pricing.forEach((p) => {
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
                    {isAdmin && <th style={{ textAlign: 'right' }}>Actions</th>}
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
                          {isAdmin ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span>₹</span>
                              <input
                                type="number"
                                step="0.01"
                                min="0.00"
                                value={draftRate}
                                onChange={(e) =>
                                  setPricingDrafts((prev) => ({
                                    ...prev,
                                    [mrpStr]: e.target.value,
                                  }))
                                }
                                placeholder="e.g. 7.00"
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
                              <button
                                type="button"
                                className="text-button"
                                disabled={isSaving}
                                onClick={() => savePricingSlab(mrpStr, draftRate)}
                                id={`btn-save-pricing-${mrpStr}`}
                              >
                                {isSaving ? 'Saving...' : existing ? 'Update' : 'Save'}
                              </button>
                              {existing && (
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
