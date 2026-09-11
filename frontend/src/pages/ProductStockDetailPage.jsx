import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchProductInventory, fetchStockLedger } from '../api/inventory'
import StatusMessage from '../components/StatusMessage'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }
function qty(value) { return Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 3 }) }

function formatAttributes(attributes) {
  if (!attributes || Object.keys(attributes).length === 0) return null
  const parts = []
  if (attributes.net_weight) parts.push(`${attributes.net_weight}${attributes.net_weight_unit || ''}`)
  if (attributes.units_per_master_box) parts.push(`${attributes.units_per_master_box} per M.Box`)
  return parts.join(' · ')
}

const MOVEMENT_LABELS = {
  OPENING_STOCK: 'Opening Stock',
  PURCHASE: 'Purchase',
  PURCHASE_REVERSAL: 'Purchase Reversal',
  SALE: 'Sale',
  SALE_REVERSAL: 'Sale Reversal',
  SALES_RETURN: 'Sales Return',
  PURCHASE_RETURN: 'Purchase Return',
  DAMAGE: 'Damage',
  ADJUSTMENT: 'Adjustment',
  TRANSFER_IN: 'Transfer In',
  TRANSFER_OUT: 'Transfer Out',
}

export default function ProductStockDetailPage() {
  const { productId } = useParams()
  const [productBalances, setProductBalances] = useState([])
  const [movements, setMovements] = useState([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [hasPrevious, setHasPrevious] = useState(false)
  const [busy, setBusy] = useState(true)
  const [movementsBusy, setMovementsBusy] = useState(true)
  const [error, setError] = useState('')
  const latestLoad = useRef(0)

  useEffect(() => {
    setBusy(true); setError('')
    fetchProductInventory(productId)
      .then((data) => {
        setProductBalances(data)
      })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setBusy(false))
  }, [productId])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setMovementsBusy(true)
    fetchStockLedger({ page, product: productId })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setMovements(Array.isArray(data) ? data : data.results || [])
        setTotal(Number(data.count ?? 0))
        setHasNext(Boolean(data.next))
        setHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestLoad.current) return
        if (err?.response?.status === 404 && page > 1) { setPage(1); return }
      })
      .finally(() => { if (requestId === latestLoad.current) setMovementsBusy(false) })
  }, [page, productId])

  if (busy) {
    return <section className="page-section"><div className="empty-state">Loading product details...</div></section>
  }

  if (productBalances.length === 0) {
    return <section className="page-section">
      <StatusMessage>{error || 'Product not found in inventory.'}</StatusMessage>
      <Link to="/inventory" className="secondary-button">← Back to inventory</Link>
    </section>
  }

  const firstBalance = productBalances[0]
  const totalStock = productBalances.reduce((sum, b) => sum + Number(b.quantity_on_hand), 0)
  const totalValue = productBalances.reduce((sum, b) => sum + Number(b.quantity_on_hand) * Number(b.average_cost), 0)
  const attrs = formatAttributes(firstBalance.product_attributes)

  const totalPages = Math.max(1, Math.ceil(total / 25))

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">
          <Link to="/inventory" style={{ color: 'inherit', textDecoration: 'none' }}>Inventory</Link> / Product detail
        </p>
        <h1>{firstBalance.product_name}</h1>
        {attrs && <p className="page-subtitle">{attrs}</p>}
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
      <div className="info-card">
        <div className="info-label">SKU</div>
        <div className="info-value">{firstBalance.product_sku || '-'}</div>
      </div>
      <div className="info-card">
        <div className="info-label">Category</div>
        <div className="info-value">{firstBalance.product_category_name || '-'}</div>
      </div>
      <div className="info-card">
        <div className="info-label">MRP</div>
        <div className="info-value">{firstBalance.product_mrp ? money(firstBalance.product_mrp) : '-'}</div>
      </div>
      <div className="info-card">
        <div className="info-label">Total Stock</div>
        <div className="info-value"><strong>{qty(totalStock)} {firstBalance.product_base_unit}</strong></div>
      </div>
      <div className="info-card">
        <div className="info-label">Total Value</div>
        <div className="info-value"><strong>{money(totalValue)}</strong></div>
      </div>
    </div>

    <h2 style={{ marginBottom: '1rem' }}>Stock by Warehouse</h2>
    <div className="table-frame" style={{ marginBottom: '2rem' }}>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Warehouse</th>
              <th style={{ textAlign: 'right' }}>Quantity</th>
              <th style={{ textAlign: 'right' }}>Avg Cost</th>
              <th style={{ textAlign: 'right' }}>Value</th>
            </tr>
          </thead>
          <tbody>
            {productBalances.map((balance) => (
              <tr key={balance.id}>
                <td><strong>{balance.warehouse_name}</strong></td>
                <td style={{ textAlign: 'right' }}>{qty(balance.quantity_on_hand)}</td>
                <td style={{ textAlign: 'right' }}>{money(balance.average_cost)}</td>
                <td style={{ textAlign: 'right' }}><strong>{money(Number(balance.quantity_on_hand) * Number(balance.average_cost))}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>

    <h2 style={{ marginBottom: '1rem' }}>Stock Movements</h2>
    <div className="table-frame">
      <div className="table-meta">
        <span>{movementsBusy ? 'Loading movements...' : `${total} movement${total === 1 ? '' : 's'}`}</span>
      </div>
      {movementsBusy ? <div className="empty-state">Loading movements...</div> : movements.length === 0 ? (
        <div className="empty-state">No stock movements recorded for this product.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Date/Time</th>
                <th>Type</th>
                <th>Reference</th>
                <th>Warehouse</th>
                <th style={{ textAlign: 'right' }}>Qty Change</th>
                <th style={{ textAlign: 'right' }}>Unit Cost</th>
                <th>User</th>
              </tr>
            </thead>
            <tbody>
              {movements.map((movement) => {
                const isReversal = movement.movement_type.includes('REVERSAL')
                return (
                  <tr key={movement.id} className={isReversal ? 'archived-row' : ''}>
                    <td>{new Date(movement.created_at).toLocaleString('en-IN')}</td>
                    <td>
                      <span className={isReversal ? 'state-cancelled' : 'type-chip'}>
                        {MOVEMENT_LABELS[movement.movement_type] || movement.movement_type}
                      </span>
                    </td>
                    <td><code>{movement.reference || '-'}</code></td>
                    <td>{movement.warehouse_name}</td>
                    <td style={{ textAlign: 'right', color: Number(movement.quantity_change) >= 0 ? '#16a34a' : '#dc2626' }}>
                      <strong>{Number(movement.quantity_change) >= 0 ? '+' : ''}{qty(movement.quantity_change)}</strong>
                    </td>
                    <td style={{ textAlign: 'right' }}>{movement.unit_cost ? money(movement.unit_cost) : '-'}</td>
                    <td>{movement.created_by_username || '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-meta pager" role="navigation" aria-label="Movement pagination">
        <button
          className="pager-button"
          onClick={() => setPage((c) => Math.max(1, c - 1))}
          disabled={!hasPrevious || movementsBusy}
        >
          ← Previous
        </button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} movements` : ''}</span>
        <button
          className="pager-button"
          onClick={() => setPage((c) => c + 1)}
          disabled={!hasNext || movementsBusy}
        >
          Next →
        </button>
      </div>
    </div>
  </section>
}
