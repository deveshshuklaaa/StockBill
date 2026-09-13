import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import { fetchDashboard } from '../api/reports'
import StatusMessage from '../components/StatusMessage'
import { daysAgo, today } from '../components/ReportsShared'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }
function qty(value) { return Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 3 }) }

// Every number comes from the tested /reports/dashboard endpoint; each
// card links into the corresponding report. No fabricated graphs.
export default function DashboardPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [from, setFrom] = useState(daysAgo(30))
  const [to, setTo] = useState(today())
  const [range, setRange] = useState({ from: daysAgo(30), to: today() })

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchDashboard(range)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setError(apiForbiddenMessage(err, 'view the dashboard', 'loading dashboard')) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range])

  const todayData = data?.today
  const inventory = data?.inventory
  const period = data?.period

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Management / overview</p><h1>Dashboard</h1><p className="page-subtitle">Concise overview backed by the report endpoints. Click a card for the full report.</p></div>
      <div className="filter-row">
        <label className="filter-field">From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Period from" /></label>
        <label className="filter-field">To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Period to" /></label>
        <button type="button" className="quiet-button" onClick={() => setRange({ from, to })}>Apply</button>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    {busy && !data && <div className="empty-state">Loading dashboard...</div>}

    {data && <div className="metric-grid">
      <Link className="metric-card linked" to={`/reports/sales?from=${today}&to=${today}`}>
        <div className="metric-label">Today's sales</div>
        <div className="metric-value">{money(todayData.net_sales)}</div>
        <div className="metric-hint">{todayData.invoice_count} posted invoice(s)</div>
      </Link>
      <Link className="metric-card linked" to={`/reports/purchases?from=${today}&to=${today}`}>
        <div className="metric-label">Today's purchases</div>
        <div className="metric-value">{money(todayData.purchase_value)}</div>
        <div className="metric-hint">{todayData.purchase_count} posted purchase(s)</div>
      </Link>
      <Link className="metric-card linked" to="/reports/inventory">
        <div className="metric-label">Inventory value</div>
        <div className="metric-value">{money(inventory.total_value)}</div>
        <div className="metric-hint">{inventory.product_count} product(s) in stock</div>
      </Link>
      <Link className="metric-card linked" to="/reports/customers">
        <div className="metric-label">Customer outstanding</div>
        <div className="metric-value">{money(data.customer_outstanding_total)}</div>
        <div className="metric-hint">{data.active_customers} active customer(s)</div>
      </Link>
      <div className="metric-card">
        <div className="metric-label">Active suppliers</div>
        <div className="metric-value">{data.active_suppliers}</div>
        <div className="metric-hint">Supplier settlement is outside StockBill</div>
      </div>
      <Link className="metric-card linked" to={`/reports/profit?from=${range.from}&to=${range.to}`}>
        <div className="metric-label">Gross profit (period)</div>
        <div className="metric-value">{money(period.gross_profit)}</div>
        <div className="metric-hint">Revenue {money(period.revenue)} · COGS {money(period.cogs)}</div>
      </Link>
    </div>}

    {data && (data.low_stock.length > 0 || data.recent_sales.length > 0 || data.recent_purchases.length > 0) && <div className="dashboard-columns">
      {data.low_stock.length > 0 && <div className="table-frame">
        <div className="table-meta"><span>Stock alerts</span><Link className="text-button" to="/inventory">Inventory →</Link></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Product</th><th style={{ textAlign: 'right' }}>On hand</th><th style={{ textAlign: 'right' }}>Threshold</th></tr></thead>
          <tbody>{data.low_stock.map((row) => <tr key={row.id} className="archived-row">
            <td><strong>{row.name}</strong></td>
            <td style={{ textAlign: 'right' }}>{qty(row.current_stock)}</td>
            <td style={{ textAlign: 'right' }}>{qty(row.low_stock_threshold)}</td>
          </tr>)}</tbody>
        </table></div>
      </div>}

      {data.recent_sales.length > 0 && <div className="table-frame">
        <div className="table-meta"><span>Recent sales</span><Link className="text-button" to="/invoices">Invoices →</Link></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Invoice</th><th>Customer</th><th style={{ textAlign: 'right' }}>Total</th></tr></thead>
          <tbody>{data.recent_sales.map((row) => <tr key={row.id}>
            <td><Link className="text-button" to={`/invoices/${row.id}`}>{row.invoice_number}</Link></td>
            <td>{row.customer_name_snapshot || 'Walk-in customer'}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(row.total_amount)}</strong></td>
          </tr>)}</tbody>
        </table></div>
      </div>}

      {data.recent_purchases.length > 0 && <div className="table-frame">
        <div className="table-meta"><span>Recent purchases</span><Link className="text-button" to="/purchases">Purchases →</Link></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Purchase</th><th>Supplier</th><th style={{ textAlign: 'right' }}>Total</th></tr></thead>
          <tbody>{data.recent_purchases.map((row) => <tr key={row.id}>
            <td><Link className="text-button" to={`/purchases/${row.id}`}>{row.purchase_number || `Draft #${row.id}`}</Link></td>
            <td>{row.supplier_name_snapshot}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(row.total_amount)}</strong></td>
          </tr>)}</tbody>
        </table></div>
      </div>}

      {data.top_products.length > 0 && <div className="table-frame">
        <div className="table-meta"><span>Top sellers (period)</span><Link className="text-button" to={`/reports/top-products?from=${range.from}&to=${range.to}`}>Full ranking →</Link></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Product</th><th style={{ textAlign: 'right' }}>Qty</th><th style={{ textAlign: 'right' }}>Revenue</th></tr></thead>
          <tbody>{data.top_products.map((row) => <tr key={row.product_id}>
            <td><strong>{row.product_name}</strong></td>
            <td style={{ textAlign: 'right' }}>{qty(row.total_quantity)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.total_revenue)}</td>
          </tr>)}</tbody>
        </table></div>
      </div>}
    </div>}
  </section>
}
