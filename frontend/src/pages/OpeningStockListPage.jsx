import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchOpeningStocks } from '../api/openingStock'
import { fetchWarehouses } from '../api/warehouses'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatQuantityWithUnit } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

const REASONS = [
  'Inventory Initialization',
  'Physical Count',
  'Pre-existing Stock',
  'Other',
]

export default function OpeningStockListPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [openingStocks, setOpeningStocks] = useState([])
  const [warehouses, setWarehouses] = useState([])
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
    fetchWarehouses({ is_active: 'true' })
      .then((data) => setWarehouses(Array.isArray(data) ? data : data?.results || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true)
    setError('')
    fetchOpeningStocks({
      page,
      warehouse: warehouseFilter,
      reason: reasonFilter,
      from: fromDate,
      to: toDate,
      search,
    })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setOpeningStocks(Array.isArray(data) ? data : data.results || [])
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
  }, [page, warehouseFilter, reasonFilter, fromDate, toDate, search])

  const totalPages = Math.max(1, Math.ceil(total / 25))
  const filtersActive = search || warehouseFilter || reasonFilter || fromDate || toDate

  function resetFilters() {
    setSearchInput('')
    setSearch('')
    setWarehouseFilter('')
    setReasonFilter('')
    setFromDate('')
    setToDate('')
    setPage(1)
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations</p>
          <h1>Opening Stock</h1>
          <p className="page-subtitle">
            Initial physical stock initialized before StockBill tracking began.
          </p>
        </div>
        {isAdmin && (
          <Link
            className="primary-button"
            to="/inventory/opening-stock/new"
            id="btn-new-opening-stock"
          >
            + New Opening Stock
          </Link>
        )}
      </header>

      <StatusMessage type="error">{error}</StatusMessage>

      {/* Filter toolbar */}
      <div className="table-frame">
        <div className="table-meta" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <span>
            {busy
              ? 'Loading opening stock...'
              : `${total} record${total === 1 ? '' : 's'}`}
          </span>
          <div
            className="filter-row"
            style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}
          >
            <label className="filter-field">
              Search
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Number, product, SKU, note..."
                aria-label="Search opening stock"
              />
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
                <option value="">All Warehouses</option>
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
                <option value="">All Reasons</option>
                {REASONS.map((r) => (
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

            {filtersActive && (
              <button
                type="button"
                className="quiet-button"
                onClick={resetFilters}
                style={{ alignSelf: 'flex-end', height: '2.4rem' }}
              >
                Reset
              </button>
            )}
          </div>
        </div>

        {busy ? (
          <div className="empty-state">Loading opening stock records...</div>
        ) : openingStocks.length === 0 ? (
          <div className="empty-state">
            {filtersActive
              ? 'No opening stock records match your filters.'
              : 'No opening stock entries recorded yet.'}
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Number</th>
                  <th>Date</th>
                  <th>Product</th>
                  <th>Warehouse</th>
                  <th>Entered Quantity</th>
                  <th style={{ textAlign: 'right' }}>Base Quantity</th>
                  <th style={{ textAlign: 'right' }}>Cost / Piece</th>
                  <th style={{ textAlign: 'right' }}>Opening Value</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {openingStocks.map((record) => (
                  <tr key={record.id}>
                    <td>
                      <Link
                        to={`/inventory/opening-stock/${record.id}`}
                        style={{ fontWeight: 600, color: '#2563eb' }}
                      >
                        {record.opening_stock_number}
                      </Link>
                    </td>
                    <td>{record.effective_date}</td>
                    <td>
                      <strong>{record.product_name}</strong>
                      {record.product_sku && (
                        <div style={{ fontSize: '0.8rem', color: '#6b7280' }}>
                          SKU: {record.product_sku}
                        </div>
                      )}
                    </td>
                    <td>
                      {record.warehouse_name} (<code>{record.warehouse_code}</code>)
                    </td>
                    <td>
                      {formatQuantityWithUnit(record.quantity, record.unit)}
                      {record.unit === 'master box' && record.conversion_factor > 1 && (
                        <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>
                          × {record.conversion_factor} pcs/box
                        </div>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <strong>{Number(record.base_quantity).toLocaleString('en-IN')} pcs</strong>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {money(record.cost_per_piece)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <strong>{money(record.opening_value)}</strong>
                    </td>
                    <td>
                      <span className="badge badge-not-set">{record.reason}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > 25 && (
          <div className="table-meta pager" role="navigation" aria-label="Pagination">
            <span>
              Page {page} of {totalPages} ({total} records)
            </span>
            <div className="pager-buttons">
              <button
                type="button"
                className="quiet-button"
                disabled={!hasPrevious}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="quiet-button"
                disabled={!hasNext}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
