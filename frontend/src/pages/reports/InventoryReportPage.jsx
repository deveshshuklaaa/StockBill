import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { fetchInventoryReport } from '../../api/reports'
import { fetchWarehouses } from '../../api/warehouses'
import StatusMessage from '../../components/StatusMessage'
import { formatQuantity } from '../../utils/format'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// Value = InventoryBalance.quantity_on_hand Ã— average_cost (authoritative WAC).
export default function InventoryReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [warehouses, setWarehouses] = useState([])
  const [warehouse, setWarehouse] = useState('')
  const [isActive, setIsActive] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    fetchWarehouses().then(setWarehouses).catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchInventoryReport({ warehouse, isActive, search })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [warehouse, isActive, search])

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / inventory</p><h1>Stock Valuation</h1><p className="page-subtitle">Inventory value = quantity on hand Ã— weighted-average cost, exactly as the inventory service maintains it.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.product_count : 0} product${report?.product_count === 1 ? '' : 's'} in stock`}</span>
        <div className="filter-row">
          <label className="filter-field">Warehouse<select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} aria-label="Filter by warehouse"><option value="">All</option>{warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
          <label className="filter-field">Status<select value={isActive} onChange={(e) => setIsActive(e.target.value)} aria-label="Filter by status"><option value="">All</option><option value="true">Active</option><option value="false">Archived</option></select></label>
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Product name or SKU" aria-label="Search products" /></label>
        </div>
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Quantity on hand</div><div className="metric-value">{formatQuantity(report.quantity_on_hand, 'piece')}</div></div>
        <div className="metric-card"><div className="metric-label">Total inventory value</div><div className="metric-value">{money(report.total_value)}</div><div className="metric-hint">At weighted-average cost</div></div>
      </div>}

      {report && report.by_warehouse.length > 0 && <div className="table-scroll"><table>
        <thead><tr><th>Warehouse</th><th style={{ textAlign: 'right' }}>Products</th><th style={{ textAlign: 'right' }}>Quantity</th><th style={{ textAlign: 'right' }}>Value (WAC)</th></tr></thead>
        <tbody>{report.by_warehouse.map((row) => <tr key={row.warehouse_id}>
          <td><strong>{row.warehouse_name}</strong><small>{row.warehouse_code}</small></td>
          <td style={{ textAlign: 'right' }}>{row.product_count}</td>
          <td style={{ textAlign: 'right' }}>{formatQuantity(row.quantity, 'piece')}</td>
          <td style={{ textAlign: 'right' }}><strong>{money(row.value)}</strong></td>
        </tr>)}</tbody>
      </table></div>}
    </div>
  </section>
}
