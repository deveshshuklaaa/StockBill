import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAdjustments } from '../api/adjustments'
import { apiErrorMessage } from '../api/client'
import { fetchWarehouses } from '../api/purchases'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatQuantityWithUnit } from '../utils/format'

function money(value) {
  return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
}

const TYPE_BADGE = {
  STOCK_ADJUSTMENT_IN: 'tax-chip',
  STOCK_ADJUSTMENT_OUT: 'state-cancelled',
}

const REASONS_ALL = [
  'Physical Count Increase',
  'Found Stock',
  'Physical Count Decrease',
  'Damaged',
  'Expired',
  'Missing/Short',
  'Other',
]

export default function StockAdjustmentsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [adjustments, setAdjustments] = useState([])
  const [warehouses, setWarehouses] = useState([])
  const [typeFilter, setTypeFilter] = useState('')
  const [warehouseFilter, setWarehouseFilter] = useState('')
  const [reasonFilter, setReasonFilter] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
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
    const timer = setTimeout(() => {
      setSearch(searchInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    fetchWarehouses()
      .then((data) => setWarehouses(data || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true)
    setError('')
    fetchAdjustments({
      page,
      type: typeFilter,
      warehouse: warehouseFilter,
      reason: reasonFilter,
      from: fromDate,
      to: toDate,
      search,
    })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setAdjustments(Array.isArray(data) ? data : data.results || [])
        setTotal(Number(data.count ?? 0))
        setHasNext(Boolean(data.next))
        setHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestLoad.current) return
        if (err?.response?.status === 404 && page > 1) {
          setPage(1)
          return
        }
        setError(apiErrorMessage(err))
      })
      .finally(() => {
        if (requestId === latestLoad.current) setBusy(false)
      })
  }, [page, typeFilter, warehouseFilter, reasonFilter, fromDate, toDate, search])

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations</p>
          <h1>Stock Adjustments</h1>
          <p className="page-subtitle">
            Controlled physical inventory corrections, stock counts, damages, and write-offs.
          </p>
        </div>
        {isAdmin && (
          <Link className="primary-button" to="/inventory/adjustments/new">
            + New Adjustment
          </Link>
        )}
      </header>
      <StatusMessage>{error}</StatusMessage>

      <div className="table-frame">
        <div className="table-meta">
          <span>
            {busy ? 'Loading adjustments...' : `${total} adjustment${total === 1 ? '' : 's'}`}
          </span>
          <div className="filter-row">
            <label className="filter-field">
              Search
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="ADJ no, product, note..."
                aria-label="Search adjustments"
              />
            </label>
            <label className="filter-field">
              Type
              <select
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by type"
              >
                <option value="">All</option>
                <option value="STOCK_ADJUSTMENT_IN">+ Increase (IN)</option>
                <option value="STOCK_ADJUSTMENT_OUT">- Decrease (OUT)</option>
              </select>
            </label>
            <label className="filter-field">
              Warehouse
              <select
                value={warehouseFilter}
                onChange={(e) => {
                  setWarehouseFilter(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by warehouse"
              >
                <option value="">All</option>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              Reason
              <select
                value={reasonFilter}
                onChange={(e) => {
                  setReasonFilter(e.target.value)
                  setPage(1)
                }}
                aria-label="Filter by reason"
              >
                <option value="">All</option>
                {REASONS_ALL.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              From
              <input
                type="date"
                value={fromDate}
                onChange={(e) => {
                  setFromDate(e.target.value)
                  setPage(1)
                }}
                aria-label="From date"
              />
            </label>
            <label className="filter-field">
              To
              <input
                type="date"
                value={toDate}
                onChange={(e) => {
                  setToDate(e.target.value)
                  setPage(1)
                }}
                aria-label="To date"
              />
            </label>
          </div>
        </div>

        {busy ? (
          <div className="empty-state">Loading adjustments...</div>
        ) : adjustments.length === 0 ? (
          <div className="empty-state">
            {search || typeFilter || warehouseFilter || reasonFilter || fromDate || toDate
              ? 'No adjustments match your filters.'
              : 'No stock adjustments recorded yet.'}
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Adjustment No.</th>
                  <th>Date</th>
                  <th>Product</th>
                  <th>Warehouse</th>
                  <th>Type</th>
                  <th style={{ textAlign: 'right' }}>Entered Qty</th>
                  <th style={{ textAlign: 'right' }}>Base Pieces</th>
                  <th style={{ textAlign: 'right' }}>Unit Cost</th>
                  <th style={{ textAlign: 'right' }}>Value</th>
                  <th>Reason</th>
                  <th>Created By</th>
                </tr>
              </thead>
              <tbody>
                {adjustments.map((adj) => {
                  const isIn = adj.adjustment_type === 'STOCK_ADJUSTMENT_IN'
                  return (
                    <tr key={adj.id}>
                      <td>
                        <Link to={`/inventory/adjustments/${adj.id}`}>
                          <strong>{adj.adjustment_number}</strong>
                        </Link>
                      </td>
                      <td>{adj.effective_date}</td>
                      <td>
                        <div>
                          <strong>{adj.product_name}</strong>
                          {adj.product_sku && (
                            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>
                              SKU: {adj.product_sku}
                            </span>
                          )}
                        </div>
                      </td>
                      <td>{adj.warehouse_name}</td>
                      <td>
                        <span className={TYPE_BADGE[adj.adjustment_type] || 'type-chip'}>
                          {isIn ? '+ IN' : '- OUT'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQuantityWithUnit(adj.quantity, adj.unit)}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <strong>{formatQuantityWithUnit(adj.base_quantity, 'piece')}</strong>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {money(adj.cost_per_base_unit_snapshot)}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <strong>{money(adj.adjustment_value)}</strong>
                      </td>
                      <td>
                        <span>{adj.reason}</span>
                        {adj.note && (
                          <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>
                            {adj.note}
                          </span>
                        )}
                      </td>
                      <td>{adj.created_by_username || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="table-meta pager" role="navigation" aria-label="Adjustment pagination">
          <button
            className="pager-button"
            onClick={() => setPage((c) => Math.max(1, c - 1))}
            disabled={!hasPrevious || busy}
          >
            ← Previous
          </button>
          <span>
            Page {page} of {totalPages}
            {total > 0 ? ` · ${total} adjustments` : ''}
          </span>
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
  )
}
