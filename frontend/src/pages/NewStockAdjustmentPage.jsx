import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createAdjustment, fetchNextAdjustmentNumber } from '../api/adjustments'
import { apiErrorMessage } from '../api/client'
import { fetchProductInventory } from '../api/inventory'
import { fetchWarehouses, searchPurchaseProducts } from '../api/purchases'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatNetWeight, formatQuantityWithUnit, masterBoxSize } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

const REASONS_IN = ['Physical Count Increase', 'Found Stock', 'Other']
const REASONS_OUT = ['Physical Count Decrease', 'Damaged', 'Expired', 'Missing/Short', 'Other']

export default function NewStockAdjustmentPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'

  const [warehouses, setWarehouses] = useState([])
  const [warehouseId, setWarehouseId] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [productResults, setProductResults] = useState([])
  const [productBusy, setProductBusy] = useState(false)
  const [selectedProduct, setSelectedProduct] = useState(null)
  const [inventoryBalance, setInventoryBalance] = useState(null)
  const [balanceBusy, setBalanceBusy] = useState(false)

  const [adjustmentType, setAdjustmentType] = useState('STOCK_ADJUSTMENT_IN')
  const [unit, setUnit] = useState('piece')
  const [quantity, setQuantity] = useState('')
  const [costPerPiece, setCostPerPiece] = useState('')
  const [reason, setReason] = useState('Physical Count Increase')
  const [note, setNote] = useState('')
  const [effectiveDate, setEffectiveDate] = useState(today())
  const [nextNumber, setNextNumber] = useState('')

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Load initial warehouses & preview next number
  useEffect(() => {
    fetchWarehouses()
      .then((data) => {
        setWarehouses(data || [])
        if (data?.length > 0) {
          setWarehouseId(String(data[0].id))
        }
      })
      .catch(() => {})

    fetchNextAdjustmentNumber(today())
      .then(setNextNumber)
      .catch(() => {})
  }, [])

  // Update preview number when effective date changes
  useEffect(() => {
    if (effectiveDate) {
      fetchNextAdjustmentNumber(effectiveDate)
        .then(setNextNumber)
        .catch(() => {})
    }
  }, [effectiveDate])

  // Debounced product search
  useEffect(() => {
    if (!productSearch.trim() || selectedProduct) {
      setProductResults([])
      return
    }
    const timer = setTimeout(() => {
      setProductBusy(true)
      searchPurchaseProducts(productSearch.trim())
        .then((res) => setProductResults(res.data?.results || res.data || []))
        .catch(() => setProductResults([]))
        .finally(() => setProductBusy(false))
    }, 250)
    return () => clearTimeout(timer)
  }, [productSearch, selectedProduct])

  // Reset reason when direction changes
  useEffect(() => {
    if (adjustmentType === 'STOCK_ADJUSTMENT_IN') {
      setReason(REASONS_IN[0])
    } else {
      setReason(REASONS_OUT[0])
    }
  }, [adjustmentType])

  // Fetch product inventory balance when product or warehouse changes
  useEffect(() => {
    if (!selectedProduct?.id || !warehouseId) {
      setInventoryBalance(null)
      return
    }
    setBalanceBusy(true)
    fetchProductInventory(selectedProduct.id)
      .then((balances) => {
        const bal = balances.find((b) => String(b.warehouse) === String(warehouseId))
        setInventoryBalance(bal || null)
      })
      .catch(() => setInventoryBalance(null))
      .finally(() => setBalanceBusy(false))
  }, [selectedProduct, warehouseId])

  // Units per master box for selected product
  const packSize = useMemo(() => {
    return selectedProduct ? masterBoxSize(selectedProduct) : null
  }, [selectedProduct])

  // When switching product, reset unit if master box not supported
  useEffect(() => {
    if (!packSize && unit === 'master box') {
      setUnit('piece')
    }
  }, [packSize, unit])

  // Calculations for live preview
  const currentStock = Number(inventoryBalance?.quantity_on_hand ?? selectedProduct?.current_stock ?? 0)
  const currentWac = Number(inventoryBalance?.average_cost ?? selectedProduct?.cost_price ?? 0)
  const conversionFactor = unit === 'master box' && packSize ? packSize : 1
  const enteredQty = Number(quantity) || 0
  const baseQuantity = enteredQty > 0 ? enteredQty * conversionFactor : 0

  const isIn = adjustmentType === 'STOCK_ADJUSTMENT_IN'
  const isOut = adjustmentType === 'STOCK_ADJUSTMENT_OUT'

  let newStock = currentStock
  let newWac = currentWac
  let adjustmentValue = 0
  let effectiveUnitCost = 0

  if (isIn) {
    newStock = currentStock + baseQuantity
    effectiveUnitCost = Number(costPerPiece) || 0
    adjustmentValue = baseQuantity * effectiveUnitCost
    if (baseQuantity > 0) {
      if (currentStock <= 0) {
        newWac = effectiveUnitCost
      } else {
        newWac = (currentStock * currentWac + baseQuantity * effectiveUnitCost) / newStock
      }
    }
  } else if (isOut) {
    newStock = Math.max(0, currentStock - baseQuantity)
    effectiveUnitCost = currentWac
    adjustmentValue = baseQuantity * effectiveUnitCost
    newWac = currentWac
  }

  const isInsufficientStock = isOut && baseQuantity > currentStock

  function handleSelectProduct(prod) {
    setSelectedProduct(prod)
    setProductSearch(prod.name)
    setProductResults([])
    setError('')
  }

  function handleClearProduct() {
    setSelectedProduct(null)
    setProductSearch('')
    setProductResults([])
    setInventoryBalance(null)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (!selectedProduct) {
      setError('Please select a product.')
      return
    }
    if (!warehouseId) {
      setError('Please select a warehouse.')
      return
    }
    if (enteredQty <= 0) {
      setError('Quantity must be greater than zero.')
      return
    }
    if (isInsufficientStock) {
      setError('Insufficient stock for this adjustment.')
      return
    }
    if (isIn && (costPerPiece === '' || Number(costPerPiece) < 0)) {
      setError('Adjustment Cost (per Piece) is required for stock additions.')
      return
    }
    if (!effectiveDate) {
      setError('Effective date is required.')
      return
    }
    if (effectiveDate > today()) {
      setError('Effective date cannot be in the future.')
      return
    }
    if (reason === 'Other' && !note.trim()) {
      setError("A note is required when reason is 'Other'.")
      return
    }

    const payload = {
      product: selectedProduct.id,
      warehouse: Number(warehouseId),
      adjustment_type: adjustmentType,
      quantity: String(enteredQty),
      unit,
      conversion_factor: String(conversionFactor),
      reason,
      note: note.trim(),
      effective_date: effectiveDate,
    }
    if (isIn) {
      payload.cost_per_piece = String(costPerPiece)
    }

    setBusy(true)
    const idempotencyKey = crypto?.randomUUID ? crypto.randomUUID() : `adj-${Date.now()}`
    try {
      const data = await createAdjustment(payload, { idempotencyKey })
      navigate(`/inventory/adjustments/${data.id}`)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!isAdmin) {
    return (
      <section className="page-section">
        <header className="page-header">
          <div>
            <p className="eyebrow">Inventory Operations</p>
            <h1>New Stock Adjustment</h1>
          </div>
        </header>
        <div className="empty-state">
          <p>Access restricted: Only administrators are authorized to post stock adjustments.</p>
          <Link className="secondary-button" to="/inventory/adjustments" style={{ marginTop: '1rem' }}>
            View Adjustments
          </Link>
        </div>
      </section>
    )
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Inventory Operations</p>
          <h1>New Stock Adjustment</h1>
          <p className="page-subtitle">
            {nextNumber ? `Drafting adjustment ${nextNumber}` : 'Record a physical stock correction'}
          </p>
        </div>
        <Link className="secondary-button" to="/inventory/adjustments">
          Cancel
        </Link>
      </header>

      <StatusMessage>{error}</StatusMessage>

      <form onSubmit={handleSubmit} noValidate className="form-frame">
        <div className="form-grid">
          {/* Product Selection */}
          <div className="form-field full-width" style={{ position: 'relative' }}>
            <label>
              Product <span className="required">*</span>
            </label>
            {selectedProduct ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.75rem 1rem',
                  background: 'var(--color-surface, #f8f9fa)',
                  border: '1px solid var(--color-border, #e2e8f0)',
                  borderRadius: '6px',
                }}
              >
                <div>
                  <strong>{selectedProduct.name}</strong>
                  <span style={{ fontSize: '0.85em', color: '#666', display: 'block' }}>
                    {[
                      formatNetWeight(selectedProduct.attributes?.net_weight),
                      selectedProduct.mrp ? `MRP: ₹${selectedProduct.mrp}` : null,
                      selectedProduct.sku ? `SKU: ${selectedProduct.sku}` : null,
                      packSize ? `Pack size: ${packSize} pcs/box` : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={handleClearProduct}
                  style={{ padding: '0.25rem 0.5rem', fontSize: '0.85em' }}
                >
                  Change Product
                </button>
              </div>
            ) : (
              <div>
                <input
                  type="text"
                  value={productSearch}
                  onChange={(e) => setProductSearch(e.target.value)}
                  placeholder="Type product name or SKU..."
                  aria-label="Search product"
                  autoFocus
                />
                {productBusy && <span style={{ fontSize: '0.85em', color: '#666' }}>Searching products...</span>}
                {productResults.length > 0 && (
                  <ul
                    style={{
                      position: 'absolute',
                      zIndex: 10,
                      top: '100%',
                      left: 0,
                      right: 0,
                      background: '#fff',
                      border: '1px solid #ccc',
                      borderRadius: '4px',
                      listStyle: 'none',
                      margin: 0,
                      padding: 0,
                      maxHeight: '220px',
                      overflowY: 'auto',
                      boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
                    }}
                  >
                    {productResults.map((p) => {
                      const size = masterBoxSize(p)
                      return (
                        <li
                          key={p.id}
                          onClick={() => handleSelectProduct(p)}
                          style={{
                            padding: '0.5rem 1rem',
                            cursor: 'pointer',
                            borderBottom: '1px solid #eee',
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = '#f0f4f8')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                        >
                          <strong>{p.name}</strong>
                          <div style={{ fontSize: '0.85em', color: '#666' }}>
                            {[
                              formatNetWeight(p.attributes?.net_weight),
                              p.mrp ? `MRP: ₹${p.mrp}` : null,
                              p.sku ? `SKU: ${p.sku}` : null,
                              size ? `${size} pcs/box` : null,
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* Warehouse */}
          <div className="form-field">
            <label htmlFor="adj-warehouse">
              Warehouse <span className="required">*</span>
            </label>
            <select
              id="adj-warehouse"
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
              aria-label="Warehouse"
              required
            >
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} ({w.code})
                </option>
              ))}
            </select>
          </div>

          {/* Adjustment Direction */}
          <div className="form-field">
            <label htmlFor="adj-type">
              Adjustment Type <span className="required">*</span>
            </label>
            <select
              id="adj-type"
              value={adjustmentType}
              onChange={(e) => setAdjustmentType(e.target.value)}
              aria-label="Adjustment Type"
            >
              <option value="STOCK_ADJUSTMENT_IN">Increase Stock (+ IN)</option>
              <option value="STOCK_ADJUSTMENT_OUT">Decrease Stock (- OUT)</option>
            </select>
          </div>

          {/* Quantity Unit */}
          <div className="form-field">
            <label htmlFor="adj-unit">
              Quantity Unit <span className="required">*</span>
            </label>
            <select
              id="adj-unit"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              aria-label="Quantity Unit"
            >
              <option value="piece">Piece</option>
              {packSize && (
                <option value="master box">
                  Master Box ({packSize} pcs)
                </option>
              )}
            </select>
          </div>

          {/* Quantity Input */}
          <div className="form-field">
            <label htmlFor="adj-quantity">
              {unit === 'master box' ? 'Quantity in master boxes' : 'Quantity in pieces'}{' '}
              <span className="required">*</span>
            </label>
            <input
              id="adj-quantity"
              type="number"
              step="any"
              min="0.001"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="e.g. 5"
              aria-label={unit === 'master box' ? 'Quantity in master boxes' : 'Quantity in pieces'}
              required
            />
            {unit === 'master box' && baseQuantity > 0 && (
              <span style={{ fontSize: '0.85em', color: '#666' }}>
                = {formatQuantityWithUnit(baseQuantity, 'piece')}
              </span>
            )}
          </div>

          {/* Cost Field */}
          <div className="form-field">
            {isIn ? (
              <>
                <label htmlFor="adj-cost">
                  Adjustment Cost (per Piece) <span className="required">*</span>
                </label>
                <input
                  id="adj-cost"
                  type="number"
                  step="0.01"
                  min="0"
                  value={costPerPiece}
                  onChange={(e) => setCostPerPiece(e.target.value)}
                  placeholder="e.g. 6.66"
                  aria-label="Adjustment Cost (per Piece)"
                  required
                />
                <span style={{ fontSize: '0.8em', color: '#666' }}>
                  Weighted-average cost will be recalculated.
                </span>
              </>
            ) : (
              <>
                <label>Cost Basis (Current WAC)</label>
                <div
                  style={{
                    padding: '0.65rem 0.75rem',
                    background: '#f8f9fa',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    fontWeight: 600,
                  }}
                >
                  {balanceBusy ? 'Fetching WAC...' : `Current WAC: ${money(currentWac)} / piece`}
                </div>
                <span style={{ fontSize: '0.8em', color: '#666' }}>
                  Deductions consume stock at current WAC without altering average cost.
                </span>
              </>
            )}
          </div>

          {/* Reason */}
          <div className="form-field">
            <label htmlFor="adj-reason">
              Reason <span className="required">*</span>
            </label>
            <select
              id="adj-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label="Reason"
              required
            >
              {(isIn ? REASONS_IN : REASONS_OUT).map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          {/* Effective Date */}
          <div className="form-field">
            <label htmlFor="adj-date">
              Effective Date <span className="required">*</span>
            </label>
            <input
              id="adj-date"
              type="date"
              max={today()}
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
              aria-label="Effective Date"
              required
            />
          </div>

          {/* Note / Reference */}
          <div className="form-field full-width">
            <label htmlFor="adj-note">
              Note / Reference {reason === 'Other' && <span className="required">*</span>}
            </label>
            <input
              id="adj-note"
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={
                reason === 'Other'
                  ? 'Detailed explanation required for Other...'
                  : 'Optional note or inspection reference...'
              }
              aria-label="Note / Reference"
              required={reason === 'Other'}
            />
          </div>
        </div>

        {/* Live Calculation Preview Card */}
        {selectedProduct && baseQuantity > 0 && (
          <div
            style={{
              margin: '1.5rem 0',
              padding: '1.25rem',
              background: isInsufficientStock ? '#fff5f5' : '#f0fdf4',
              border: `1px solid ${isInsufficientStock ? '#feb2b2' : '#bbf7d0'}`,
              borderRadius: '8px',
            }}
          >
            <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05em' }}>
              Live Calculation Preview ({isIn ? 'Stock Addition' : 'Stock Deduction'})
            </h3>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: '1rem',
              }}
            >
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>Current Stock</span>
                <div style={{ fontWeight: 600 }}>{formatQuantityWithUnit(currentStock, 'piece')}</div>
              </div>
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>Adjustment</span>
                <div style={{ fontWeight: 600, color: isIn ? '#16a34a' : '#dc2626' }}>
                  {isIn ? `+${formatQuantityWithUnit(baseQuantity, 'piece')}` : `-${formatQuantityWithUnit(baseQuantity, 'piece')}`}
                </div>
              </div>
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>New Stock</span>
                <div style={{ fontWeight: 700, color: isInsufficientStock ? '#dc2626' : '#111' }}>
                  {formatQuantityWithUnit(newStock, 'piece')}
                </div>
              </div>
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>Current WAC</span>
                <div style={{ fontWeight: 600 }}>{money(currentWac)} / pc</div>
              </div>
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>
                  {isIn ? 'Adjustment Cost' : 'Cost Snapshot'}
                </span>
                <div style={{ fontWeight: 600 }}>{money(effectiveUnitCost)} / pc</div>
              </div>
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>New WAC</span>
                <div style={{ fontWeight: 600 }}>{money(newWac)} / pc</div>
              </div>
              <div>
                <span style={{ fontSize: '0.85em', color: '#555' }}>Adjustment Value</span>
                <div style={{ fontWeight: 700, fontSize: '1.1em' }}>{money(adjustmentValue)}</div>
              </div>
            </div>

            {isInsufficientStock && (
              <div
                style={{
                  marginTop: '0.75rem',
                  padding: '0.5rem 0.75rem',
                  background: '#fee2e2',
                  color: '#991b1b',
                  borderRadius: '4px',
                  fontWeight: 600,
                  fontSize: '0.9em',
                }}
              >
                Insufficient stock for this adjustment. Available: {currentStock} pieces, Requested:{' '}
                {baseQuantity} pieces.
              </div>
            )}
          </div>
        )}

        <div className="form-actions" style={{ marginTop: '1.5rem' }}>
          <button
            type="submit"
            className="primary-button"
            disabled={busy || isInsufficientStock || !selectedProduct}
          >
            {busy ? 'Posting Adjustment...' : 'Post Adjustment'}
          </button>
          <Link className="secondary-button" to="/inventory/adjustments">
            Cancel
          </Link>
        </div>
      </form>
    </section>
  )
}
