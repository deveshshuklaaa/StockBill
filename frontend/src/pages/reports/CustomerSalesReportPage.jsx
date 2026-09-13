import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../../api/client'
import { fetchCustomerSalesReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared from '../../components/ReportsShared'
import { useReportRange, daysAgo, today } from '../../components/ReportsShared'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// POSTED invoices grouped by customer; outstanding is the customer
// model's authoritative all-time balance.
export default function CustomerSalesReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchCustomerSalesReport({ from: range.from, to: range.to })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiForbiddenMessage(err, 'view the customer sales report', 'loading customer sales report')) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range])

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / relationships</p><h1>Customer Sales</h1><p className="page-subtitle">POSTED sales by customer. Outstanding is the customer account's authoritative all-time balance.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.invoice_count : 0} posted invoice${report?.invoice_count === 1 ? '' : 's'} · ${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={apply} />
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Total sales</div><div className="metric-value">{money(report.total_sales)}</div></div>
        <div className="metric-card"><div className="metric-label">Payments received</div><div className="metric-value">{money(report.payment_amount)}</div><div className="metric-hint">{report.payment_count} payment(s) in period</div></div>
      </div>}

      {report && (report.by_customer.length === 0
        ? <div className="empty-state">No posted sales in this period.</div>
        : <div className="table-scroll"><table>
          <thead><tr><th>Customer</th><th style={{ textAlign: 'right' }}>Invoices</th><th style={{ textAlign: 'right' }}>Sales value</th><th style={{ textAlign: 'right' }}>Outstanding (all-time)</th><th aria-label="Actions" /></tr></thead>
          <tbody>{report.by_customer.map((row) => <tr key={row.customer_id || 'walk-in'}>
            <td><strong>{row.is_walk_in ? 'Walk-in customer' : row.customer_name}</strong>{row.is_walk_in && <small>Cash sale without account</small>}</td>
            <td style={{ textAlign: 'right' }}>{row.invoice_count}</td>
            <td style={{ textAlign: 'right' }}>{money(row.sales_value)}</td>
            <td style={{ textAlign: 'right' }}>{row.outstanding_balance != null ? <strong className={Number(row.outstanding_balance) > 0 ? 'balance due' : ''}>{money(row.outstanding_balance)}</strong> : '—'}</td>
            <td>{row.customer_id && <Link className="text-button" to={`/customers/${row.customer_id}`}>View</Link>}</td>
          </tr>)}</tbody>
        </table></div>)}
    </div>
  </section>
}
