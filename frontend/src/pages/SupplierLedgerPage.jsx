import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import {
  balanceLabel,
  createSupplierPayment,
  exportSupplierStatement,
  fetchSupplierLedger,
  PAYMENT_MODES,
  reverseSupplierPayment,
} from '../api/supplierLedger'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }

function today() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const EMPTY_PAYMENT = { amount: '', payment_date: '', mode: 'BANK_TRANSFER', reference: '', notes: '' }

function BalanceText({ balance }) {
  const label = balanceLabel(balance)
  if (label === 'Settled') return <span>{money(0)} (Settled)</span>
  return <span>{money(Math.abs(Number(balance)))} {label}</span>
}

export default function SupplierLedgerPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [ledger, setLedger] = useState(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [payment, setPayment] = useState({ ...EMPTY_PAYMENT, payment_date: today() })
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [reversing, setReversing] = useState(null) // { id, amount, reason }

  const load = useCallback(async (range = {}) => {
    setError('')
    try {
      setLedger(await fetchSupplierLedger(id, range))
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }, [id])

  useEffect(() => {
    let active = true
    fetchSupplierLedger(id)
      .then((data) => { if (active) setLedger(data) })
      .catch((err) => { if (active) setError(apiErrorMessage(err)) })
    return () => { active = false }
  }, [id])

  async function recordPayment(event) {
    event.preventDefault()
    if (!(Number(payment.amount) > 0)) { setError('Enter a payment amount greater than zero.'); return }
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await createSupplierPayment({
        supplier: Number(id),
        amount: payment.amount,
        payment_date: payment.payment_date || today(),
        mode: payment.mode,
        reference: payment.reference.trim(),
        notes: payment.notes.trim(),
      })
      setPayment({ ...EMPTY_PAYMENT, payment_date: today() })
      setMessage('Payment recorded.')
      await load({ from, to })
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'recording payment' }))
    } finally {
      setBusy(false)
    }
  }

  async function confirmReversal() {
    if (!reversing?.reason?.trim()) { setError('A reversal reason is required.'); return }
    setBusy(true)
    setError('')
    try {
      await reverseSupplierPayment(reversing.id, { amount: reversing.amount, reason: reversing.reason.trim() })
      setReversing(null)
      setMessage('Payment reversed.')
      await load({ from, to })
    } catch (err) {
      setError(err.response?.status === 403 ? apiForbiddenMessage(err, 'reverse supplier payments') : apiErrorMessage(err, { action: 'reversing payment' }))
    } finally {
      setBusy(false)
    }
  }

  async function exportStatement() {
    setExporting(true)
    setError('')
    try {
      await exportSupplierStatement(id, { from, to })
    } catch (err) {
      setError(apiErrorMessage(err, { action: 'exporting statement' }))
    } finally {
      setExporting(false)
    }
  }

  if (error && !ledger) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to={`/suppliers/${id}`}>Back to supplier</Link></section>
  if (!ledger) return <section className="page-section"><div className="empty-state">Loading supplier ledger...</div></section>

  const supplier = ledger.supplier || {}

  return <section className="page-section invoice-detail-page">
    <header className="detail-toolbar">
      <Link className="quiet-button" to={`/suppliers/${id}`}>← {supplier.name || 'Supplier'}</Link>
      <div className="detail-actions">
        <button type="button" className="quiet-button" onClick={() => window.print()}>Print statement</button>
        <button type="button" className="quiet-button" onClick={exportStatement} disabled={exporting}>{exporting ? 'Exporting...' : 'Export (Excel)'}</button>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>
    {message && <p className="field-help no-print" role="status" style={{ fontSize: 12, color: 'var(--green)' }}>{message}</p>}

    <form className="record-form no-print" onSubmit={recordPayment}>
      <div className="form-heading"><div><p className="eyebrow">Accounts payable</p><h2>Record payment to supplier</h2></div></div>
      <div className="form-grid">
        <label>Amount (₹)<input type="number" min="0.01" step="0.01" value={payment.amount} onChange={(e) => setPayment({ ...payment, amount: e.target.value })} aria-label="Payment amount" required /></label>
        <label>Date<input type="date" value={payment.payment_date} onChange={(e) => setPayment({ ...payment, payment_date: e.target.value })} aria-label="Payment date" /></label>
        <label>Mode
          <select value={payment.mode} onChange={(e) => setPayment({ ...payment, mode: e.target.value })} aria-label="Payment mode">
            {PAYMENT_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
        <label>Reference<input value={payment.reference} onChange={(e) => setPayment({ ...payment, reference: e.target.value })} placeholder="UTR / cheque / UPI ref" aria-label="Payment reference" /></label>
        <label style={{ gridColumn: 'span 4' }}>Notes<input value={payment.notes} onChange={(e) => setPayment({ ...payment, notes: e.target.value })} aria-label="Payment notes" /></label>
      </div>
      <p className="field-help">Round-figure advances are fine: they are drawn down by later purchases. Payments are append-only; an admin can reverse one.</p>
      <div className="form-actions"><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving...' : 'Record payment'}</button></div>
    </form>

    {reversing && <div className="record-form no-print">
      <div className="form-heading"><div><p className="eyebrow">Reversal</p><h2>Reverse payment</h2></div></div>
      <div className="form-grid">
        <label>Amount (₹)<input type="number" min="0.01" step="0.01" value={reversing.amount} onChange={(e) => setReversing({ ...reversing, amount: e.target.value })} aria-label="Reversal amount" /></label>
        <label style={{ gridColumn: 'span 3' }}>Reason<input value={reversing.reason} onChange={(e) => setReversing({ ...reversing, reason: e.target.value })} aria-label="Reversal reason" /></label>
      </div>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setReversing(null)}>Keep payment</button>
        <button type="button" className="primary-button" style={{ background: 'var(--red)' }} onClick={confirmReversal} disabled={busy}>Reverse payment</button>
      </div>
    </div>}

    <div className="report-filters no-print" style={{ display: 'flex', gap: 12, alignItems: 'center', margin: '0 0 16px' }}>
      <label className="filter-field">From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" /></label>
      <label className="filter-field">To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" /></label>
      <button type="button" className="quiet-button" onClick={() => load({ from, to })}>Apply</button>
      {(from || to) && <button type="button" className="quiet-button" onClick={() => { setFrom(''); setTo(''); load() }}>Clear</button>}
    </div>

    <div className="print-sheet">
      <div className="invoice-detail-head">
        <div>
          <p className="eyebrow">{ledger.business?.business_name || 'Divya Enterprises'} / Supplier statement</p>
          <h1>{supplier.name}</h1>
          <p>{[supplier.gstin || 'GSTIN not recorded', supplier.contact_info].filter(Boolean).join(' · ')}</p>
          {supplier.address && <p>{supplier.address}</p>}
        </div>
        <div className="detail-status">
          <span>{balanceLabel(ledger.closing_balance)}</span>
          <strong data-testid="closing-balance"><BalanceText balance={ledger.closing_balance} /></strong><br />
          <span style={{ background: 'transparent', color: '#89958d' }}>{ledger.from || 'Start'} → {ledger.to || 'Today'}</span>
        </div>
      </div>
      <table className="data-table detail-table">
        <thead>
          <tr><th>Date</th><th>Type</th><th>Reference</th><th style={{ textAlign: 'right' }}>Debit (paid / returned)</th><th style={{ textAlign: 'right' }}>Credit (purchased)</th><th style={{ textAlign: 'right' }}>Balance</th><th className="no-print" /></tr>
        </thead>
        <tbody>
          {(ledger.from && Number(ledger.opening_balance) !== 0) && (
            <tr><td>{ledger.from}</td><td>Brought forward</td><td>Balance before {ledger.from}</td><td /><td /><td style={{ textAlign: 'right' }}><BalanceText balance={ledger.opening_balance} /></td><td className="no-print" /></tr>
          )}
          {(ledger.entries || []).map((entry, index) => (
            <tr key={`${entry.kind}-${entry.id}-${index}`} data-testid="ledger-row">
              <td>{entry.date}</td>
              <td>{entry.type_label}</td>
              <td>{entry.reference}{entry.mode_label ? ` · ${entry.mode_label}` : ''}</td>
              <td style={{ textAlign: 'right' }}>{entry.debit != null ? money(entry.debit) : ''}</td>
              <td style={{ textAlign: 'right' }}>{entry.credit != null ? money(entry.credit) : ''}</td>
              <td style={{ textAlign: 'right' }}><BalanceText balance={entry.balance} /></td>
              <td className="no-print">
                {isAdmin && entry.kind === 'payment' && Number(entry.reversible_amount) > 0 && (
                  <button type="button" className="quiet-button" onClick={() => setReversing({ id: entry.id, amount: entry.reversible_amount, reason: '' })}>Reverse</button>
                )}
              </td>
            </tr>
          ))}
          {!(ledger.entries || []).length && <tr><td colSpan={7} className="empty-state">No entries in this period.</td></tr>}
        </tbody>
      </table>
      <div className="detail-total">
        <span>Total purchased {money(ledger.total_credit)} · Total paid / returned {money(ledger.total_debit)}</span>
        <strong>Closing: <BalanceText balance={ledger.closing_balance} /></strong>
      </div>
      <p className="field-help">Balance above zero is Payable (owed to the supplier); below zero is an Advance (paid ahead).</p>
    </div>
  </section>
}
