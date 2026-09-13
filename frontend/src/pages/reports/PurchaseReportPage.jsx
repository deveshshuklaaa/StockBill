import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { fetchSuppliers } from '../../api/suppliers'
import { fetchPurchaseReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared from '../../components/ReportsShared'
import { useReportRange, daysAgo, today } from '../../components/ReportsShared'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// POSTED purchases at posting-time snapshots; cancelled excluded.
export default function PurchaseReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [suppliers, setSuppliers] = useState([])
  const [supplier, setSupplier] = useState('')
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })
  const [supplierFilter, setSupplierFilter] = useState('')

  useEffect(() => {
    fetchSuppliers({ page: 1 }).then((data) => setSuppliers(data.results || [])).catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchPurchaseReport({ from: range.from, to: range.to, supplier: supplierFilter })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range, supplierFilter])

  function applyAll() {
    apply()
    setSupplierFilter(supplier)
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / purchasing</p><h1>Purchase Summary</h1><p className="page-subtitle">POSTED purchases at posting-time values — never current cost or WAC. Cancelled purchases are excluded from active totals.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${report ? report.purchase_count : 0} posted purchase${report?.purchase_count === 1 ? '' : 's'} · ${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={applyAll}>
          <label className="filter-field">Supplier<select value={supplier} onChange={(e) => setSupplier(e.target.value)} aria-label="Filter by supplier"><option value="">All</option>{suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        </ReportsShared>
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Taxable purchases</div><div className="metric-value">{money(report.taxable_purchases)}</div></div>
        <div className="metric-card"><div className="metric-label">Input GST</div><div className="metric-value">{money(report.gst)}</div></div>
        <div className="metric-card"><div className="metric-label">Total purchase value</div><div className="metric-value">{money(report.total_purchase_value)}</div></div>
        <div className="metric-card cancelled-metric"><div className="metric-label">Cancelled purchases</div><div className="metric-value">{money(report.cancelled_purchase_value)}</div><div className="metric-hint">{report.cancelled_purchase_count} purchase(s) excluded</div></div>
      </div>}

      {report && report.by_supplier.length > 0 && <div className="table-scroll"><table>
        <thead><tr><th>Supplier</th><th style={{ textAlign: 'right' }}>Purchases</th><th style={{ textAlign: 'right' }}>Taxable</th><th style={{ textAlign: 'right' }}>GST</th><th style={{ textAlign: 'right' }}>Total</th></tr></thead>
        <tbody>{report.by_supplier.map((row) => <tr key={row.supplier_id}>
          <td><strong>{row.supplier_name}</strong></td>
          <td style={{ textAlign: 'right' }}>{row.invoice_count}</td>
          <td style={{ textAlign: 'right' }}>{money(row.taxable_total)}</td>
          <td style={{ textAlign: 'right' }}>{money(row.gst_total)}</td>
          <td style={{ textAlign: 'right' }}><strong>{money(row.purchase_total)}</strong></td>
        </tr>)}</tbody>
      </table></div>}
    </div>
  </section>
}
