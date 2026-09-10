import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchPurchases, fetchSuppliers } from '../api/purchases'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const STATE_BADGE = {
  DRAFT: 'type-chip',
  POSTED: 'tax-chip',
  CANCELLED: 'state-cancelled',
}

export default function PurchasesPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [purchases, setPurchases] = useState([])
  const [suppliers, setSuppliers] = useState([])
  const [stateFilter, setStateFilter] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [hasPrevious, setHasPrevious] = useState(false)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const latestLoad = useRef(0)

  useEffect(() => {
    const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    fetchSuppliers().then(setSuppliers).catch(() => {})
  }, [])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true); setError('')
    fetchPurchases({ page, state: stateFilter, supplier: supplierFilter, search })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setPurchases(Array.isArray(data) ? data : data.results || [])
        setTotal(Number(data.count ?? 0))
        setHasNext(Boolean(data.next))
        setHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestLoad.current) return
        if (err?.response?.status === 404 && page > 1) { setPage(1); return }
        setError(apiErrorMessage(err))
      })
      .finally(() => { if (requestId === latestLoad.current) setBusy(false) })
  }, [page, stateFilter, supplierFilter, search])

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Purchasing / goods inward</p><h1>Purchases</h1><p className="page-subtitle">Supplier invoices, stock receipts, and weighted-average cost updates.</p></div>
      {isAdmin && <Link className="primary-button" to="/purchases/new">New purchase</Link>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading purchases...' : `${total} purchase${total === 1 ? '' : 's'}`}</span>
        <div className="filter-row">
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="PI no, bill no, supplier" aria-label="Search purchases" /></label>
          <label className="filter-field">Status<select value={stateFilter} onChange={(e) => { setStateFilter(e.target.value); setPage(1) }} aria-label="Filter by status"><option value="">All</option><option value="DRAFT">Draft</option><option value="POSTED">Posted</option><option value="CANCELLED">Cancelled</option></select></label>
          <label className="filter-field">Supplier<select value={supplierFilter} onChange={(e) => { setSupplierFilter(e.target.value); setPage(1) }} aria-label="Filter by supplier"><option value="">All</option>{suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading purchases...</div> : purchases.length === 0 ? <div className="empty-state">{search || stateFilter || supplierFilter ? 'No purchases match your filters.' : 'No purchases yet. Record your first supplier invoice.'}</div> : <div className="table-scroll"><table>
        <thead><tr><th>Purchase</th><th>Supplier</th><th>Date</th><th>Bill no</th><th>Warehouse</th><th>Taxable</th><th>Total</th><th>Status</th></tr></thead>
        <tbody>{purchases.map((purchase) => <tr key={purchase.id} className={purchase.state === 'CANCELLED' ? 'archived-row' : ''}>
          <td><strong>{purchase.purchase_number || `Draft #${purchase.id}`}</strong></td>
          <td>{purchase.supplier_name}</td>
          <td>{purchase.invoice_date}</td>
          <td><code>{purchase.supplier_invoice_no || '-'}</code></td>
          <td>{purchase.warehouse_name}</td>
          <td>{money(purchase.taxable_total)}</td>
          <td><strong>{money(purchase.total_amount)}</strong></td>
          <td><span className={STATE_BADGE[purchase.state] || 'type-chip'}>{purchase.state}</span></td>
        </tr>)}</tbody>
      </table></div>}
      <div className="table-meta pager" role="navigation" aria-label="Purchase pagination">
        <button className="pager-button" onClick={() => setPage((c) => Math.max(1, c - 1))} disabled={!hasPrevious || busy}>← Previous</button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} purchases` : ''}</span>
        <button className="pager-button" onClick={() => setPage((c) => c + 1)} disabled={!hasNext || busy}>Next →</button>
      </div>
    </div>
  </section>
}
