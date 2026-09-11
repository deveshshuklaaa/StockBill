import { useEffect, useRef, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { fetchStockLedger } from '../api/inventory'
import { fetchWarehouses } from '../api/warehouses'
import StatusMessage from '../components/StatusMessage'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }
function qty(value) { return Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 3 }) }

const MOVEMENT_LABELS = {
  OPENING_STOCK: 'Opening Stock',
  PURCHASE: 'Purchase',
  PURCHASE_REVERSAL: 'Purchase Reversal',
  SALE: 'Sale',
  SALE_REVERSAL: 'Sale Reversal',
  SALES_RETURN: 'Sales Return',
  PURCHASE_RETURN: 'Purchase Return',
  DAMAGE: 'Damage',
  ADJUSTMENT: 'Adjustment',
  TRANSFER_IN: 'Transfer In',
  TRANSFER_OUT: 'Transfer Out',
}

export default function StockLedgerPage() {
  const [movements, setMovements] = useState([])
  const [warehouses, setWarehouses] = useState([])
  const [warehouseFilter, setWarehouseFilter] = useState('')
  const [movementTypeFilter, setMovementTypeFilter] = useState('')
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
    fetchWarehouses().then(setWarehouses).catch(() => {})
  }, [])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true); setError('')
    fetchStockLedger({ page, warehouse: warehouseFilter, movement_type: movementTypeFilter, reference: search })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setMovements(Array.isArray(data) ? data : data.results || [])
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
  }, [page, warehouseFilter, movementTypeFilter, search])

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Stock management / movement history</p>
        <h1>Stock Ledger</h1>
        <p className="page-subtitle">Complete history of all stock movements across products and warehouses.</p>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading movements...' : `${total} movement${total === 1 ? '' : 's'}`}</span>
        <div className="filter-row">
          <label className="filter-field">
            Reference
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="PI no, invoice no"
              aria-label="Search by reference"
            />
          </label>
          <label className="filter-field">
            Warehouse
            <select
              value={warehouseFilter}
              onChange={(e) => { setWarehouseFilter(e.target.value); setPage(1) }}
              aria-label="Filter by warehouse"
            >
              <option value="">All</option>
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </label>
          <label className="filter-field">
            Movement Type
            <select
              value={movementTypeFilter}
              onChange={(e) => { setMovementTypeFilter(e.target.value); setPage(1) }}
              aria-label="Filter by movement type"
            >
              <option value="">All</option>
              {Object.entries(MOVEMENT_LABELS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading movements...</div> : movements.length === 0 ? (
        <div className="empty-state">
          {search || warehouseFilter || movementTypeFilter ? 'No movements match your filters.' : 'No stock movements recorded yet.'}
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Date/Time</th>
                <th>Product</th>
                <th>SKU</th>
                <th>Type</th>
                <th>Reference</th>
                <th>Warehouse</th>
                <th style={{ textAlign: 'right' }}>Qty Change</th>
                <th style={{ textAlign: 'right' }}>Unit Cost</th>
                <th>User</th>
              </tr>
            </thead>
            <tbody>
              {movements.map((movement) => {
                const isReversal = movement.movement_type.includes('REVERSAL')
                return (
                  <tr key={movement.id} className={isReversal ? 'archived-row' : ''}>
                    <td>{new Date(movement.created_at).toLocaleString('en-IN')}</td>
                    <td><strong>{movement.product_name}</strong></td>
                    <td><code>{movement.product_sku || '-'}</code></td>
                    <td>
                      <span className={isReversal ? 'state-cancelled' : 'type-chip'}>
                        {MOVEMENT_LABELS[movement.movement_type] || movement.movement_type}
                      </span>
                    </td>
                    <td><code>{movement.reference || '-'}</code></td>
                    <td>{movement.warehouse_name}</td>
                    <td style={{ textAlign: 'right', color: Number(movement.quantity_change) >= 0 ? '#16a34a' : '#dc2626' }}>
                      <strong>{Number(movement.quantity_change) >= 0 ? '+' : ''}{qty(movement.quantity_change)}</strong>
                    </td>
                    <td style={{ textAlign: 'right' }}>{movement.unit_cost ? money(movement.unit_cost) : '-'}</td>
                    <td>{movement.created_by_username || '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-meta pager" role="navigation" aria-label="Ledger pagination">
        <button
          className="pager-button"
          onClick={() => setPage((c) => Math.max(1, c - 1))}
          disabled={!hasPrevious || busy}
        >
          ← Previous
        </button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} movements` : ''}</span>
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
