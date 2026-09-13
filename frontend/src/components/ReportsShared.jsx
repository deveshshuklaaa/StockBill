import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

// Shared date-range + report navigation for all report pages.
// Date semantics: backend invoice_date/purchase invoice_date, inclusive
// on both boundaries (from=X&to=X covers the whole day X).
export function today() { return new Date().toISOString().slice(0, 10) }

export function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

export default function ReportFilters({ from, to, onFrom, onTo, onApply, children }) {
  return <div className="filter-row report-filters">
    <label className="filter-field">From<input type="date" value={from} onChange={(e) => onFrom(e.target.value)} aria-label="Report from date" /></label>
    <label className="filter-field">To<input type="date" value={to} onChange={(e) => onTo(e.target.value)} aria-label="Report to date" /></label>
    {children}
    <button type="button" className="quiet-button" onClick={onApply}>Apply</button>
  </div>
}

export function useReportRange({ initialFrom, initialTo } = {}) {
  const [fromInput, setFromInput] = useState(initialFrom)
  const [toInput, setToInput] = useState(initialTo)
  const [range, setRange] = useState({ from: initialFrom, to: initialTo })
  const [loading, setLoading] = useState(false)

  useEffect(() => { setLoading(false) }, [range])

  function apply() {
    if (!fromInput || !toInput) return
    setRange({ from: fromInput, to: toInput })
  }

  return { fromInput, toInput, setFromInput, setToInput, range, apply, loading }
}

export function MetricCard({ label, value, hint, to, onClick }) {
  const body = <><div className="metric-label">{label}</div><div className="metric-value">{value}</div>{hint && <div className="metric-hint">{hint}</div>}</>
  if (to) return <Link className="metric-card linked" to={to} onClick={onClick}>{body}</Link>
  return <div className="metric-card">{body}</div>
}

export function ReportTable({ columns, rows, rowKey, renderRow, emptyMessage }) {
  if (!rows.length) return <div className="empty-state">{emptyMessage}</div>
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map((c) => <th key={c.key} style={c.alignRight ? { textAlign: 'right' } : undefined}>{c.label}</th>)}</tr></thead>
    <tbody>{rows.map((row) => renderRow(row))}</tbody>
  </table></div>
}
