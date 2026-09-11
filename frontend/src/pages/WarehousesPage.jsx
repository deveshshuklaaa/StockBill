import { useEffect, useState } from 'react'
import { apiErrorMessage } from '../api/client'
import { fetchWarehouseSummary } from '../api/warehouses'
import StatusMessage from '../components/StatusMessage'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }
function qty(value) { return Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 3 }) }

export default function WarehousesPage() {
  const [warehouses, setWarehouses] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setBusy(true); setError('')
    fetchWarehouseSummary()
      .then(setWarehouses)
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setBusy(false))
  }, [])

  const totalValue = warehouses.reduce((sum, w) => sum + Number(w.total_value), 0)
  const totalProducts = warehouses.reduce((sum, w) => sum + Number(w.product_count), 0)

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Configuration</p>
        <h1>Warehouses</h1>
        <p className="page-subtitle">Warehouse locations and inventory summaries.</p>
      </div>
    </header>
    <StatusMessage>{error}</StatusMessage>

    {!busy && warehouses.length > 0 && (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
        <div className="info-card">
          <div className="info-label">Total Warehouses</div>
          <div className="info-value"><strong>{warehouses.length}</strong></div>
        </div>
        <div className="info-card">
          <div className="info-label">Total Products in Stock</div>
          <div className="info-value"><strong>{totalProducts}</strong></div>
        </div>
        <div className="info-card">
          <div className="info-label">Total Inventory Value</div>
          <div className="info-value"><strong>{money(totalValue)}</strong></div>
        </div>
      </div>
    )}

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading warehouses...' : `${warehouses.length} warehouse${warehouses.length === 1 ? '' : 's'}`}</span>
      </div>
      {busy ? <div className="empty-state">Loading warehouses...</div> : warehouses.length === 0 ? (
        <div className="empty-state">No warehouses configured yet.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Code</th>
                <th style={{ textAlign: 'right' }}>Products in Stock</th>
                <th style={{ textAlign: 'right' }}>Total Quantity</th>
                <th style={{ textAlign: 'right' }}>Inventory Value</th>
              </tr>
            </thead>
            <tbody>
              {warehouses.map((warehouse) => (
                <tr key={warehouse.warehouse}>
                  <td><strong>{warehouse.name}</strong></td>
                  <td><code>{warehouse.code}</code></td>
                  <td style={{ textAlign: 'right' }}>{warehouse.product_count}</td>
                  <td style={{ textAlign: 'right' }}>{qty(warehouse.total_quantity)}</td>
                  <td style={{ textAlign: 'right' }}><strong>{money(warehouse.total_value)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  </section>
}
