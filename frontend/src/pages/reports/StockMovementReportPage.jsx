import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { fetchStockMovementReport } from '../../api/reports'
import { fetchWarehouses } from '../../api/warehouses'
import StatusMessage from '../../components/StatusMessage'
import { formatQuantity } from '../../utils/format'

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
  STOCK_ADJUSTMENT_IN: 'Stock Adjustment In',
  STOCK_ADJUSTMENT_OUT: 'Stock Adjustment Out',
  TRANSFER_IN: 'Transfer In',
  TRANSFER_OUT: 'Transfer Out',
}

// Read-only aggregate over the append-only StockLedger; totals computed
// server-side across the whole filtered set.
export default function StockMovementReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [warehouses, setWarehouses] = useState([])
  const [warehouse, setWarehouse] = useState('')
  const [movementType, setMovementType] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [reference, setReference] = useState('')

  useEffect(() => {
    fetchWarehouses().then(setWarehouses).catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchStockMovementReport({ warehouse, movementType, from, to, reference })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [warehouse, movementType, from, to, reference])

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / inventory</p><h1>Stock Movement</h1><p className="page-subtitle">Aggregate view over the append-only stock ledger. Line-level history lives in the Stock Ledger screen.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.movement_count : 0} movements`}</span>
        <div className="filter-row">
          <label className="filter-field">Warehouse<select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} aria-label="Filter by warehouse"><option value="">All</option>{warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
          <label className="filter-field">Movement<select value={movementType} onChange={(e) => setMovementType(e.target.value)} aria-label="Filter by movement type"><option value="">All</option>{Object.entries(MOVEMENT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="filter-field">From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" /></label>
          <label className="filter-field">To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" /></label>
          <label className="filter-field">Reference<input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. PI/" aria-label="Filter by reference" /></label>
        </div>
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Movements</div><div className="metric-value">{report.movement_count}</div></div>
        <div className="metric-card"><div className="metric-label">Inflow</div><div className="metric-value">+{formatQuantity(report.inflow, 'piece')}</div></div>
        <div className="metric-card"><div className="metric-label">Outflow</div><div className="metric-value">{formatQuantity(report.outflow, 'piece')}</div></div>
        <div className="metric-card"><div className="metric-label">Net quantity</div><div className="metric-value">{formatQuantity(report.net_quantity, 'piece')}</div></div>
      </div>}

      {report && report.by_movement_type.length > 0 && <div className="table-scroll"><table>
        <thead><tr><th>Movement type</th><th style={{ textAlign: 'right' }}>Count</th><th style={{ textAlign: 'right' }}>Net quantity</th></tr></thead>
        <tbody>{report.by_movement_type.map((row) => <tr key={row.movement_type}>
          <td><span className="type-chip">{MOVEMENT_LABELS[row.movement_type] || row.movement_type}</span></td>
          <td style={{ textAlign: 'right' }}>{row.movement_count}</td>
          <td style={{ textAlign: 'right' }}><strong>{formatQuantity(row.net_quantity, 'piece')}</strong></td>
        </tr>)}</tbody>
      </table></div>}
    </div>
  </section>
}
