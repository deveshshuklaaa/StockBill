import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { exportInvoiceItemSummaryXlsx, fetchInvoiceItemSummary } from '../api/invoices'
import StatusMessage from './StatusMessage'
import { formatQuantityWithUnit, formatStockWithBoxes } from '../utils/format'

export default function InvoiceItemSummaryModal({ isOpen, onClose, selectedIds = [] }) {
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const [generatedAt, setGeneratedAt] = useState('')

  useEffect(() => {
    if (!isOpen || selectedIds.length === 0) {
      setData(null)
      setError('')
      setLoading(false)
      setExporting(false)
      return
    }

    let active = true
    setLoading(true)
    setError('')

    fetchInvoiceItemSummary(selectedIds)
      .then((res) => {
        if (!active) return
        setData(res)
        setGeneratedAt(new Date().toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }))
      })
      .catch((err) => {
        if (!active) return
        setError(apiErrorMessage(err))
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [isOpen, selectedIds])

  const handleExportExcel = async () => {
    if (exporting || selectedIds.length === 0) return
    setExporting(true)
    setError('')
    try {
      await exportInvoiceItemSummaryXlsx(selectedIds)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  const handlePrint = () => {
    window.print()
  }

  if (!isOpen) return null

  const items = data?.items || []
  const invoiceNumbers = data?.invoice_numbers || data?.selected_invoice_numbers || []
  const invoiceCount = data?.invoice_count ?? data?.selected_invoice_count ?? selectedIds.length
  const totalBaseQty = data?.total_base_quantity ?? '0'

  return (
    <>
      <style>{`
        @media print {
          body * {
            visibility: hidden;
          }
          .summary-printable-area, .summary-printable-area * {
            visibility: visible;
          }
          .summary-printable-area {
            position: absolute !important;
            left: 0 !important;
            top: 0 !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 24px !important;
            background: #ffffff !important;
            box-shadow: none !important;
            border: none !important;
            display: block !important;
          }
          .no-print {
            display: none !important;
          }
          .print-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 16px;
          }
          .print-table th, .print-table td {
            border: 1px solid #c8d3cc;
            padding: 8px 10px;
            font-size: 12px;
          }
          .print-table th {
            background-color: #f2f6f3 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
          .print-table thead {
            display: table-header-group;
          }
          .print-table tr {
            page-break-inside: avoid;
          }
        }
      `}</style>

      <div
        className="modal-backdrop"
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.55)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '16px',
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="summary-modal-title"
      >
        <div
          className="modal-content summary-printable-area"
          style={{
            backgroundColor: '#fff',
            borderRadius: '8px',
            padding: '24px',
            maxWidth: '850px',
            width: '100%',
            maxHeight: '90vh',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.25)',
          }}
        >
          {/* Header */}
          <div
            className="summary-header-block"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}
          >
            <div>
              <p
                className="company-print-title eyebrow"
                style={{ margin: 0, color: '#274b38', fontWeight: 700, fontSize: '13px', letterSpacing: '0.05em' }}
              >
                DIVYA ENTERPRISES
              </p>
              <h2
                id="summary-modal-title"
                style={{ margin: '4px 0 0', color: '#1e382b', fontSize: '20px', fontWeight: 700 }}
              >
                Item-wise Summary
              </h2>
            </div>
            <button
              type="button"
              className="quiet-button no-print"
              style={{ fontSize: '20px', lineHeight: 1, padding: '4px 8px' }}
              onClick={onClose}
              aria-label="Close summary modal"
            >
              ✕
            </button>
          </div>

          <StatusMessage>{error}</StatusMessage>

          {loading ? (
            <div className="empty-state" style={{ padding: '40px 0' }}>
              Loading item summary...
            </div>
          ) : error ? (
            <div style={{ padding: '20px 0', textAlign: 'center' }}>
              <p style={{ color: '#c53030' }}>Failed to load summary.</p>
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  setLoading(true)
                  setError('')
                  fetchInvoiceItemSummary(selectedIds)
                    .then((res) => {
                      setData(res)
                      setGeneratedAt(new Date().toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }))
                    })
                    .catch((err) => setError(apiErrorMessage(err)))
                    .finally(() => setLoading(false))
                }}
              >
                Retry
              </button>
            </div>
          ) : (
            <>
              {/* Selected invoices metadata */}
              <div
                className="summary-meta-card"
                style={{
                  backgroundColor: '#f3f6f3',
                  border: '1px solid #d4ded6',
                  borderRadius: '6px',
                  padding: '12px 16px',
                  marginBottom: '16px',
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ flex: 1, minWidth: '220px' }}>
                    <span style={{ color: '#55695e' }}>Selected Invoices: </span>
                    <strong className="selected-invoices-list">
                      {invoiceNumbers.length > 0 ? invoiceNumbers.join(', ') : `${invoiceCount} invoices`}
                    </strong>
                  </div>
                  <div>
                    <span style={{ color: '#55695e' }}>Generated Date/Time: </span>
                    <strong>{generatedAt || '—'}</strong>
                  </div>
                </div>
                <p
                  className="aggregation-note"
                  style={{ margin: '8px 0 0', fontSize: '11px', color: '#687e71', fontStyle: 'italic' }}
                >
                  Authoritative aggregation across all selected posted invoices. Quantities reflect base inventory units.
                </p>
              </div>

              {items.length === 0 ? (
                <div className="empty-state" style={{ padding: '30px 0' }}>
                  No items found in selected invoices.
                </div>
              ) : (
                <div
                  className="table-scroll"
                  style={{ flex: 1, overflowY: 'auto', maxHeight: '50vh', border: '1px solid #e1e7e2' }}
                >
                  <table className="print-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ background: '#f8faf8', borderBottom: '2px solid #cbd8ce' }}>
                        <th style={{ textAlign: 'left', padding: '10px 12px' }}>Product</th>
                        <th style={{ textAlign: 'left', padding: '10px 12px' }}>SKU</th>
                        <th style={{ textAlign: 'left', padding: '10px 12px' }}>Variant / Pack</th>
                        <th style={{ textAlign: 'right', padding: '10px 12px' }}>MRP</th>
                        <th style={{ textAlign: 'right', padding: '10px 12px' }}>Total Quantity</th>
                        <th style={{ textAlign: 'center', padding: '10px 12px' }}>Invoice Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item) => (
                        <tr key={item.product_id} style={{ borderBottom: '1px solid #eef2ee' }}>
                          <td style={{ padding: '10px 12px' }}>
                            <strong>{item.product_name}</strong>
                          </td>
                          <td style={{ padding: '10px 12px', color: '#4a5d52', fontSize: '12px' }}>
                            {item.sku || '—'}
                          </td>
                          <td style={{ padding: '10px 12px', color: '#687e71', fontSize: '12px' }}>
                            {item.variant_summary || '—'}
                          </td>
                          <td style={{ textAlign: 'right', padding: '10px 12px', whiteSpace: 'nowrap' }}>
                            {item.mrp != null ? `₹${Number(item.mrp).toFixed(2)}` : '—'}
                          </td>
                          <td style={{ textAlign: 'right', padding: '10px 12px', whiteSpace: 'nowrap' }}>
                            <strong>
                              {formatStockWithBoxes(item.total_base_quantity, item)}
                            </strong>
                          </td>
                          <td style={{ textAlign: 'center', padding: '10px 12px' }}>
                            <span className="type-chip" style={{ fontSize: '11px' }}>
                              {item.invoice_count}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Bottom Totals & Controls */}
              <div
                className="summary-footer-block"
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginTop: '16px',
                  paddingTop: '14px',
                  borderTop: '2px solid #274b38',
                  flexWrap: 'wrap',
                  gap: '12px',
                }}
              >
                <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                  <div>
                    <span style={{ color: '#55695e', fontSize: '13px' }}>Total Products: </span>
                    <strong style={{ color: '#1e382b', fontSize: '15px' }}>{items.length}</strong>
                  </div>
                  <div>
                    <span style={{ color: '#55695e', fontSize: '13px' }}>Total Base Quantity: </span>
                    <strong style={{ color: '#1e382b', fontSize: '16px' }}>
                      {formatQuantityWithUnit(totalBaseQty, 'piece')}
                    </strong>
                  </div>
                </div>

                <div className="no-print" style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <button
                    type="button"
                    className="quiet-button"
                    style={{ border: '1px solid #cbd5cd', padding: '6px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
                    onClick={handlePrint}
                    disabled={items.length === 0}
                    aria-label="Print item-wise summary"
                  >
                    <span>🖨️</span> Print
                  </button>
                  <button
                    type="button"
                    className="quiet-button"
                    style={{ border: '1px solid #274b38', color: '#274b38', padding: '6px 14px', fontWeight: 600 }}
                    onClick={handleExportExcel}
                    disabled={exporting || items.length === 0}
                  >
                    {exporting ? 'Exporting...' : 'Export Excel'}
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    style={{ padding: '6px 16px' }}
                    onClick={onClose}
                  >
                    Close
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
