import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchOpeningStock } from '../api/openingStock'
import StatusMessage from '../components/StatusMessage'
import { formatQuantityWithUnit } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export default function OpeningStockDetailPage() {
  const { id } = useParams()
  const [openingStock, setOpeningStock] = useState(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setBusy(true)
    setError('')
    fetchOpeningStock(id)
      .then(setOpeningStock)
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setBusy(false))
  }, [id])

  if (busy) {
    return (
      <section className="page-section">
        <div className="empty-state">Loading opening stock record #{id}...</div>
      </section>
    )
  }

  if (error || !openingStock) {
    return (
      <section className="page-section">
        <StatusMessage type="error">{error || 'Opening stock record not found.'}</StatusMessage>
        <Link className="secondary-button" to="/inventory/opening-stock" style={{ marginTop: '1rem' }}>
          Back to Opening Stock
        </Link>
      </section>
    )
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations / Opening Stock</p>
          <h1>{openingStock.opening_stock_number}</h1>
          <p className="page-subtitle">
            Initial inventory balance snapshot created on {openingStock.effective_date}
          </p>
        </div>
        <Link className="secondary-button" to="/inventory/opening-stock">
          Back to List
        </Link>
      </header>

      {/* Immutability Banner */}
      <div
        style={{
          padding: '0.75rem 1rem',
          backgroundColor: '#eff6ff',
          border: '1px solid #bfdbfe',
          borderRadius: '6px',
          color: '#1e40af',
          fontSize: '0.875rem',
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
        }}
      >
        <span>🔒</span>
        <strong>Immutable Historical Record:</strong> Posted opening stock entries cannot be edited or deleted. Corrections must be handled via a subsequent Stock Adjustment.
      </div>

      <div className="detail-cards-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem', marginBottom: '2rem' }}>
        {/* Item & Warehouse */}
        <div className="info-card">
          <h3 style={{ marginTop: 0, fontSize: '1rem', color: '#374151' }}>Product & Storage</h3>
          <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Product</span>
              <div style={{ fontWeight: 600 }}>{openingStock.product_name}</div>
              {openingStock.product_sku && (
                <div style={{ fontSize: '0.85rem', color: '#6b7280' }}>
                  SKU: <code>{openingStock.product_sku}</code>
                </div>
              )}
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Warehouse</span>
              <div style={{ fontWeight: 600 }}>
                {openingStock.warehouse_name} (<code>{openingStock.warehouse_code}</code>)
              </div>
            </div>
          </div>
        </div>

        {/* Quantities */}
        <div className="info-card">
          <h3 style={{ marginTop: 0, fontSize: '1rem', color: '#374151' }}>Quantities & Conversion</h3>
          <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Entered Quantity</span>
              <div style={{ fontWeight: 600 }}>
                {formatQuantityWithUnit(openingStock.quantity, openingStock.unit)}
              </div>
            </div>
            {openingStock.unit === 'master box' && (
              <div>
                <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Conversion Factor</span>
                <div>{openingStock.conversion_factor} pieces per master box</div>
              </div>
            )}
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Authoritative Base Quantity</span>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#111827' }}>
                {Number(openingStock.base_quantity).toLocaleString('en-IN')} pcs
              </div>
            </div>
          </div>
        </div>

        {/* Valuation */}
        <div className="info-card">
          <h3 style={{ marginTop: 0, fontSize: '1rem', color: '#374151' }}>Valuation & Cost Basis</h3>
          <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Cost per Piece</span>
              <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
                {money(openingStock.cost_per_piece)} / pc
              </div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Total Opening Valuation</span>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#047857' }}>
                {money(openingStock.opening_value)}
              </div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Initial WAC Established</span>
              <div style={{ fontWeight: 600 }}>{money(openingStock.cost_per_piece)}</div>
            </div>
          </div>
        </div>

        {/* Audit context */}
        <div className="info-card">
          <h3 style={{ marginTop: 0, fontSize: '1rem', color: '#374151' }}>Audit & Context</h3>
          <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Reason</span>
              <div>
                <span className="badge badge-not-set">{openingStock.reason}</span>
              </div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Notes</span>
              <div style={{ color: openingStock.note ? '#111827' : '#9ca3af' }}>
                {openingStock.note || 'None recorded'}
              </div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>Created By</span>
              <div>
                {openingStock.created_by_username || 'System'}{' '}
                <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>
                  on {new Date(openingStock.created_at).toLocaleString()}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
