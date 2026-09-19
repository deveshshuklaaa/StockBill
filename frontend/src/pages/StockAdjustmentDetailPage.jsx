import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchAdjustment } from '../api/adjustments'
import { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import { formatQuantityWithUnit } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const TYPE_BADGE = {
  STOCK_ADJUSTMENT_IN: 'tax-chip',
  STOCK_ADJUSTMENT_OUT: 'state-cancelled',
}

export default function StockAdjustmentDetailPage() {
  const { id } = useParams()
  const [adjustment, setAdjustment] = useState(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setBusy(true)
    setError('')
    fetchAdjustment(id)
      .then(setAdjustment)
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setBusy(false))
  }, [id])

  if (busy) {
    return (
      <section className="page-section">
        <div className="empty-state">Loading adjustment details...</div>
      </section>
    )
  }

  if (error || !adjustment) {
    return (
      <section className="page-section">
        <StatusMessage>{error || 'Adjustment not found.'}</StatusMessage>
        <Link className="secondary-button" to="/inventory/adjustments" style={{ marginTop: '1rem' }}>
          Back to Adjustments
        </Link>
      </section>
    )
  }

  const isIn = adjustment.adjustment_type === 'STOCK_ADJUSTMENT_IN'

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations / Adjustments</p>
          <h1>{adjustment.adjustment_number}</h1>
          <p className="page-subtitle">
            Effective date: {adjustment.effective_date} · Recorded {new Date(adjustment.created_at).toLocaleString('en-IN')}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <span className={TYPE_BADGE[adjustment.adjustment_type] || 'type-chip'}>
            {isIn ? '+ IN (Stock Increase)' : '- OUT (Stock Decrease)'}
          </span>
          <Link className="secondary-button" to="/inventory/adjustments">
            Back to List
          </Link>
        </div>
      </header>

      {/* Immutability Banner */}
      <div
        style={{
          background: 'var(--color-surface, #f8fafc)',
          border: '1px solid var(--color-border, #cbd5e1)',
          borderRadius: '6px',
          padding: '0.75rem 1rem',
          margin: '1rem 0',
          fontSize: '0.9em',
          color: '#475569',
        }}
      >
        <strong>Append-Only Record:</strong> This stock adjustment is an immutable historical event.
        It cannot be modified or deleted. Any corrective movement must be recorded as a compensating adjustment.
      </div>

      <div className="table-frame" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15em', margin: '0 0 1rem 0' }}>Adjustment Details</h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Product</span>
            <strong>{adjustment.product_name}</strong>
            {adjustment.product_sku && (
              <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>
                SKU: {adjustment.product_sku}
              </span>
            )}
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Warehouse</span>
            <strong>{adjustment.warehouse_name}</strong>
            {adjustment.warehouse_code && (
              <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>
                Code: {adjustment.warehouse_code}
              </span>
            )}
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Entered Quantity</span>
            <strong>{formatQuantityWithUnit(adjustment.quantity, adjustment.unit)}</strong>
            {adjustment.unit === 'master box' && (
              <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>
                Conversion: {adjustment.conversion_factor} pcs/box
              </span>
            )}
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Authoritative Base Pieces</span>
            <strong style={{ fontSize: '1.1em', color: isIn ? '#16a34a' : '#dc2626' }}>
              {isIn ? `+${formatQuantityWithUnit(adjustment.base_quantity, 'piece')}` : `-${formatQuantityWithUnit(adjustment.base_quantity, 'piece')}`}
            </strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Unit Cost Snapshot</span>
            <strong>{money(adjustment.cost_per_base_unit_snapshot)} / piece</strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Adjustment Total Value</span>
            <strong style={{ fontSize: '1.1em' }}>{money(adjustment.adjustment_value)}</strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Reason</span>
            <strong>{adjustment.reason}</strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Note / Reference</span>
            <span>{adjustment.note || 'None'}</span>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Created By</span>
            <span>{adjustment.created_by_username || 'System'}</span>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Created Timestamp</span>
            <span>{new Date(adjustment.created_at).toLocaleString('en-IN')}</span>
          </div>
        </div>
      </div>
    </section>
  )
}
