import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { fetchInvoiceItemSummary } from '../api/invoices'
import StatusMessage from './StatusMessage'
import { formatQuantityWithUnit, formatStockWithBoxes } from '../utils/format'

export default function InvoiceItemSummaryModal({ isOpen, onClose, selectedIds = [] }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!isOpen || selectedIds.length === 0) {
      setData(null)
      setError('')
      setLoading(false)
      return
    }

    let active = true
    setLoading(true)
    setError('')

    fetchInvoiceItemSummary(selectedIds)
      .then((res) => {
        if (!active) return
        setData(res)
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

  if (!isOpen) return null

  const items = data?.items || []
  const invoiceNumbers = data?.invoice_numbers || []
  const invoiceCount = data?.invoice_count ?? selectedIds.length
  const totalBaseQty = data?.total_base_quantity ?? '0'

  return (
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
        className="modal-content"
        style={{
          backgroundColor: '#fff',
          borderRadius: '8px',
          padding: '24px',
          maxWidth: '750px',
          width: '100%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.25)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <p className="eyebrow" style={{ margin: 0, color: '#6b8678' }}>Billing / Report</p>
            <h2 id="summary-modal-title" style={{ margin: '4px 0 0', color: '#1e382b', fontSize: '20px' }}>
              Item-wise Summary
            </h2>
          </div>
          <button
            type="button"
            className="quiet-button"
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
                  .then(setData)
                  .catch((err) => setError(apiErrorMessage(err)))
                  .finally(() => setLoading(false))
              }}
            >
              Retry
            </button>
          </div>
        ) : (
          <>
            <div
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
                <div>
                  <span style={{ color: '#55695e' }}>Selected Invoices: </span>
                  <strong>{invoiceNumbers.length > 0 ? invoiceNumbers.join(', ') : `${invoiceCount} invoices`}</strong>
                </div>
                <div>
                  <span style={{ color: '#55695e' }}>Products: </span>
                  <strong>{items.length}</strong>
                </div>
              </div>
              <p style={{ margin: '6px 0 0', fontSize: '11px', color: '#687e71' }}>
                Authoritative aggregation across all selected posted invoices. Quantities reflect base inventory units.
              </p>
            </div>

            {items.length === 0 ? (
              <div className="empty-state" style={{ padding: '30px 0' }}>
                No items found in selected invoices.
              </div>
            ) : (
              <div className="table-scroll" style={{ flex: 1, overflowY: 'auto', maxHeight: '50vh', border: '1px solid #e1e7e2' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ background: '#f8faf8', borderBottom: '2px solid #cbd8ce' }}>
                      <th style={{ textAlign: 'left', padding: '10px 12px' }}>Product</th>
                      <th style={{ textAlign: 'right', padding: '10px 12px' }}>MRP</th>
                      <th style={{ textAlign: 'right', padding: '10px 12px' }}>Total Qty</th>
                      <th style={{ textAlign: 'center', padding: '10px 12px' }}>Invoices</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.product_id} style={{ borderBottom: '1px solid #eef2ee' }}>
                        <td style={{ padding: '10px 12px' }}>
                          <strong>{item.product_name}</strong>
                          {item.variant_summary && (
                            <span style={{ display: 'block', color: '#7a8c80', fontSize: '11px', marginTop: '2px' }}>
                              {item.variant_summary}
                            </span>
                          )}
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

            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginTop: '16px',
                paddingTop: '14px',
                borderTop: '2px solid #274b38',
              }}
            >
              <div>
                <span style={{ color: '#55695e', fontSize: '13px' }}>Total Base Quantity: </span>
                <strong style={{ color: '#1e382b', fontSize: '16px' }}>
                  {formatQuantityWithUnit(totalBaseQty, 'piece')}
                </strong>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  type="button"
                  className="quiet-button"
                  style={{ border: '1px solid #cbd5cd', padding: '6px 14px' }}
                  onClick={() => window.print()}
                >
                  Print
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
  )
}
