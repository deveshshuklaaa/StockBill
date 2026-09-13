import { useEffect, useState } from 'react'
import { apiErrorMessage, apiForbiddenMessage } from '../../api/client'
import { fetchTaxReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import ReportsShared from '../../components/ReportsShared'
import { useReportRange, daysAgo, today } from '../../components/ReportsShared'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

// Output tax from POSTED invoice line snapshots; input tax from POSTED
// purchase line snapshots. Internal summary — not a GST return.
export default function TaxReportPage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { fromInput, toInput, setFromInput, setToInput, range, apply } = useReportRange({ initialFrom: daysAgo(30), initialTo: today() })

  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    fetchTaxReport({ from: range.from, to: range.to })
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setError(apiForbiddenMessage(err, 'view the tax summary', 'loading tax summary')) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [range])

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Reports / tax</p><h1>GST Summary</h1><p className="page-subtitle">Historical tax snapshots from posted invoices (output) and purchases (input). Internal summary — not a government GST return.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Calculating...' : `${range.from} → ${range.to}`}</span>
        <ReportsShared from={fromInput} to={toInput} onFrom={setFromInput} onTo={setToInput} onApply={apply} />
      </div>

      {report && <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Output tax (sales)</div><div className="metric-value">{money(report.output_tax.total)}</div></div>
        <div className="metric-card"><div className="metric-label">Input tax (purchases)</div><div className="metric-value">{money(report.input_tax.total)}</div></div>
        <div className="metric-card"><div className="metric-label">Net tax</div><div className="metric-value">{money(report.net_tax)}</div><div className="metric-hint">Output − input</div></div>
      </div>}

      {report && <div className="table-scroll"><table>
        <thead><tr><th>Component</th><th style={{ textAlign: 'right' }}>Taxable value</th><th style={{ textAlign: 'right' }}>CGST</th><th style={{ textAlign: 'right' }}>SGST</th><th style={{ textAlign: 'right' }}>IGST</th><th style={{ textAlign: 'right' }}>Total</th></tr></thead>
        <tbody>
          <tr>
            <td><strong>OUTPUT — sales</strong></td>
            <td style={{ textAlign: 'right' }}>{money(report.output_tax.taxable_sales)}</td>
            <td style={{ textAlign: 'right' }}>{money(report.output_tax.cgst)}</td>
            <td style={{ textAlign: 'right' }}>{money(report.output_tax.sgst)}</td>
            <td style={{ textAlign: 'right' }}>{money(report.output_tax.igst)}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(report.output_tax.total)}</strong></td>
          </tr>
          <tr>
            <td><strong>INPUT — purchases</strong></td>
            <td style={{ textAlign: 'right' }}>{money(report.input_tax.taxable_purchases)}</td>
            <td style={{ textAlign: 'right' }}>{money(report.input_tax.cgst)}</td>
            <td style={{ textAlign: 'right' }}>{money(report.input_tax.sgst)}</td>
            <td style={{ textAlign: 'right' }}>{money(report.input_tax.igst)}</td>
            <td style={{ textAlign: 'right' }}><strong>{money(report.input_tax.total)}</strong></td>
          </tr>
        </tbody>
      </table></div>}
    </div>
  </section>
}
