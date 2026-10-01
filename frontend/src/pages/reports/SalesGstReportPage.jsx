import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../../api/client'
import { exportSalesGstReportXlsx, fetchSalesGstReport } from '../../api/reports'
import StatusMessage from '../../components/StatusMessage'
import { daysAgo, today } from '../../components/ReportsShared'

function formatCurrency(val) {
  return Number(val || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatDateDisplay(isoStr) {
  if (!isoStr) return ''
  const parts = isoStr.split('-')
  if (parts.length === 3) {
    return `${parts[2]}-${parts[1]}-${parts[0]}`
  }
  return isoStr
}

export default function SalesGstReportPage() {
  const [fromInput, setFromInput] = useState(daysAgo(30))
  const [toInput, setToInput] = useState(today())
  const [range, setRange] = useState({ from: daysAgo(30), to: today() })
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setBusy(true)
    setError('')
    fetchSalesGstReport({ from: range.from, to: range.to })
      .then((data) => {
        if (!cancelled) setReport(data)
      })
      .catch((err) => {
        if (!cancelled) setError(apiErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [range])

  function handleGenerate(e) {
    if (e) e.preventDefault()
    if (!fromInput || !toInput) return
    setRange({ from: fromInput, to: toInput })
  }

  async function handleExportExcel() {
    if (!report || !report.rows || report.rows.length === 0) return
    try {
      setExporting(true)
      await exportSalesGstReportXlsx({
        from: report.from || range.from,
        to: report.to || range.to,
      })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  function handlePrint() {
    window.print()
  }

  const hasData = Boolean(report && report.rows && report.rows.length > 0)
  const totals = report?.totals || {}
  const sellerName = report?.seller?.business_name || 'DIVYA ENTERPRISES'
  const fromDisplay = formatDateDisplay(range.from)
  const toDisplay = formatDateDisplay(range.to)

  return (
    <section className="page-section">
      <style>{`
        @media screen {
          .printable-sales-gst {
            display: none !important;
          }
        }
        @media print {
          @page {
            size: A4 landscape;
            margin: 8mm;
          }
          html, body, #root, .app-shell, .main-content, .page-section {
            height: auto !important;
            min-height: auto !important;
            max-height: none !important;
            overflow: visible !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            background: #ffffff !important;
            display: block !important;
            position: static !important;
          }
          .no-print,
          .sidebar,
          .page-header,
          .table-frame,
          .table-meta,
          .filter-row,
          .report-filters,
          .detail-toolbar,
          button {
            display: none !important;
          }
          .printable-sales-gst {
            display: block !important;
            width: 100% !important;
            height: auto !important;
            max-height: none !important;
            overflow: visible !important;
            position: static !important;
            margin: 0 !important;
            padding: 0 !important;
            background: #ffffff !important;
            color: #111827 !important;
          }
          .printable-sales-gst table {
            width: 100% !important;
            height: auto !important;
            overflow: visible !important;
            border-collapse: collapse !important;
          }
          .printable-sales-gst thead {
            display: table-header-group !important;
          }
          .printable-sales-gst tbody {
            display: table-row-group !important;
          }
          .printable-sales-gst tfoot {
            display: table-footer-group !important;
          }
          .printable-sales-gst tr {
            break-inside: avoid !important;
            page-break-inside: avoid !important;
          }
          .printable-sales-gst th,
          .printable-sales-gst td {
            border: 1px solid #cbd5cd !important;
            padding: 3px 2px !important;
            font-size: 6.8pt !important;
            line-height: 1.2 !important;
          }
          .printable-sales-gst th {
            background-color: #e6efe9 !important;
            font-weight: 700 !important;
            text-align: center !important;
            vertical-align: middle !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          .printable-sales-gst tfoot tr {
            background-color: #f2f6f3 !important;
            font-weight: 700 !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
        }
      `}</style>

      {/* Screen Page Header */}
      <header className="page-header no-print">
        <div>
          <p className="eyebrow">Reports / sales</p>
          <h1>Sales GST Report</h1>
          <p className="page-subtitle">
            Invoice-level Sales Book with GST taxable, tax, and round-off breakdown for POSTED sales.
          </p>
        </div>
      </header>

      <StatusMessage>{error}</StatusMessage>

      {/* Main Screen Container */}
      <div className="table-frame no-print">
        <div className="table-meta" style={{ flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
          <form
            onSubmit={handleGenerate}
            className="filter-row report-filters"
            style={{ margin: 0, display: 'inline-flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}
          >
            <label className="filter-field">
              From Date
              <input
                type="date"
                value={fromInput}
                onChange={(e) => setFromInput(e.target.value)}
                aria-label="From Date"
              />
            </label>
            <label className="filter-field">
              To Date
              <input
                type="date"
                value={toInput}
                onChange={(e) => setToInput(e.target.value)}
                aria-label="To Date"
              />
            </label>
            <button type="submit" className="quiet-button" disabled={busy}>
              Generate
            </button>
          </form>

          <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              type="button"
              className="action-button outline"
              onClick={handleExportExcel}
              disabled={!hasData || exporting}
              aria-label="Export Excel"
            >
              {exporting ? 'Exporting...' : 'Export Excel'}
            </button>
            <button
              type="button"
              className="action-button primary"
              onClick={handlePrint}
              disabled={!hasData}
              aria-label="Print"
            >
              Print
            </button>
          </div>
        </div>

        {/* Loading Indicator */}
        {busy && <div className="loading-state" style={{ padding: '24px', textAlign: 'center', color: '#55695e' }}>Generating report...</div>}

        {/* Empty State */}
        {!busy && report && report.rows.length === 0 && (
          <div className="empty-state" style={{ padding: '32px 16px', textAlign: 'center' }}>
            No posted sales invoices found for the selected period.
          </div>
        )}

        {/* Report Data Table */}
        {!busy && hasData && (
          <div className="table-scroll" style={{ maxHeight: 'calc(100vh - 280px)', overflowX: 'auto', overflowY: 'auto' }}>
            <table className="data-table" style={{ width: '100%', minWidth: '1540px', fontSize: '13px' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '95px', minWidth: '95px', whiteSpace: 'nowrap' }}>DATE</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '105px', minWidth: '105px', whiteSpace: 'nowrap' }}>BILL NO.</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', minWidth: '180px', whiteSpace: 'nowrap' }}>PARTY NAME</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '135px', minWidth: '135px', whiteSpace: 'nowrap' }}>GSTIN</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '95px', minWidth: '95px', whiteSpace: 'nowrap' }}>HSN</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '110px', minWidth: '110px', whiteSpace: 'nowrap' }}>BILL AMT.</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '105px', minWidth: '105px', whiteSpace: 'nowrap' }}>TAXABLE</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '95px', minWidth: '95px', whiteSpace: 'nowrap' }}>TAX</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '95px', minWidth: '95px', whiteSpace: 'nowrap' }}>SGST</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '95px', minWidth: '95px', whiteSpace: 'nowrap' }}>CGST</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '90px', minWidth: '90px', whiteSpace: 'nowrap' }}>IGST</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '105px', minWidth: '105px', whiteSpace: 'nowrap' }}>TOTAL GST</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '70px', minWidth: '70px', whiteSpace: 'nowrap' }}>SUR.</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '85px', minWidth: '85px', whiteSpace: 'nowrap' }}>TAX FREE</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '90px', minWidth: '90px', whiteSpace: 'nowrap' }}>EXEMPTED</th>
                  <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '80px', minWidth: '80px', whiteSpace: 'nowrap' }}>R.OFF</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row) => (
                  <tr key={row.bill_no}>
                    <td style={{ textAlign: 'center', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>{row.date}</td>
                    <td style={{ textAlign: 'center', verticalAlign: 'middle', whiteSpace: 'nowrap', fontWeight: 600 }}>{row.bill_no}</td>
                    <td style={{ textAlign: 'left', verticalAlign: 'middle' }}>{row.party_name}</td>
                    <td style={{ textAlign: 'center', verticalAlign: 'middle', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>{row.gstin || '-'}</td>
                    <td style={{ textAlign: 'center', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>{row.hsn || '-'}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 600, whiteSpace: 'nowrap' }}>₹{formatCurrency(row.bill_amt)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>₹{formatCurrency(row.taxable)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>₹{formatCurrency(row.tax)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>₹{formatCurrency(row.sgst)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>₹{formatCurrency(row.cgst)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap' }}>₹{formatCurrency(row.igst)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap', fontWeight: 600 }}>₹{formatCurrency(row.total_gst)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap', color: '#88988e' }}>{formatCurrency(row.sur)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap', color: '#88988e' }}>{formatCurrency(row.tax_free)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap', color: '#88988e' }}>{formatCurrency(row.exempted)}</td>
                    <td style={{ textAlign: 'right', verticalAlign: 'middle', whiteSpace: 'nowrap', color: Number(row.r_off) !== 0 ? '#1e382b' : '#88988e' }}>
                      {Number(row.r_off) > 0 ? `+${formatCurrency(row.r_off)}` : formatCurrency(row.r_off)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: '#f2f6f3', fontWeight: 'bold', borderTop: '2px solid #2c4d3b' }}>
                  <td colSpan={5} style={{ textAlign: 'left', verticalAlign: 'middle', fontWeight: 'bold' }}>
                    TOTAL ({totals.invoice_count} {totals.invoice_count === 1 ? 'Invoice' : 'Invoices'})
                  </td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 800, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.bill_amt)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.taxable)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.tax)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.sgst)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.cgst)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.igst)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 800, whiteSpace: 'nowrap' }}>₹{formatCurrency(totals.total_gst)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>{formatCurrency(totals.sur)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>{formatCurrency(totals.tax_free)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>{formatCurrency(totals.exempted)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle', fontWeight: 700, whiteSpace: 'nowrap' }}>
                    {Number(totals.r_off) > 0 ? `+${formatCurrency(totals.r_off)}` : formatCurrency(totals.r_off)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {/* Dedicated Print Layout (shown only under @media print) */}
      {hasData && (
        <div className="printable-sales-gst" data-testid="sales-gst-print-doc" aria-hidden="true">
          <header style={{ marginBottom: '14px', borderBottom: '2px solid #1e382b', paddingBottom: '8px' }}>
            <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 800, color: '#1e382b', letterSpacing: '0.04em' }}>
              {sellerName}
            </h1>
            <h2 style={{ margin: '4px 0 0', fontSize: '13px', fontWeight: 700, color: '#274b38', letterSpacing: '0.05em' }}>
              SALES GST REPORT
            </h2>
            <div style={{ fontSize: '10px', color: '#55695e', marginTop: '4px' }}>
              Period: {fromDisplay} to {toDisplay}
            </div>
          </header>

          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#e6efe9' }}>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5.5%' }}>DATE</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '6.5%' }}>BILL NO.</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '14%' }}>PARTY NAME</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '9%' }}>GSTIN</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5.5%' }}>HSN</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '6.5%' }}>BILL AMT.</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '6.5%' }}>TAXABLE</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5.5%' }}>TAX</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5.5%' }}>SGST</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5.5%' }}>CGST</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5%' }}>IGST</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '6.5%' }}>TOTAL GST</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '4.5%' }}>SUR.</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '4.5%' }}>TAX FREE</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '4.5%' }}>EXEMPTED</th>
                <th style={{ textAlign: 'center', verticalAlign: 'middle', width: '5%' }}>R.OFF</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.bill_no}>
                  <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>{row.date}</td>
                  <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>{row.bill_no}</td>
                  <td style={{ textAlign: 'left', verticalAlign: 'middle' }}>{row.party_name}</td>
                  <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>{row.gstin || '-'}</td>
                  <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>{row.hsn || '-'}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.bill_amt).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.taxable).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.tax).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.sgst).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.cgst).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.igst).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.total_gst).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.sur).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.tax_free).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.exempted).toFixed(2)}</td>
                  <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(row.r_off).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ background: '#f2f6f3', fontWeight: 'bold' }}>
                <td colSpan={5} style={{ textAlign: 'left', verticalAlign: 'middle', fontWeight: 'bold' }}>
                  TOTAL ({totals.invoice_count} {totals.invoice_count === 1 ? 'Invoice' : 'Invoices'})
                </td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.bill_amt || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.taxable || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.tax || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.sgst || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.cgst || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.igst || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.total_gst || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.sur || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.tax_free || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.exempted || 0).toFixed(2)}</td>
                <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>{Number(totals.r_off || 0).toFixed(2)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </section>
  )
}
