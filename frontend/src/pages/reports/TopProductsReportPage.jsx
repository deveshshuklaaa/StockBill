import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { fetchTopProductsReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared from '../../components/ReportsShared'
import { useReportRange, daysAgo, today } from '../../components/ReportsShared'
import { formatQuantity } from '../../utils/format'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// POSTED-lines ranking; current inventory is never a sales proxy.
export default function TopProductsReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sortBy, setSortBy] = useState('quantity')
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })
  const [sortFilter, setSortFilter] = useState('quantity')

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchTopProductsReport({ from: range.from, to: range.to, sortBy: sortFilter })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range, sortFilter])

  function applyAll() {
    apply()
    setSortFilter(sortBy)
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / sales</p><h1>Top Products</h1><p className="page-subtitle">Ranking of posted sales by quantity, revenue, or gross profit for the period.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.products.length : 0} ranked product${report?.products?.length === 1 ? '' : 's'} · ${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={applyAll}>
          <label className="filter-field">Rank by<select value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="Rank products by"><option value="quantity">Quantity sold</option><option value="revenue">Sales value</option><option value="profit">Gross profit</option></select></label>
        </ReportsShared>
      </div>

      {report && (report.products.length === 0
        ? <div className="empty-state">No posted sales in this period.</div>
        : <div className="table-scroll"><table>
          <thead><tr><th>Rank</th><th>Product</th><th style={{ textAlign: 'right' }}>Quantity</th><th style={{ textAlign: 'right' }}>Revenue</th><th style={{ textAlign: 'right' }}>COGS</th><th style={{ textAlign: 'right' }}>Gross profit</th></tr></thead>
          <tbody>{report.products.map((row) => <tr key={row.product_id}>
            <td><strong>#{row.rank}</strong></td>
            <td><strong>{row.product_name}</strong><small>{row.variant_snapshot}</small></td>
            <td style={{ textAlign: 'right' }}>{formatQuantity(row.total_quantity, 'piece')}</td>
            <td style={{ textAlign: 'right' }}>{money(row.total_revenue)}</td>
            <td style={{ textAlign: 'right' }}>{money(row.total_cogs)}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(row.total_profit)}</strong></td>
          </tr>)}</tbody>
        </table></div>)}
    </div>
  </section>
}
