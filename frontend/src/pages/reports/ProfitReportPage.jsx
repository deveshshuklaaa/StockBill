import { useEffect, useState } from 'react'
import { apiErrorMessage, apiForbiddenMessage } from '../../api/client'
import { fetchProfitReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared from '../../components/ReportsShared'
import { useReportRange, daysAgo, today } from '../../components/ReportsShared'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// Revenue − historical COGS snapshots = gross profit. Admin only.
export default function ProfitReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchProfitReport({ from: range.from, to: range.to })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiForbiddenMessage(err, 'view the profit report', 'loading profit report')) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range])

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / finance</p><h1>Profit &amp; Margin</h1><p className="page-subtitle">Gross profit = POSTED revenue − historical COGS snapshots. Cancelled sales and drafts are excluded; today's cost never restates old sales.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={apply} />
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Revenue</div><div className="metric-value">{money(report.revenue)}</div></div>
        <div className="metric-card"><div className="metric-label">Cost of goods sold</div><div className="metric-value">{money(report.cogs)}</div><div className="metric-hint">Historical snapshots</div></div>
        <div className="metric-card"><div className="metric-label">Gross profit</div><div className="metric-value">{money(report.gross_profit)}</div></div>
        <div className="metric-card"><div className="metric-label">Gross margin</div><div className="metric-value">{report.gross_margin_percent != null ? `${report.gross_margin_percent}%` : '—'}</div></div>
      </div>}

      {report && (report.by_product.length === 0
        ? <div className="empty-state">No posted sales in this period.</div>
        : <div className="table-scroll"><table>
          <thead><tr><th>Product</th><th style={{ textAlign: 'right' }}>Revenue</th><th style={{ textAlign: 'right' }}>COGS</th><th style={{ textAlign: 'right' }}>Gross profit</th></tr></thead>
          <tbody>{report.by_product.map((row) => <tr key={row.product_id}>
            <td><strong>{row.product_name}</strong></td>
            <td style={{ textAlign: 'right' }}>{money(row.revenue)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.cogs)}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(row.gross_profit)}</strong></td>
          </tr>)}</tbody>
        </table></div>)}
    </div>
  </section>
}
