import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { fetchProductSalesReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared from '../../components/ReportsShared'
import { useReportRange, daysAgo, today } from '../../components/ReportsShared'
import { formatQuantityWithUnit } from '../../utils/format'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// POSTED lines only; COGS is the historical snapshot — current cost/WAC
// never restates old sales.
export default function ProductSalesReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchProductSalesReport({ from: range.from, to: range.to })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range])

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / sales</p><h1>Product Sales</h1><p className="page-subtitle">Per-product sales with historical COGS — cost is the snapshot taken at sale time, never today's WAC.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.products.length : 0} product${report?.products?.length === 1 ? '' : 's'} · ${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={apply} />
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Total sales value</div><div className="metric-value">{money(report.total_revenue)}</div></div>
        <div className="metric-card"><div className="metric-label">Total COGS</div><div className="metric-value">{money(report.total_cogs)}</div></div>
        <div className="metric-card"><div className="metric-label">Total gross profit</div><div className="metric-value">{money(report.total_gross_profit)}</div></div>
      </div>}

      {report && (report.products.length === 0
        ? <div className="empty-state">No posted sales in this period.</div>
        : <div className="table-scroll"><table>
          <thead><tr><th>Product</th><th style={{ textAlign: 'right' }}>Qty sold</th><th style={{ textAlign: 'right' }}>Discounts</th><th style={{ textAlign: 'right' }}>Taxable</th><th style={{ textAlign: 'right' }}>GST</th><th style={{ textAlign: 'right' }}>Sales value</th><th style={{ textAlign: 'right' }}>COGS</th><th style={{ textAlign: 'right' }}>Gross profit</th><th style={{ textAlign: 'right' }}>Margin</th></tr></thead>
          <tbody>{report.products.map((row) => <tr key={row.product_id}>
            <td><strong>{row.product_name}</strong><small>{row.variant_snapshot}</small></td>
            <td style={{ textAlign: 'right' }}>{formatQuantityWithUnit(row.quantity_sold, row.base_unit)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.discounts)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.taxable_sales)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.gst)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.sales_value)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.cogs)}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(row.gross_profit)}</strong></td>
            <td style={{ textAlign: 'right' }}>{row.margin_percent != null ? `${row.margin_percent}%` : '—'}</td>
          </tr>)}</tbody>
        </table></div>)}
    </div>
  </section>
}
