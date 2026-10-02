import { formatQuantityWithUnit, formatStockWithBoxes } from '../utils/format'

/**
 * Dedicated print-only document component for Item-wise Invoice Summary.
 *
 * Rules:
 * - Hidden on screen via `.printable-summary { display: none !important; }`.
 * - Rendered full-height, full-width under `@media print` with zero scrollbars or overflow clipping.
 * - Table header repeats across page breaks via `display: table-header-group`.
 * - Table rows avoid breaking across pages via `break-inside: avoid`.
 * - Renders all rows sequentially from the authoritative summary response.
 */
export default function ItemSummaryPrintDocument({
  items = [],
  invoiceNumbers = [],
  invoiceCount = 0,
  totalBaseQty = '0',
  generatedAt = '',
}) {
  const displayInvoices = invoiceNumbers.length > 0
    ? invoiceNumbers.join(', ')
    : `${invoiceCount} invoices`

  return (
    <div
      className="printable-summary"
      data-testid="item-summary-print-doc"
      aria-hidden="true"
    >
      {/* Print Document Header */}
      <header className="item-summary-print-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '2px solid #274b38', paddingBottom: '10px', marginBottom: '14px' }}>
          <div>
            <h1
              className="print-company-title"
              style={{ margin: 0, color: '#1e382b', fontSize: '22px', fontWeight: 800, letterSpacing: '0.04em' }}
            >
              DIVYA ENTERPRISES
            </h1>
            <h2
              className="print-report-title"
              style={{ margin: '4px 0 0', color: '#274b38', fontSize: '15px', fontWeight: 700, letterSpacing: '0.06em' }}
            >
              ITEM-WISE SUMMARY
            </h2>
          </div>
          <div style={{ textAlign: 'right', fontSize: '11px', color: '#4a5d52' }}>
            <div><strong>Generated:</strong> {generatedAt || new Date().toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</div>
            <div><strong>Invoices:</strong> {invoiceCount} selected</div>
          </div>
        </div>

        {/* Invoices metadata & authoritative aggregation note */}
        <div
          className="print-meta-box"
          style={{
            background: '#f4f7f4',
            border: '1px solid #d4ded6',
            borderRadius: '4px',
            padding: '8px 12px',
            fontSize: '11px',
            marginBottom: '14px',
          }}
        >
          <div style={{ marginBottom: '4px' }}>
            <span style={{ color: '#55695e', fontWeight: 600 }}>Selected Invoices: </span>
            <span style={{ color: '#1e382b', fontWeight: 700 }}>{displayInvoices}</span>
          </div>
          <p style={{ margin: 0, color: '#4a5d52', fontStyle: 'italic' }}>
            Authoritative aggregation across all selected posted invoices. Quantities reflect base inventory units.
          </p>
        </div>
      </header>

      {/* Main Aggregated Table */}
      <table className="print-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: '#f2f6f3' }}>
            <th style={{ width: '40px', textAlign: 'center' }}>#</th>
            <th style={{ textAlign: 'left' }}>Product Name</th>
            <th style={{ textAlign: 'right', width: '100px' }}>MRP</th>
            <th style={{ textAlign: 'right', width: '180px' }}>Total Quantity</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const mrpFormatted = item.mrp != null ? `₹${Number(item.mrp).toFixed(2)}` : '—'
            const totalQtyFormatted = formatStockWithBoxes(item.total_base_quantity, item)

            return (
              <tr key={item.product_id || idx}>
                <td style={{ textAlign: 'center', color: '#687e71', fontSize: '11px' }}>
                  {idx + 1}
                </td>
                <td style={{ textAlign: 'left' }}>
                  <strong style={{ color: '#1e382b', fontSize: '12px' }}>{item.product_name}</strong>
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap', fontSize: '12px' }}>
                  {mrpFormatted}
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap', fontWeight: 600, fontSize: '12px' }}>
                  {totalQtyFormatted}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* Summary Totals & Signature Line */}
      <footer className="item-summary-print-footer" style={{ marginTop: '16px', paddingTop: '10px', borderTop: '2px solid #274b38' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'nowrap' }}>
          <div>
            <div style={{ fontSize: '12px', color: '#1e382b', marginBottom: '4px' }}>
              <span>Total Products: </span>
              <strong>{items.length}</strong>
            </div>
            <div style={{ fontSize: '13px', color: '#1e382b' }}>
              <span>Total Base Quantity: </span>
              <strong style={{ fontSize: '14px', color: '#1e382b' }}>
                {formatQuantityWithUnit(totalBaseQty, 'piece')}
              </strong>
            </div>
          </div>

          <div style={{ textAlign: 'center', minWidth: '180px' }}>
            <div style={{ borderBottom: '1px solid #728477', height: '36px', marginBottom: '6px' }}></div>
            <span style={{ fontSize: '10px', color: '#55695e', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Verified By / Signature
            </span>
          </div>
        </div>
      </footer>
    </div>
  )
}
