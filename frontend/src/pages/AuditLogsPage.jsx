import { useEffect, useRef, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { fetchAuditLogs } from '../api/settings'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

export default function AuditLogsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [logs, setLogs] = useState([])
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [entityTypeFilter, setEntityTypeFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
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
    const requestId = ++latestLoad.current
    setBusy(true); setError('')
    fetchAuditLogs({ page, search, entity_type: entityTypeFilter, action: actionFilter })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setLogs(Array.isArray(data) ? data : data.results || [])
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
  }, [page, search, entityTypeFilter, actionFilter])

  if (!isAdmin) {
    return <section className="page-section">
      <StatusMessage>You do not have permission to view audit logs.</StatusMessage>
    </section>
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Administration</p>
        <h1>Audit Logs</h1>
        <p className="page-subtitle">Complete audit trail of all system actions and changes.</p>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading logs...' : `${total} log entr${total === 1 ? 'y' : 'ies'}`}</span>
        <div className="filter-row">
          <label className="filter-field">
            Search
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Action, entity, or user"
              aria-label="Search audit logs"
            />
          </label>
          <label className="filter-field">
            Entity Type
            <select
              value={entityTypeFilter}
              onChange={(e) => { setEntityTypeFilter(e.target.value); setPage(1) }}
              aria-label="Filter by entity type"
            >
              <option value="">All</option>
              <option value="Product">Product</option>
              <option value="Category">Category</option>
              <option value="Supplier">Supplier</option>
              <option value="PurchaseInvoice">Purchase Invoice</option>
              <option value="TaxRate">Tax Rate</option>
              <option value="BusinessProfile">Business Profile</option>
            </select>
          </label>
          <label className="filter-field">
            Action
            <input
              value={actionFilter}
              onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
              placeholder="e.g. created, updated"
              aria-label="Filter by action"
            />
          </label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading audit logs...</div> : logs.length === 0 ? (
        <div className="empty-state">
          {search || entityTypeFilter || actionFilter ? 'No audit logs match your filters.' : 'No audit logs recorded yet.'}
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>User</th>
                <th>Action</th>
                <th>Entity Type</th>
                <th>Entity ID</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>{new Date(log.created_at).toLocaleString('en-IN')}</td>
                  <td><strong>{log.username || '-'}</strong></td>
                  <td><span className="type-chip">{log.action}</span></td>
                  <td>{log.entity_type}</td>
                  <td><code>{log.entity_id}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-meta pager" role="navigation" aria-label="Audit log pagination">
        <button
          className="pager-button"
          onClick={() => setPage((c) => Math.max(1, c - 1))}
          disabled={!hasPrevious || busy}
        >
          ← Previous
        </button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} logs` : ''}</span>
        <button
          className="pager-button"
          onClick={() => setPage((c) => c + 1)}
          disabled={!hasNext || busy}
        >
          Next →
        </button>
      </div>
    </div>
  </section>
}
