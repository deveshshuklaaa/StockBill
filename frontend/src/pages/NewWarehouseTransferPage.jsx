import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchProductInventory } from '../api/inventory'
import { fetchWarehouses, searchPurchaseProducts } from '../api/purchases'
import { createTransfer, fetchNextTransferNumber } from '../api/transfers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'
import { formatQuantityWithUnit, masterBoxSize } from '../utils/format'

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

const REASONS = [
  'Stock Replenishment',
  'Inter-branch Transfer',
  'Order Fulfillment',
  'Excess Stock Rebalancing',
  'Other',
]

export default function NewWarehouseTransferPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'

  const [warehouses, setWarehouses] = useState([])
  const [sourceWarehouseId, setSourceWarehouseId] = useState('')
  const [destinationWarehouseId, setDestinationWarehouseId] = useState('')

  const [productSearch, setProductSearch] = useState('')
  const [productResults, setProductResults] = useState([])
  const [productBusy, setProductBusy] = useState(false)
  const [selectedProduct, setSelectedProduct] = useState(null)

  const [inventoryBalances, setInventoryBalances] = useState([])
  const [balanceBusy, setBalanceBusy] = useState(false)

  const [unit, setUnit] = useState('piece')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('Stock Replenishment')
  const [note, setNote] = useState('')
  const [effectiveDate, setEffectiveDate] = useState(today())
  const [nextNumber, setNextNumber] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Load warehouses & initial preview number
  useEffect(() => {
    fetchWarehouses({ is_active: 'true' })
      .then((data) => {
        const activeWarehouses = data || []
        setWarehouses(activeWarehouses)
        if (activeWarehouses.length > 0) {
          setSourceWarehouseId(String(activeWarehouses[0].id))
          if (activeWarehouses.length > 1) {
            setDestinationWarehouseId(String(activeWarehouses[1].id))
          }
        }
      })
      .catch(() => {})

    fetchNextTransferNumber(today())
      .then(setNextNumber)
      .catch(() => {})
  }, [])

  // Update preview number when date changes
  useEffect(() => {
    if (effectiveDate) {
      fetchNextTransferNumber(effectiveDate)
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

  // Load inventory balances across warehouses for selected product
  useEffect(() => {
    if (!selectedProduct?.id) {
      setInventoryBalances([])
      return
    }
    setBalanceBusy(true)
    fetchProductInventory(selectedProduct.id)
      .then((balances) => {
        setInventoryBalances(balances || [])
      })
      .catch(() => setInventoryBalances([]) )
      .finally(() => setBalanceBusy(false))
  }, [selectedProduct])

  const packSize = useMemo(() => {
    return selectedProduct ? masterBoxSize(selectedProduct) : null
  }, [selectedProduct])

  useEffect(() => {
    if (!packSize && unit === 'master box') {
      setUnit('piece')
    }
  }, [packSize, unit])

  // Source balance & Destination balance
  const sourceBalance = useMemo(() => {
    return inventoryBalances.find((b) => String(b.warehouse) === String(sourceWarehouseId)) || null
  }, [inventoryBalances, sourceWarehouseId])

  const destBalance = useMemo(() => {
    return inventoryBalances.find((b) => String(b.warehouse) === String(destinationWarehouseId)) || null
  }, [inventoryBalances, destinationWarehouseId])

  const sourceStock = Number(sourceBalance?.quantity_on_hand ?? 0)
  const sourceWac = Number(sourceBalance?.average_cost ?? 0)
  const destStock = Number(destBalance?.quantity_on_hand ?? 0)
  const destWac = Number(destBalance?.average_cost ?? 0)

  const conversionFactor = unit === 'master box' && packSize ? packSize : 1
  const enteredQty = Number(quantity) || 0
  const baseQuantity = enteredQty > 0 ? enteredQty * conversionFactor : 0
  const transferValue = baseQuantity * sourceWac

  // Destination WAC calculation preview
  const newDestStock = destStock + baseQuantity
  let projectedDestWac = destWac
  if (baseQuantity > 0) {
    if (destStock <= 0) {
      projectedDestWac = sourceWac
    } else {
      projectedDestWac = ((destStock * destWac) + (baseQuantity * sourceWac)) / newDestStock
    }
  }

  // Validations
  const sameWarehouse = Boolean(
    sourceWarehouseId && destinationWarehouseId && sourceWarehouseId === destinationWarehouseId
  )
  const insufficientStock = Boolean(
    selectedProduct && sourceBalance && baseQuantity > sourceStock
  )
  const futureDate = effectiveDate > today()
  const otherNeedsNote = reason === 'Other' && !note.trim()

  const canSubmit = Boolean(
    isAdmin &&
      selectedProduct &&
      sourceWarehouseId &&
      destinationWarehouseId &&
      !sameWarehouse &&
      enteredQty > 0 &&
      !insufficientStock &&
      !futureDate &&
      reason &&
      !otherNeedsNote &&
      !submitting
  )

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError('')

    const idempotencyKey = `trf-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
    const payload = {
      product: selectedProduct.id,
      source_warehouse: Number(sourceWarehouseId),
      destination_warehouse: Number(destinationWarehouseId),
      quantity: String(enteredQty),
      unit,
      conversion_factor: String(conversionFactor),
      reason,
      note: note.trim(),
      effective_date: effectiveDate,
    }

    try {
      const result = await createTransfer(payload, { idempotencyKey })
      navigate(`/inventory/transfers/${result.id}`)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const handleSelectProduct = (prod) => {
    setSelectedProduct(prod)
    setProductSearch(prod.name)
    setProductResults([])
  }

  const handleClearProduct = () => {
    setSelectedProduct(null)
    setProductSearch('')
    setProductResults([])
    setQuantity('')
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
          <h1>New Warehouse Transfer</h1>
          <p className="page-subtitle">
            Transfer stock between warehouses without altering total company inventory valuation.
          </p>
        </div>
      </header>

      <StatusMessage>{error}</StatusMessage>

      {!isAdmin && (
        <div className="status-message error" style={{ marginBottom: '16px' }}>
          Only administrator accounts are authorized to initiate warehouse transfers.
        </div>
      )}

      {/* Concept clarity callout banner */}
      <div
        style={{
          background: '#f2f6f3',
          border: '1px solid #cad8cf',
          borderRadius: '8px',
          padding: '14px 18px',
          marginBottom: '20px',
          display: 'flex',
          gap: '14px',
          alignItems: 'center',
        }}
      >
        <div style={{ fontSize: '24px' }}>🔄</div>
        <div style={{ fontSize: '13px', color: '#274b38', lineHeight: 1.5 }}>
          <strong>Zero Net Valuation Change:</strong> Transferred items leave the source warehouse at its current
          weighted average cost (WAC) and enter the destination warehouse at the exact same cost basis. Company-wide
          total stock and valuation remain invariant.
        </div>
      </div>

      <form onSubmit={handleSubmit} className="form-card" style={{ maxWidth: '820px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
          {/* Transfer Reference & Date */}
          <div>
            <label htmlFor="preview-trf-number">Transfer # (Auto-assigned)</label>
            <input
              id="preview-trf-number"
              type="text"
              readOnly
              value={nextNumber || 'TRF/YY-YY/XXXXXX'}
              style={{ backgroundColor: '#f5f5f5', color: '#555', cursor: 'not-allowed' }}
            />
          </div>
          <div>
            <label htmlFor="trf-effective-date">Effective Date *</label>
            <input
              id="trf-effective-date"
              type="date"
              max={today()}
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
              required
            />
            {futureDate && (
              <p style={{ color: '#c53030', fontSize: '11px', margin: '4px 0 0' }}>
                Effective date cannot be in the future.
              </p>
            )}
          </div>
        </div>

        {/* Warehouses Selection */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr auto 1fr',
            gap: '12px',
            alignItems: 'center',
            marginTop: '16px',
            padding: '16px',
            backgroundColor: '#fafcfa',
            borderRadius: '8px',
            border: '1px solid #e1e8e3',
          }}
        >
          <div>
            <label htmlFor="trf-source-warehouse" style={{ fontWeight: 600, color: '#912018' }}>
              Source Warehouse (Stock Out) *
            </label>
            <select
              id="trf-source-warehouse"
              value={sourceWarehouseId}
              onChange={(e) => setSourceWarehouseId(e.target.value)}
              required
            >
              {warehouses.map((wh) => (
                <option key={wh.id} value={wh.id}>
                  {wh.name} ({wh.code})
                </option>
              ))}
            </select>
            {sourceWarehouseId && (
              <span style={{ display: 'block', fontSize: '11px', color: '#687e71', marginTop: '4px' }}>
                {balanceBusy
                  ? 'Checking stock...'
                  : selectedProduct
                  ? `Available stock: ${formatQuantityWithUnit(sourceStock, 'piece')} @ ${money(sourceWac)}`
                  : 'Select a product to view stock'}
              </span>
            )}
          </div>

          <div style={{ textAlign: 'center', fontSize: '20px', color: '#274b38', paddingTop: '16px' }}>
            ➔
          </div>

          <div>
            <label htmlFor="trf-dest-warehouse" style={{ fontWeight: 600, color: '#027a48' }}>
              Destination Warehouse (Stock In) *
            </label>
            <select
              id="trf-dest-warehouse"
              value={destinationWarehouseId}
              onChange={(e) => setDestinationWarehouseId(e.target.value)}
              required
            >
              {warehouses.map((wh) => (
                <option key={wh.id} value={wh.id}>
                  {wh.name} ({wh.code})
                </option>
              ))}
            </select>
            {destinationWarehouseId && (
              <span style={{ display: 'block', fontSize: '11px', color: '#687e71', marginTop: '4px' }}>
                {balanceBusy
                  ? 'Checking stock...'
                  : selectedProduct
                  ? `Current stock: ${formatQuantityWithUnit(destStock, 'piece')} @ ${money(destWac)}`
                  : 'Select a product to view stock'}
              </span>
            )}
          </div>
        </div>

        {sameWarehouse && (
          <div style={{ color: '#c53030', fontSize: '12px', marginTop: '6px', fontWeight: 600 }}>
            Source and destination warehouses must be different.
          </div>
        )}

        {/* Product Search & Selection */}
        <div style={{ marginTop: '16px', position: 'relative' }}>
          <label htmlFor="trf-product-search">Product to Transfer *</label>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              id="trf-product-search"
              type="text"
              placeholder="Type to search product catalogue..."
              value={productSearch}
              onChange={(e) => {
                setProductSearch(e.target.value)
                if (selectedProduct) setSelectedProduct(null)
              }}
              readOnly={Boolean(selectedProduct)}
              style={selectedProduct ? { backgroundColor: '#f8faf8', fontWeight: 600 } : {}}
              required
            />
            {selectedProduct && (
              <button
                type="button"
                className="quiet-button"
                style={{ border: '1px solid #cbd5cd' }}
                onClick={handleClearProduct}
              >
                Change
              </button>
            )}
          </div>

          {/* Autocomplete dropdown */}
          {productResults.length > 0 && !selectedProduct && (
            <div
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                backgroundColor: '#fff',
                border: '1px solid #cbd5cd',
                borderRadius: '6px',
                zIndex: 50,
                maxHeight: '220px',
                overflowY: 'auto',
                boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
              }}
            >
              {productResults.map((p) => (
                <div
                  key={p.id}
                  onClick={() => handleSelectProduct(p)}
                  style={{
                    padding: '8px 12px',
                    cursor: 'pointer',
                    borderBottom: '1px solid #f0f0f0',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f4f7f4')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  <div style={{ fontWeight: 600, color: '#1e382b' }}>{p.name}</div>
                  <div style={{ fontSize: '11px', color: '#667d70' }}>
                    SKU: {p.sku || '—'} · MRP: {money(p.mrp)}
                    {masterBoxSize(p) ? ` · Master Box: ${masterBoxSize(p)} pcs` : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
          {productBusy && (
            <span style={{ fontSize: '11px', color: '#687e71', marginTop: '4px', display: 'block' }}>
              Searching catalogue...
            </span>
          )}
        </div>

        {/* Quantity, Unit & Conversion */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '16px',
            marginTop: '16px',
          }}
        >
          <div>
            <label htmlFor="trf-quantity">Quantity *</label>
            <input
              id="trf-quantity"
              type="number"
              step="0.001"
              min="0.001"
              placeholder="e.g. 10"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              required
            />
            {insufficientStock && (
              <p style={{ color: '#c53030', fontSize: '11px', margin: '4px 0 0' }}>
                Requested quantity ({baseQuantity} pcs) exceeds source available stock ({sourceStock} pcs).
              </p>
            )}
          </div>

          <div>
            <label htmlFor="trf-unit">Unit *</label>
            <select
              id="trf-unit"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              required
            >
              <option value="piece">Piece (Base Unit)</option>
              {packSize ? (
                <option value="master box">Master Box ({packSize} pcs)</option>
              ) : null}
            </select>
            {!packSize && (
              <span style={{ fontSize: '11px', color: '#687e71', display: 'block', marginTop: '4px' }}>
                Item has no master box pack size configured.
              </span>
            )}
          </div>

          <div>
            <label htmlFor="trf-base-qty">Total Base Quantity (Authoritative)</label>
            <input
              id="trf-base-qty"
              type="text"
              readOnly
              value={formatQuantityWithUnit(baseQuantity, 'piece')}
              style={{ backgroundColor: '#f5f5f5', color: '#1e382b', fontWeight: 600 }}
            />
          </div>
        </div>

        {/* Costing & Valuation (Read-only WAC and Calculated Transfer Value) */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '16px',
            marginTop: '16px',
            padding: '14px 16px',
            backgroundColor: '#f7faf8',
            borderRadius: '6px',
            border: '1px solid #d9e3dc',
          }}
        >
          <div>
            <label style={{ fontSize: '12px', color: '#55695e' }}>Transfer Cost / Piece (Source WAC)</label>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e382b', marginTop: '4px' }}>
              {money(sourceWac)}
            </div>
            <span style={{ fontSize: '11px', color: '#6b8273' }}>
              Snapshot taken from source warehouse at time of transfer
            </span>
          </div>

          <div>
            <label style={{ fontSize: '12px', color: '#55695e' }}>Transfer Value</label>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e382b', marginTop: '4px' }}>
              {money(transferValue)}
            </div>
            <span style={{ fontSize: '11px', color: '#6b8273' }}>
              {baseQuantity} pcs × {money(sourceWac)}
            </span>
          </div>

          <div>
            <label style={{ fontSize: '12px', color: '#55695e' }}>Projected Destination WAC</label>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#027a48', marginTop: '4px' }}>
              {money(projectedDestWac)}
            </div>
            <span style={{ fontSize: '11px', color: '#6b8273' }}>
              {destStock <= 0 ? 'Destination stock is 0; enters at transfer cost' : 'Weighted average across current + incoming stock'}
            </span>
          </div>
        </div>

        {/* Reason & Notes */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '16px',
            marginTop: '16px',
          }}
        >
          <div>
            <label htmlFor="trf-reason">Reason for Transfer *</label>
            <select
              id="trf-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            >
              {REASONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="trf-note">Note {reason === 'Other' ? '*' : '(Optional)'}</label>
            <input
              id="trf-note"
              type="text"
              placeholder={reason === 'Other' ? 'Mandatory explanation for Other' : 'Additional operational notes'}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              required={reason === 'Other'}
            />
            {otherNeedsNote && (
              <span style={{ color: '#c53030', fontSize: '11px', display: 'block', marginTop: '4px' }}>
                A note is mandatory when selecting reason &quot;Other&quot;.
              </span>
            )}
          </div>
        </div>

        <div style={{ marginTop: '24px', display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
          <Link to="/inventory/transfers" className="quiet-button" style={{ border: '1px solid #cbd5cd' }}>
            Cancel
          </Link>
          <button
            type="submit"
            className="primary-button"
            disabled={!canSubmit}
            style={{ minWidth: '140px' }}
          >
            {submitting ? 'Transferring...' : 'Execute Transfer'}
          </button>
        </div>
      </form>
    </section>
  )
}
