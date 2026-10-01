import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchWarehouses } from '../api/purchases'
import { fetchTransfers } from '../api/transfers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatQuantityWithUnit } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const REASONS_ALL = [
  'Stock Replenishment',
  'Inter-branch Transfer',
  'Order Fulfillment',
  'Excess Stock Rebalancing',
  'Other',
]

export default function WarehouseTransfersPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [transfers, setTransfers] = useState([])
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
    fetchWarehouses()
      .then((data) => setWarehouses(data || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true)
    setError('')
    fetchTransfers({
      page,
      warehouse: warehouseFilter,
      reason: reasonFilter,
      from: fromDate,
      to: toDate,
      search,
    })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setTransfers(Array.isArray(data) ? data : data.results || [])
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

  const handleResetFilters = () => {
    setWarehouseFilter('')
    setReasonFilter('')
    setFromDate('')
    setToDate('')
    setSearchInput('')
    setSearch('')
    setPage(1)
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations</p>
          <h1>Warehouse Transfers</h1>
          <p className="page-subtitle">
            Inter-warehouse atomic stock transfers with preserved total valuation.
          </p>
        </div>
        {isAdmin && (
          <Link className="primary-button" to="/inventory/transfers/new">
            + New Transfer
          </Link>
        )}
      </header>

      <StatusMessage>{error}</StatusMessage>

      <div className="table-frame">
        <div className="table-meta">
          <span>
            {busy ? 'Loading transfers...' : `${total} transfer${total === 1 ? '' : 's'}`}
          </span>
          <div className="table-filters" style={{ flexWrap: 'wrap', gap: '8px' }}>
            <input
              type="text"
              placeholder="Search transfer #, product, warehouse..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              style={{ width: '220px' }}
            />
            <select
              value={warehouseFilter}
              onChange={(e) => {
                setWarehouseFilter(e.target.value)
                setPage(1)
              }}
            >
              <option value="">All Warehouses</option>
              {warehouses.map((wh) => (
                <option key={wh.id} value={wh.id}>
                  {wh.name} ({wh.code})
                </option>
              ))}
            </select>
            <select
              value={reasonFilter}
              onChange={(e) => {
                setReasonFilter(e.target.value)
                setPage(1)
              }}
            >
              <option value="">All Reasons</option>
              {REASONS_ALL.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <input
              type="date"
              title="From date"
              value={fromDate}
              onChange={(e) => {
                setFromDate(e.target.value)
                setPage(1)
              }}
            />
            <input
              type="date"
              title="To date"
              value={toDate}
              onChange={(e) => {
                setToDate(e.target.value)
                setPage(1)
              }}
            />
            {(warehouseFilter || reasonFilter || fromDate || toDate || search) && (
              <button
                type="button"
                className="quiet-button"
                style={{ border: '1px solid #cbd5cd' }}
                onClick={handleResetFilters}
              >
                Reset
              </button>
            )}
          </div>
        </div>

        {busy ? (
          <div className="empty-state">Loading warehouse transfers...</div>
        ) : transfers.length === 0 ? (
          <div className="empty-state">
            <p>No warehouse transfers found.</p>
            {isAdmin && (
              <Link className="primary-button" to="/inventory/transfers/new" style={{ marginTop: '8px' }}>
                Create First Transfer
              </Link>
            )}
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Transfer #</th>
                  <th>Date</th>
                  <th>Product</th>
                  <th>Source</th>
                  <th>Destination</th>
                  <th style={{ textAlign: 'right' }}>Entered Qty</th>
                  <th style={{ textAlign: 'right' }}>Base Qty</th>
                  <th style={{ textAlign: 'right' }}>Cost / Pcs</th>
                  <th style={{ textAlign: 'right' }}>Transfer Value</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {transfers.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link
                        to={`/inventory/transfers/${item.id}`}
                        style={{ fontWeight: 600, color: '#1e382b' }}
                      >
                        {item.transfer_number}
                      </Link>
                    </td>
                    <td>{item.effective_date}</td>
                    <td>
                      <div>
                        <strong>{item.product_name}</strong>
                        {item.product_sku && (
                          <span style={{ display: 'block', fontSize: '11px', color: '#667d70' }}>
                            {item.product_sku}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className="type-chip" style={{ background: '#fef3f2', color: '#b42318' }}>
                        {item.source_warehouse_code || item.source_warehouse_name}
                      </span>
                    </td>
                    <td>
                      <span className="type-chip" style={{ background: '#ecfdf3', color: '#027a48' }}>
                        {item.destination_warehouse_code || item.destination_warehouse_name}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {Number(item.quantity).toLocaleString()} {item.unit}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>
                      {formatQuantityWithUnit(item.base_quantity, 'piece')}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {money(item.unit_cost_snapshot)}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>
                      {money(item.transfer_value)}
                    </td>
                    <td>
                      <span style={{ fontSize: '12px' }}>{item.reason}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <footer className="table-pagination">
          <span>
            Page {page} of {totalPages}
          </span>
          <div className="table-pagination-actions">
            <button
              type="button"
              className="quiet-button"
              disabled={!hasPrevious || busy}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="quiet-button"
              disabled={!hasNext || busy}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </footer>
      </div>
    </section>
  )
}
