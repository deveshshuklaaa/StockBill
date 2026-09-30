import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchInvoices, printInvoicePdf } from '../api/invoices'
import InvoiceItemSummaryModal from '../components/InvoiceItemSummaryModal'
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
  const [selectedIds, setSelectedIds] = useState([])
  const [summaryOpen, setSummaryOpen] = useState(false)
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

  const postedInvoicesOnPage = invoices.filter((inv) => inv.state === 'POSTED')
  const allPostedSelected = postedInvoicesOnPage.length > 0 && postedInvoicesOnPage.every((inv) => selectedIds.includes(inv.id))

  function toggleSelectAllOnPage() {
    if (allPostedSelected) {
      const pagePostedIds = new Set(postedInvoicesOnPage.map((inv) => inv.id))
      setSelectedIds((prev) => prev.filter((id) => !pagePostedIds.has(id)))
    } else {
      setSelectedIds((prev) => {
        const set = new Set(prev)
        postedInvoicesOnPage.forEach((inv) => set.add(inv.id))
        return Array.from(set)
      })
    }
  }

  function toggleSelectInvoice(id) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]))
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))
  const filtersActive = search || stateFilter || paymentFilter || fromFilter || toFilter

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Billing / sales history</p>
        <h1>Invoices</h1>
        <p className="page-subtitle">Sales invoices with payment status and stock effect history.</p>
      </div>
      <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
        <button
          type="button"
          className="primary-button"
          style={selectedIds.length === 0 ? { opacity: 0.6, cursor: 'not-allowed', background: '#53685c' } : {}}
          disabled={selectedIds.length === 0}
          onClick={() => setSummaryOpen(true)}
        >
          {selectedIds.length > 0 ? `Item-wise Summary (${selectedIds.length})` : 'Item-wise Summary'}
        </button>
        <Link className="primary-button" to="/invoices/new">New invoice</Link>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
          <span>{busy ? 'Loading invoices...' : `${total} invoice${total === 1 ? '' : 's'}`}</span>
          {selectedIds.length > 0 && (
            <span style={{ fontSize: '12px', color: '#1e4832', fontWeight: 600 }}>
              Selected: {selectedIds.length} invoice{selectedIds.length === 1 ? '' : 's'}
              <button
                type="button"
                className="text-button"
                style={{ marginLeft: '8px' }}
                onClick={() => setSelectedIds([])}
                aria-label="Clear selected invoices"
              >
                Clear
              </button>
            </span>
          )}
        </div>
        <div className="filter-row">
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Invoice no, customer" aria-label="Search invoices" /></label>
          <label className="filter-field">Status<select value={stateFilter} onChange={(e) => { setStateFilter(e.target.value); setPage(1) }} aria-label="Filter by status"><option value="">All</option><option value="POSTED">Posted</option><option value="DRAFT">Draft</option><option value="CANCELLED">Cancelled</option></select></label>
          <label className="filter-field">Payment<select value={paymentFilter} onChange={(e) => { setPaymentFilter(e.target.value); setPage(1) }} aria-label="Filter by payment type"><option value="">All</option><option value="cash">Cash</option><option value="credit">Credit</option></select></label>
          <label className="filter-field">From<input type="date" value={fromFilter} onChange={(e) => { setFromFilter(e.target.value); setPage(1) }} aria-label="From date" /></label>
          <label className="filter-field">To<input type="date" value={toFilter} onChange={(e) => { setToFilter(e.target.value); setPage(1) }} aria-label="To date" /></label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading invoices...</div> : invoices.length === 0 ? <div className="empty-state">{filtersActive ? 'No invoices match your filters.' : 'No invoices yet. Create your first sale.'}</div> : <div className="table-scroll"><table>
        <thead><tr>
          <th style={{ width: '40px', textAlign: 'center' }}>
            <input
              type="checkbox"
              aria-label="Select all posted invoices on page"
              checked={allPostedSelected}
              onChange={toggleSelectAllOnPage}
              disabled={postedInvoicesOnPage.length === 0}
            />
          </th>
          <th>Invoice</th><th>Date</th><th>Customer</th><th>Payment</th><th>Payment status</th><th>Total</th><th>State</th><th aria-label="Actions" />
        </tr></thead>
        <tbody>{invoices.map((invoice) => <tr key={invoice.id} className={invoice.state === 'CANCELLED' ? 'archived-row' : ''}>
          <td style={{ textAlign: 'center' }}>
            <input
              type="checkbox"
              aria-label={`Select invoice ${invoice.invoice_number}`}
              checked={selectedIds.includes(invoice.id)}
              onChange={() => toggleSelectInvoice(invoice.id)}
              disabled={invoice.state !== 'POSTED'}
              title={invoice.state !== 'POSTED' ? 'Only posted invoices can be selected for item summary' : ''}
            />
          </td>
          <td><strong>{invoice.invoice_number}</strong></td>
          <td>{invoice.invoice_date}</td>
          <td>{invoice.customer_name || 'Walk-in'}</td>
          <td><span className="type-chip">{invoice.payment_type}</span></td>
          <td><span className={invoice.payment_status === 'paid' ? 'tax-chip' : 'balance due'}>{invoice.payment_status}</span></td>
          <td><strong>{money(invoice.total_amount)}</strong></td>
          <td><span className={STATE_BADGE[invoice.state] || 'type-chip'}>{invoice.state}</span></td>
          <td>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <Link className="text-button" to={`/invoices/${invoice.id}`}>View</Link>
              {invoice.state === 'DRAFT' && (
                <Link className="text-button" to={`/invoices/new?edit=${invoice.id}`} aria-label={`Edit draft invoice ${invoice.invoice_number}`}>Edit</Link>
              )}
              {invoice.state === 'POSTED' && <>
                <button className="text-button" onClick={() => handlePrint(invoice.id, 'original', invoice.invoice_number)} aria-label={`Print original invoice ${invoice.invoice_number}`}>Original</button>
                <button className="text-button" onClick={() => handlePrint(invoice.id, 'duplicate', invoice.invoice_number)} aria-label={`Print duplicate invoice ${invoice.invoice_number}`}>Duplicate</button>
                <button className="text-button" onClick={() => handlePrint(invoice.id, 'reprint', invoice.invoice_number)} aria-label={`Print reprint invoice ${invoice.invoice_number}`}>Reprint</button>
              </>}
              {invoice.state === 'CANCELLED' && invoice.replacement_invoice && (
                <Link className="text-button" to={`/invoices/${invoice.replacement_invoice}`} aria-label={`View replacement for invoice ${invoice.invoice_number}`}>Replacement →</Link>
              )}
              {invoice.amended_from_invoice && (
                <Link className="text-button" to={`/invoices/${invoice.amended_from_invoice}`} aria-label={`View original invoice for ${invoice.invoice_number}`}>← Original</Link>
              )}
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

    <InvoiceItemSummaryModal
      isOpen={summaryOpen}
      onClose={() => setSummaryOpen(false)}
      selectedIds={selectedIds}
    />
  </section>
}
