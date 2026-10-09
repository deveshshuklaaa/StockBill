import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { deletePurchase, fetchPurchases } from '../api/purchases'
import { fetchSuppliers } from '../api/suppliers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

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
  const [success, setSuccess] = useState('')
  const [draftToDelete, setDraftToDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const latestLoad = useRef(0)

  useEffect(() => {
    const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    fetchSuppliers({ page: 1 }).then((data) => setSuppliers(data.results || [])).catch(() => {})
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

  async function handleConfirmDeleteDraft() {
    if (!draftToDelete) return
    setDeleting(true)
    setError('')
    try {
      await deletePurchase(draftToDelete.id)
      setPurchases((prev) => prev.filter((p) => p.id !== draftToDelete.id))
      setTotal((prev) => Math.max(0, prev - 1))
      setSuccess(`Draft purchase ${draftToDelete.purchase_number || `#${draftToDelete.id}`} deleted successfully.`)
      setDraftToDelete(null)
    } catch (err) {
      setError(apiErrorMessage(err))
      setDraftToDelete(null)
    } finally {
      setDeleting(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Purchasing / goods inward</p><h1>Purchases</h1><p className="page-subtitle">Supplier invoices, stock receipts, and weighted-average cost updates.</p></div>
      {isAdmin && <Link className="primary-button" to="/purchases/new">New purchase</Link>}
    </header>
    <StatusMessage>{error}</StatusMessage>
    {success && <div className="status-success" style={{ padding: '0.75rem 1rem', marginBottom: '1rem', borderRadius: '4px', background: 'var(--green-light, #e8f5e9)', color: 'var(--green-dark, #2e7d32)' }}>{success}</div>}

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
        <thead><tr><th>Purchase</th><th>Supplier</th><th>Date</th><th>Bill no</th><th>Warehouse</th><th>Taxable</th><th>Total</th><th>Status</th><th aria-label="Actions">Actions</th></tr></thead>
        <tbody>{purchases.map((purchase) => <tr key={purchase.id} className={purchase.state === 'CANCELLED' ? 'archived-row' : ''}>
          <td>
            <Link className="text-button" to={purchase.state === 'DRAFT' ? `/purchases/new?edit=${purchase.id}` : `/purchases/${purchase.id}`}>
              <strong>{purchase.purchase_number || `Draft #${purchase.id}`}</strong>
            </Link>
          </td>
          <td>{purchase.supplier_name}</td>
          <td>{purchase.invoice_date}</td>
          <td><code>{purchase.supplier_invoice_no || '-'}</code></td>
          <td>{purchase.warehouse_name}</td>
          <td>{money(purchase.taxable_total)}</td>
          <td><strong>{money(purchase.total_amount)}</strong></td>
          <td><span className={STATE_BADGE[purchase.state] || 'type-chip'}>{purchase.state}</span></td>
          <td>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              {purchase.state === 'DRAFT' ? (
                <>
                  <Link
                    className="text-button"
                    to={`/purchases/new?edit=${purchase.id}`}
                    aria-label={`View / Edit draft purchase ${purchase.purchase_number || purchase.id}`}
                  >
                    View / Edit
                  </Link>
                  {isAdmin && (
                    <button
                      type="button"
                      className="text-button"
                      style={{ color: 'var(--red)' }}
                      onClick={() => { setError(''); setSuccess(''); setDraftToDelete(purchase) }}
                      aria-label={`Delete draft purchase ${purchase.purchase_number || purchase.id}`}
                    >
                      Delete
                    </button>
                  )}
                </>
              ) : (
                <Link
                  className="text-button"
                  to={`/purchases/${purchase.id}`}
                  aria-label={`View purchase ${purchase.purchase_number || purchase.id}`}
                >
                  View
                </Link>
              )}
            </div>
          </td>
        </tr>)}</tbody>
      </table></div>}
      <div className="table-meta pager" role="navigation" aria-label="Purchase pagination">
        <button className="pager-button" onClick={() => setPage((c) => Math.max(1, c - 1))} disabled={!hasPrevious || busy}>← Previous</button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} purchases` : ''}</span>
        <button className="pager-button" onClick={() => setPage((c) => c + 1)} disabled={!hasNext || busy}>Next →</button>
      </div>
    </div>

    {draftToDelete && (
      <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="delete-draft-title">
        <div className="modal-dialog">
          <h3 id="delete-draft-title">Delete Draft Purchase</h3>
          <p>
            Are you sure you want to permanently delete draft purchase{' '}
            <strong>{draftToDelete.purchase_number || `Draft #${draftToDelete.id}`}</strong> from supplier{' '}
            <strong>{draftToDelete.supplier_name}</strong>?
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
            <button
              type="button"
              className="quiet-button"
              onClick={() => setDraftToDelete(null)}
              disabled={deleting}
            >
              Cancel
            </button>
            <button
              type="button"
              className="primary-button"
              style={{ background: 'var(--red)' }}
              onClick={handleConfirmDeleteDraft}
              disabled={deleting}
            >
              {deleting ? 'Deleting...' : 'Delete Draft'}
            </button>
          </div>
        </div>
      </div>
    )}
  </section>
}

