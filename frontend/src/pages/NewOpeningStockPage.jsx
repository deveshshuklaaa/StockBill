import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import {
  createOpeningStock,
  fetchNextOpeningStockNumber,
  previewOpeningStock,
} from '../api/openingStock'
import { fetchProducts } from '../api/inventory'
import { fetchWarehouses } from '../api/warehouses'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function todayISO() {
  return new Date().toISOString().split('T')[0]
}

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

const REASONS = [
  'Inventory Initialization',
  'Physical Count',
  'Pre-existing Stock',
  'Other',
]

export default function NewOpeningStockPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const navigate = useNavigate()

  const [products, setProducts] = useState([])
  const [warehouses, setWarehouses] = useState([])
  const [nextNumber, setNextNumber] = useState('OS/...')

  // Form State
  const [productId, setProductId] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [unit, setUnit] = useState('piece')
  const [quantity, setQuantity] = useState('')
  const [costPerPiece, setCostPerPiece] = useState('')
  const [effectiveDate, setEffectiveDate] = useState(todayISO())
  const [reason, setReason] = useState('Inventory Initialization')
  const [note, setNote] = useState('')

  // Preview state
  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState('')
  const [previewing, setPreviewing] = useState(false)

  // Submission state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const selectedProduct = products.find((p) => String(p.id) === String(productId))
  const masterBoxSize =
    selectedProduct?.attributes?.units_per_master_box ||
    selectedProduct?.unit_conversion_factor ||
    1

  useEffect(() => {
    // Load products and active warehouses
    fetchProducts({ page_size: 200, is_active: true })
      .then((data) => setProducts(Array.isArray(data) ? data : data?.results || []))
      .catch(() => {})

    fetchWarehouses({ is_active: 'true' })
      .then((data) => {
        const list = Array.isArray(data) ? data : data?.results || []
        setWarehouses(list)
        if (list.length > 0) {
          setWarehouseId(String(list[0].id || list[0].warehouse))
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!effectiveDate) return
    fetchNextOpeningStockNumber(effectiveDate)
      .then((num) => setNextNumber(typeof num === 'string' ? num : (num?.next_number || 'OS/...')))
      .catch(() => {})
  }, [effectiveDate])

  // Live preview calculation via backend
  useEffect(() => {
    if (!productId || !warehouseId || !quantity || Number(quantity) <= 0 || !costPerPiece || Number(costPerPiece) < 0) {
      setPreview(null)
      setPreviewError('')
      return
    }

    const conversionFactor = unit === 'master box' ? Number(masterBoxSize) : 1
    const timer = setTimeout(() => {
      setPreviewing(true)
      setPreviewError('')
      previewOpeningStock({
        product: Number(productId),
        warehouse: Number(warehouseId),
        quantity: Number(quantity),
        unit,
        conversion_factor: conversionFactor,
        cost_per_piece: Number(costPerPiece),
        reason,
        note,
        effective_date: effectiveDate,
      })
        .then((res) => {
          setPreview(res)
          setPreviewError('')
        })
        .catch((err) => {
          setPreview(null)
          setPreviewError(apiErrorMessage(err))
        })
        .finally(() => setPreviewing(false))
    }, 250)

    return () => clearTimeout(timer)
  }, [
    productId,
    warehouseId,
    unit,
    quantity,
    costPerPiece,
    masterBoxSize,
    reason,
    note,
    effectiveDate,
  ])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (!isAdmin) {
      setError('Only administrators are authorized to post opening stock.')
      return
    }

    if (reason === 'Other' && !note.trim()) {
      setError("Please provide a note when reason is 'Other'.")
      return
    }

    setSubmitting(true)
    const conversionFactor = unit === 'master box' ? Number(masterBoxSize) : 1
    const idempotencyKey = crypto.randomUUID()

    try {
      const result = await createOpeningStock(
        {
          product: Number(productId),
          warehouse: Number(warehouseId),
          quantity: Number(quantity),
          unit,
          conversion_factor: conversionFactor,
          cost_per_piece: Number(costPerPiece),
          reason,
          note: note.trim(),
          effective_date: effectiveDate,
        },
        { idempotencyKey }
      )
      navigate(`/inventory/opening-stock/${result.id}`)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!isAdmin) {
    return (
      <section className="page-section">
        <header className="page-header">
          <div>
            <p className="eyebrow">Inventory Operations</p>
            <h1>New Opening Stock</h1>
          </div>
        </header>
        <div className="empty-state" style={{ padding: '2rem', textAlign: 'center' }}>
          <p>Access restricted: Only administrators are authorized to post opening stock.</p>
          <Link
            className="secondary-button"
            to="/inventory/opening-stock"
            style={{ marginTop: '1rem', display: 'inline-block' }}
          >
            View Opening Stock Records
          </Link>
        </div>
      </section>
    )
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations / Opening Stock</p>
          <h1>New Opening Stock Entry</h1>
          <p className="page-subtitle">
            Initialize pre-existing inventory before StockBill operations began.
          </p>
        </div>
        <Link className="secondary-button" to="/inventory/opening-stock">
          Back to List
        </Link>
      </header>

      <StatusMessage type="error">{error}</StatusMessage>

      <form className="record-form" onSubmit={handleSubmit} id="new-opening-stock-form">
        <div className="form-heading">
          <div>
            <p className="eyebrow">Number Sequence Preview</p>
            <h2>{nextNumber}</h2>
          </div>
        </div>

        <div className="form-grid">
          {/* Effective Date */}
          <label>
            Effective Date *
            <input
              type="date"
              value={effectiveDate}
              max={todayISO()}
              onChange={(e) => setEffectiveDate(e.target.value)}
              required
              aria-label="Effective date"
            />
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>
              Historical or current date (cannot be future).
            </span>
          </label>

          {/* Warehouse */}
          <label>
            Warehouse *
            <select
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
              required
              aria-label="Select warehouse"
            >
              <option value="">Select an active warehouse...</option>
              {warehouses.map((w) => (
                <option key={w.id || w.warehouse} value={w.id || w.warehouse}>
                  {w.name} ({w.code})
                </option>
              ))}
            </select>
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>
              Only active warehouses can receive opening inventory.
            </span>
          </label>

          {/* Product */}
          <label className="full-width">
            Product *
            <select
              value={productId}
              onChange={(e) => {
                setProductId(e.target.value)
                setUnit('piece')
              }}
              required
              aria-label="Select product"
            >
              <option value="">Select a product to initialize...</option>
              {products.map((p) => {
                const mb = p.attributes?.units_per_master_box
                return (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.sku ? `[${p.sku}]` : ''} — MRP ₹{p.mrp || '0.00'}
                    {mb ? ` (${mb} pcs/box)` : ''}
                  </option>
                )
              })}
            </select>
          </label>

          {/* Unit */}
          <label>
            Unit of Entry *
            <select
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              aria-label="Select unit"
            >
              <option value="piece">Piece (Base unit)</option>
              {selectedProduct?.attributes?.units_per_master_box && (
                <option value="master box">
                  Master Box ({selectedProduct.attributes.units_per_master_box} pcs/box)
                </option>
              )}
            </select>
          </label>

          {/* Quantity */}
          <label>
            Entered Quantity *
            <input
              type="number"
              step="any"
              min="0.001"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="e.g. 10"
              required
              aria-label="Entered quantity"
            />
            {unit === 'master box' && (
              <span style={{ fontSize: '0.75rem', color: '#2563eb' }}>
                = {Number(quantity || 0) * Number(masterBoxSize)} base pieces
              </span>
            )}
          </label>

          {/* Cost per piece */}
          <label className="full-width">
            Cost per Piece (₹) *
            <input
              type="number"
              step="0.01"
              min="0.00"
              value={costPerPiece}
              onChange={(e) => setCostPerPiece(e.target.value)}
              placeholder="e.g. 7.10"
              required
              aria-label="Cost per piece"
            />
            <span style={{ fontSize: '0.8rem', color: '#b45309', fontWeight: 500 }}>
              ⚠️ Cost is strictly PER PIECE / BASE UNIT. Never enter the master box cost here.
            </span>
          </label>

          {/* Reason */}
          <label>
            Reason *
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              aria-label="Reason for opening stock"
            >
              {REASONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>

          {/* Note */}
          <label>
            Note {reason === 'Other' && '*'}
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={reason === 'Other' ? 'Required when reason is Other' : 'Optional notes or audit context'}
              required={reason === 'Other'}
              aria-label="Note"
            />
          </label>
        </div>

        {/* Live Calculation Preview Banner */}
        <div
          className="preview-banner"
          style={{
            marginTop: '1.5rem',
            padding: '1.25rem',
            backgroundColor: previewError ? '#fef2f2' : '#f0fdf4',
            borderRadius: '6px',
            border: `1px solid ${previewError ? '#fecaca' : '#bbf7d0'}`,
          }}
        >
          <div style={{ fontWeight: 600, color: previewError ? '#b91c1c' : '#166534', marginBottom: '0.5rem' }}>
            {previewError ? 'Validation Warning' : 'Authoritative Valuation Preview'}
          </div>

          {previewError && (
            <p style={{ margin: 0, color: '#dc2626', fontSize: '0.9rem' }}>
              {previewError}
            </p>
          )}

          {previewing && <p style={{ margin: 0, color: '#6b7280' }}>Calculating backend preview...</p>}

          {!previewError && preview && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                gap: '1rem',
              }}
            >
              <div>
                <span style={{ fontSize: '0.8rem', color: '#4b5563' }}>Base Quantity</span>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#111827' }}>
                  {Number(preview.base_quantity).toLocaleString('en-IN')} pcs
                </div>
              </div>
              <div>
                <span style={{ fontSize: '0.8rem', color: '#4b5563' }}>Unit Cost</span>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#111827' }}>
                  {money(preview.cost_per_piece)} / pc
                </div>
              </div>
              <div>
                <span style={{ fontSize: '0.8rem', color: '#4b5563' }}>Total Opening Valuation</span>
                <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#047857' }}>
                  {money(preview.opening_value)}
                </div>
              </div>
              <div>
                <span style={{ fontSize: '0.8rem', color: '#4b5563' }}>Initial WAC</span>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#111827' }}>
                  {money(preview.cost_per_piece)}
                </div>
              </div>
            </div>
          )}

          {!preview && !previewError && !previewing && (
            <p style={{ margin: 0, color: '#6b7280', fontSize: '0.85rem' }}>
              Select a product, warehouse, quantity, and cost per piece to preview the authoritative inventory valuation.
            </p>
          )}
        </div>

        <div className="form-actions" style={{ marginTop: '1.5rem' }}>
          <Link className="quiet-button" to="/inventory/opening-stock">
            Cancel
          </Link>
          <button
            type="submit"
            className="primary-button"
            disabled={submitting || Boolean(previewError)}
            id="btn-submit-opening-stock"
          >
            {submitting ? 'Initializing...' : 'Post Opening Stock'}
          </button>
        </div>
      </form>
    </section>
  )
}
