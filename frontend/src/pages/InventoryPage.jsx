import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchInventoryBalances } from '../api/inventory'
import { fetchWarehouses } from '../api/warehouses'
import StatusMessage from '../components/StatusMessage'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }
function qty(value) { return Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 3 }) }

function formatAttributes(attributes) {
  if (!attributes || Object.keys(attributes).length === 0) return null
  const parts = []
  if (attributes.net_weight) parts.push(`${attributes.net_weight}${attributes.net_weight_unit || ''}`)
  if (attributes.units_per_master_box) parts.push(`${attributes.units_per_master_box} per M.Box`)
  return parts.join(' · ')
}

export default function InventoryPage() {
  const [inventory, setInventory] = useState([])
  const [warehouses, setWarehouses] = useState([])
  const [warehouseFilter, setWarehouseFilter] = useState('')
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
    fetchInventoryBalances({ page, warehouse: warehouseFilter, search })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setInventory(Array.isArray(data) ? data : data.results || [])
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
  }, [page, warehouseFilter, search])

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Stock management</p>
        <h1>Inventory</h1>
        <p className="page-subtitle">Current stock levels, weighted-average cost, and inventory valuation by warehouse.</p>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading inventory...' : `${total} product${total === 1 ? '' : 's'} in stock`}</span>
        <div className="filter-row">
          <label className="filter-field">
            Search
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Product name or SKU"
              aria-label="Search inventory"
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
        </div>
      </div>
      {busy ? <div className="empty-state">Loading inventory...</div> : inventory.length === 0 ? (
        <div className="empty-state">
          {search || warehouseFilter ? 'No inventory matches your filters.' : 'No inventory balances recorded yet.'}
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>SKU</th>
                <th>Category</th>
                <th>MRP</th>
                <th>Warehouse</th>
                <th style={{ textAlign: 'right' }}>Stock</th>
                <th>Unit</th>
                <th style={{ textAlign: 'right' }}>Avg Cost</th>
                <th style={{ textAlign: 'right' }}>Stock Value</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {inventory.map((item) => {
                const stockValue = Number(item.quantity_on_hand) * Number(item.average_cost)
                const attrs = formatAttributes(item.product_attributes)
                return (
                  <tr key={item.id} className={!item.product_is_active ? 'archived-row' : ''}>
                    <td>
                      <Link to={`/inventory/${item.product}`}>
                        <strong>{item.product_name}</strong>
                        {attrs && <div style={{ fontSize: '0.875rem', color: '#666' }}>{attrs}</div>}
                      </Link>
                    </td>
                    <td><code>{item.product_sku || '-'}</code></td>
                    <td>{item.product_category_name || '-'}</td>
                    <td>{item.product_mrp ? money(item.product_mrp) : '-'}</td>
                    <td>{item.warehouse_name}</td>
                    <td style={{ textAlign: 'right' }}><strong>{qty(item.quantity_on_hand)}</strong></td>
                    <td>{item.product_base_unit}</td>
                    <td style={{ textAlign: 'right' }}>{money(item.average_cost)}</td>
                    <td style={{ textAlign: 'right' }}><strong>{money(stockValue)}</strong></td>
                    <td>
                      <span className={item.product_is_active ? 'tax-chip' : 'state-cancelled'}>
                        {item.product_is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-meta pager" role="navigation" aria-label="Inventory pagination">
        <button
          className="pager-button"
          onClick={() => setPage((c) => Math.max(1, c - 1))}
          disabled={!hasPrevious || busy}
        >
          ← Previous
        </button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} products` : ''}</span>
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
