import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { fetchCustomers } from '../../api/customers'
import { fetchSalesReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared, { useReportRange, daysAgo, today } from '../../components/ReportsShared'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// POSTED invoices only; DRAFT/CANCELLED excluded from active sales.
export default function SalesReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [customers, setCustomers] = useState([])
  const [customer, setCustomer] = useState('')
  const [paymentType, setPaymentType] = useState('')
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })
  const [filters, setFilters] = useState({ customer: '', paymentType: '' })

  useEffect(() => {
    fetchCustomers({ page: 1 }).then((data) => setCustomers(data.results || [])).catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchSalesReport({ from: range.from, to: range.to, customer: filters.customer, paymentType: filters.paymentType })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range, filters])

  function applyAll() {
    apply()
    setFilters({ customer, paymentType })
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / sales</p><h1>Sales Summary</h1><p className="page-subtitle">POSTED invoices only — drafts and cancelled sales are excluded from active totals.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.invoice_count : 0} posted invoice${report?.invoice_count === 1 ? '' : 's'} · ${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={applyAll}>
          <label className="filter-field">Customer<select value={customer} onChange={(e) => setCustomer(e.target.value)} aria-label="Filter by customer"><option value="">All</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label className="filter-field">Payment<select value={paymentType} onChange={(e) => setPaymentType(e.target.value)} aria-label="Filter by payment type"><option value="">All</option><option value="cash">Cash</option><option value="credit">Credit</option></select></label>
        </ReportsShared>
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Gross sales</div><div className="metric-value">{money(report.gross_sales)}</div></div>
        <div className="metric-card"><div className="metric-label">Discounts</div><div className="metric-value">{money(report.discounts)}</div></div>
        <div className="metric-card"><div className="metric-label">Taxable sales</div><div className="metric-value">{money(report.taxable_sales)}</div></div>
        <div className="metric-card"><div className="metric-label">GST collected</div><div className="metric-value">{money(report.gst)}</div></div>
        <div className="metric-card"><div className="metric-label">Net sales</div><div className="metric-value">{money(report.net_sales)}</div></div>
        <div className="metric-card"><div className="metric-label">COGS</div><div className="metric-value">{money(report.cogs)}</div></div>
        <div className="metric-card"><div className="metric-label">Gross profit</div><div className="metric-value">{money(report.gross_profit)}</div></div>
        <div className="metric-card cancelled-metric"><div className="metric-label">Cancelled sales</div><div className="metric-value">{money(report.cancelled_invoice_value)}</div><div className="metric-hint">{report.cancelled_invoice_count} invoice(s) excluded</div></div>
      </div>}
    </div>
  </section>
}
