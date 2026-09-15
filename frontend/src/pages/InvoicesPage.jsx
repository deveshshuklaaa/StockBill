import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchInvoices, printInvoicePdf } from '../api/invoices'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const STATE_BADGE = {
  DRAFT: 'type-chip',
  POSTED: 'tax-chip',
  CANCELLED: 'state-cancelled',
}

export default function InvoicesPage() {
  const { user } = useAuth()
  const [invoices, setInvoices] = useState([])
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [paymentFilter, setPaymentFilter] = useState('')
  const [fromFilter, setFromFilter] = useState('')
  const [toFilter, setToFilter] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [hasPrevious, setHasPrevious] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const latestLoad = useRef(0)

  useEffect(() => {
    const handle = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 250)
    return () => clearTimeout(handle)
  }, [searchInput])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true); setError('')
    fetchInvoices({
      page,
      search,
      state: stateFilter,
      paymentType: paymentFilter,
      from: fromFilter,
      to: toFilter,
    })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setInvoices(data.results || [])
        setTotal(data.count || 0)
        setHasNext(Boolean(data.next))
        setHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestLoad.current) return
        if (err?.response?.status === 404 && page > 1) { setPage(1); return }
        setError(apiErrorMessage(err))
      })
      .finally(() => { if (requestId === latestLoad.current) setBusy(false) })
  }, [page, search, stateFilter, paymentFilter, fromFilter, toFilter])

  async function handlePrint(id, copy, invoiceNumber) {
    try {
      await printInvoicePdf(id, { copy, invoiceNumber })
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))
  const filtersActive = search || stateFilter || paymentFilter || fromFilter || toFilter

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Billing / sales history</p><h1>Invoices</h1><p className="page-subtitle">Sales invoices with payment status and stock effect history.</p></div>
      <Link className="primary-button" to="/invoices/new">New invoice</Link>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading invoices...' : `${total} invoice${total === 1 ? '' : 's'}`}</span>
        <div className="filter-row">
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Invoice no, customer" aria-label="Search invoices" /></label>
          <label className="filter-field">Status<select value={stateFilter} onChange={(e) => { setStateFilter(e.target.value); setPage(1) }} aria-label="Filter by status"><option value="">All</option><option value="POSTED">Posted</option><option value="DRAFT">Draft</option><option value="CANCELLED">Cancelled</option></select></label>
          <label className="filter-field">Payment<select value={paymentFilter} onChange={(e) => { setPaymentFilter(e.target.value); setPage(1) }} aria-label="Filter by payment type"><option value="">All</option><option value="cash">Cash</option><option value="credit">Credit</option></select></label>
          <label className="filter-field">From<input type="date" value={fromFilter} onChange={(e) => { setFromFilter(e.target.value); setPage(1) }} aria-label="From date" /></label>
          <label className="filter-field">To<input type="date" value={toFilter} onChange={(e) => { setToFilter(e.target.value); setPage(1) }} aria-label="To date" /></label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading invoices...</div> : invoices.length === 0 ? <div className="empty-state">{filtersActive ? 'No invoices match your filters.' : 'No invoices yet. Create your first sale.'}</div> : <div className="table-scroll"><table>
        <thead><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>Payment</th><th>Payment status</th><th>Total</th><th>State</th><th aria-label="Actions" /></tr></thead>
        <tbody>{invoices.map((invoice) => <tr key={invoice.id} className={invoice.state === 'CANCELLED' ? 'archived-row' : ''}>
          <td><strong>{invoice.invoice_number}</strong></td>
          <td>{invoice.invoice_date}</td>
          <td>{invoice.customer_name || 'Walk-in'}</td>
          <td><span className="type-chip">{invoice.payment_type}</span></td>
          <td><span className={invoice.payment_status === 'paid' ? 'tax-chip' : 'balance due'}>{invoice.payment_status}</span></td>
          <td><strong>{money(invoice.total_amount)}</strong></td>
          <td><span className={STATE_BADGE[invoice.state] || 'type-chip'}>{invoice.state}</span></td>
          <td>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <Link className="text-button" to={`/invoices/${invoice.id}`}>View</Link>
              {invoice.state === 'POSTED' && <>
                <button className="text-button" onClick={() => handlePrint(invoice.id, 'original', invoice.invoice_number)} aria-label={`Print original invoice ${invoice.invoice_number}`}>Original</button>
                <button className="text-button" onClick={() => handlePrint(invoice.id, 'duplicate', invoice.invoice_number)} aria-label={`Print duplicate invoice ${invoice.invoice_number}`}>Duplicate</button>
              </>}
            </div>
          </td>
        </tr>)}</tbody>
      </table></div>}
      <div className="table-meta pager" role="navigation" aria-label="Invoice pagination">
        <button className="pager-button" onClick={() => setPage((c) => Math.max(1, c - 1))} disabled={!hasPrevious || busy}>← Previous</button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} invoices` : ''}</span>
        <button className="pager-button" onClick={() => setPage((c) => c + 1)} disabled={!hasNext || busy}>Next →</button>
      </div>
    </div>
    {!user && <div className="empty-state">Session expired.</div>}
  </section>
}
