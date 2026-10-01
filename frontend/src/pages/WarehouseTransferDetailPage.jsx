import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchTransfer } from '../api/transfers'
import StatusMessage from '../components/StatusMessage'
import { formatQuantityWithUnit } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function WarehouseTransferDetailPage() {
  const { id } = useParams()
  const [transfer, setTransfer] = useState(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setBusy(true)
    setError('')
    fetchTransfer(id)
      .then(setTransfer)
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setBusy(false))
  }, [id])

  if (busy) {
    return (
      <section className="page-section">
        <div className="empty-state">Loading warehouse transfer details...</div>
      </section>
    )
  }

  if (error || !transfer) {
    return (
      <section className="page-section">
        <StatusMessage>{error || 'Warehouse transfer not found.'}</StatusMessage>
        <Link className="secondary-button" to="/inventory/transfers" style={{ marginTop: '1rem' }}>
          Back to Transfers
        </Link>
      </section>
    )
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">
            <Link to="/inventory/transfers" style={{ color: '#4a6b57', textDecoration: 'none' }}>
              ← Warehouse Transfers
            </Link>
          </p>
          <h1>{transfer.transfer_number}</h1>
          <p className="page-subtitle">
            Effective date: {transfer.effective_date} · Recorded{' '}
            {new Date(transfer.created_at).toLocaleString('en-IN')}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <span className="type-chip" style={{ background: '#ecfdf3', color: '#027a48', fontWeight: 600 }}>
            COMPLETED
          </span>
          <Link className="secondary-button" to="/inventory/transfers">
            Back to List
          </Link>
        </div>
      </header>

      {/* Immutability Banner */}
      <div
        style={{
          background: '#f8fafc',
          border: '1px solid #cbd5e1',
          borderRadius: '6px',
          padding: '0.75rem 1rem',
          margin: '1rem 0',
          fontSize: '0.9em',
          color: '#475569',
        }}
      >
        <strong>Append-Only Record:</strong> This warehouse transfer is an immutable historical event. It cannot
        be modified or deleted. Any corrective movement must be recorded as another valid transfer or adjustment.
      </div>

      {/* Route banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-around',
          backgroundColor: '#fafcfa',
          border: '1px solid #d4ded6',
          borderRadius: '8px',
          padding: '16px 24px',
          marginBottom: '20px',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <span style={{ fontSize: '11px', textTransform: 'uppercase', color: '#912018', fontWeight: 700, display: 'block' }}>
            Source Warehouse (Stock Out)
          </span>
          <strong style={{ fontSize: '16px', color: '#1e382b' }}>
            {transfer.source_warehouse_name} ({transfer.source_warehouse_code})
          </strong>
        </div>

        <div style={{ fontSize: '24px', color: '#274b38' }}>➔</div>

        <div style={{ textAlign: 'center' }}>
          <span style={{ fontSize: '11px', textTransform: 'uppercase', color: '#027a48', fontWeight: 700, display: 'block' }}>
            Destination Warehouse (Stock In)
          </span>
          <strong style={{ fontSize: '16px', color: '#1e382b' }}>
            {transfer.destination_warehouse_name} ({transfer.destination_warehouse_code})
          </strong>
        </div>
      </div>

      <div className="table-frame" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15em', margin: '0 0 1rem 0' }}>Transfer Details</h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Product</span>
            <strong>{transfer.product_name}</strong>
            {transfer.product_sku && (
              <span style={{ fontSize: '0.85em', color: '#888', display: 'block' }}>
                SKU: {transfer.product_sku}
              </span>
            )}
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Entered Quantity</span>
            <strong>
              {Number(transfer.quantity).toLocaleString()} {transfer.unit}
            </strong>
            {Number(transfer.conversion_factor) > 1 && (
              <span style={{ fontSize: '0.85em', color: '#888', display: 'block' }}>
                Pack size: {transfer.conversion_factor} pcs / {transfer.unit}
              </span>
            )}
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Authoritative Base Quantity</span>
            <strong style={{ color: '#1e382b', fontSize: '1.1em' }}>
              {formatQuantityWithUnit(transfer.base_quantity, 'piece')}
            </strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Transfer Cost / Piece (Snapshot)</span>
            <strong>{money(transfer.unit_cost_snapshot)}</strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Total Transfer Value</span>
            <strong style={{ color: '#1e382b', fontSize: '1.1em' }}>{money(transfer.transfer_value)}</strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Reason</span>
            <strong>{transfer.reason}</strong>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Recorded By</span>
            <span>{transfer.created_by_username || 'System'}</span>
          </div>

          <div>
            <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>Note</span>
            <span>{transfer.note || '—'}</span>
          </div>
        </div>
      </div>

      {/* Stock movement breakdown card */}
      <div className="table-frame" style={{ padding: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15em', margin: '0 0 1rem 0' }}>Inventory Accounting Movements</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px' }}>
          <div style={{ padding: '12px', background: '#fef3f2', border: '1px solid #fee4e2', borderRadius: '6px' }}>
            <span style={{ fontSize: '12px', color: '#b42318', fontWeight: 600 }}>SOURCE LEDGER MOVEMENT</span>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#912018', marginTop: '4px' }}>
              - {formatQuantityWithUnit(transfer.base_quantity, 'piece')}
            </div>
            <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>
              Warehouse: {transfer.source_warehouse_name}
              <br />
              Movement Type: <code>WAREHOUSE_TRANSFER_OUT</code>
              <br />
              WAC Impact: Unchanged
            </div>
          </div>

          <div style={{ padding: '12px', background: '#ecfdf3', border: '1px solid #d1fadf', borderRadius: '6px' }}>
            <span style={{ fontSize: '12px', color: '#027a48', fontWeight: 600 }}>DESTINATION LEDGER MOVEMENT</span>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#027a48', marginTop: '4px' }}>
              + {formatQuantityWithUnit(transfer.base_quantity, 'piece')}
            </div>
            <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>
              Warehouse: {transfer.destination_warehouse_name}
              <br />
              Movement Type: <code>WAREHOUSE_TRANSFER_IN</code>
              <br />
              WAC Impact: Weighted average recalculated
            </div>
          </div>

          <div style={{ padding: '12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px' }}>
            <span style={{ fontSize: '12px', color: '#475569', fontWeight: 600 }}>NET COMPANY IMPACT</span>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginTop: '4px' }}>
              0 pieces
            </div>
            <div style={{ fontSize: '12px', color: '#555', marginTop: '4px' }}>
              Total Stock: No change
              <br />
              Total Valuation: Invariant (₹0.00 net change)
              <br />
              Transaction Type: Internal Transfer
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
