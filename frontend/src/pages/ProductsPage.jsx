import { useEffect, useState } from 'react'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

const emptyProduct = { name: '', category: '', brand: '', unit_type: 'piece', unit_conversion_factor: '1', default_price: '', cost_price: '', tax_slab: '18', current_stock: '0', low_stock_threshold: '0' }

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }
function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

export default function ProductsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [products, setProducts] = useState([])
  const [form, setForm] = useState(emptyProduct)
  const [editing, setEditing] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function loadProducts() {
    setBusy(true)
    setError('')
    try { setProducts(rows((await api.get('/products/')).data)) }
    catch (err) { setError(apiErrorMessage(err)) }
    finally { setBusy(false) }
  }
  useEffect(() => { loadProducts() }, [])

  function beginCreate() { setEditing(null); setForm(emptyProduct); setShowForm(true) }
  function beginEdit(product) {
    setEditing(product.id)
    setForm(Object.fromEntries(Object.keys(emptyProduct).map((key) => [key, product[key] ?? emptyProduct[key]])))
    setShowForm(true)
  }
  function change(event) { setForm({ ...form, [event.target.name]: event.target.value }) }

  async function save(event) {
    event.preventDefault(); setSaving(true); setError('')
    const payload = { ...form, unit_conversion_factor: Number(form.unit_conversion_factor), default_price: Number(form.default_price), cost_price: Number(form.cost_price), tax_slab: Number(form.tax_slab), current_stock: Number(form.current_stock), low_stock_threshold: Number(form.low_stock_threshold) }
    try {
      if (editing) await api.patch(`/products/${editing}/`, payload)
      else await api.post('/products/', payload)
      setShowForm(false); await loadProducts()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }
  async function remove(product) {
    if (!window.confirm(`Delete ${product.name}?`)) return
    try { await api.delete(`/products/${product.id}/`); await loadProducts() }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Inventory / catalogue</p><h1>Products</h1><p className="page-subtitle">Stock, pricing, and tax settings in one working list.</p></div>
      {isAdmin && <button className="primary-button" onClick={beginCreate}>Add product</button>}
    </header>
    <StatusMessage>{error}</StatusMessage>
    {showForm && isAdmin && <form className="record-form" onSubmit={save}>
      <div className="form-heading"><div><p className="eyebrow">{editing ? 'Edit record' : 'New record'}</p><h2>{editing ? 'Update product' : 'Add product'}</h2></div><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Close</button></div>
      <div className="form-grid">
        <label>Name<input name="name" value={form.name} onChange={change} required /></label><label>Category<input name="category" value={form.category} onChange={change} /></label><label>Brand<input name="brand" value={form.brand} onChange={change} /></label>
        <label>Unit type<select name="unit_type" value={form.unit_type} onChange={change}><option value="piece">Piece</option><option value="box">Box</option><option value="carton">Carton</option></select></label><label>Conversion factor<input name="unit_conversion_factor" type="number" min="0.001" step="0.001" value={form.unit_conversion_factor} onChange={change} required /></label><label>Tax slab<select name="tax_slab" value={form.tax_slab} onChange={change}><option value="5">5%</option><option value="18">18%</option><option value="40">40%</option></select></label>
        <label>Default price<input name="default_price" type="number" min="0" step="0.01" value={form.default_price} onChange={change} required /></label><label>Cost price<input name="cost_price" type="number" min="0" step="0.01" value={form.cost_price} onChange={change} required /></label><label>Current stock<input name="current_stock" type="number" min="0" step="0.001" value={form.current_stock} onChange={change} required /></label><label>Low-stock threshold<input name="low_stock_threshold" type="number" min="0" step="0.001" value={form.low_stock_threshold} onChange={change} required /></label>
      </div><div className="form-actions"><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? 'Saving...' : 'Save product'}</button></div>
    </form>}
    <div className="table-frame"><div className="table-meta"><span>{products.length} products</span><span className="table-note">Values shown in INR</span></div>{busy ? <div className="empty-state">Loading products...</div> : products.length === 0 ? <div className="empty-state">No products yet.</div> : <div className="table-scroll"><table><thead><tr><th>Product</th><th>Category</th><th>Unit</th><th>Stock</th>{isAdmin && <th>Cost price</th>}<th>Default price</th><th>Tax</th>{isAdmin && <th aria-label="Actions" />}</tr></thead><tbody>{products.map((product) => { const low = Number(product.current_stock) <= Number(product.low_stock_threshold); return <tr key={product.id}><td><strong>{product.name}</strong><small>{product.brand || 'No brand set'}</small></td><td>{product.category || '-'}</td><td>{product.unit_type}</td><td><span className={low ? 'stock-value low' : 'stock-value'}>{product.current_stock}{low && <em>Low</em>}</span></td>{isAdmin && <td>{money(product.cost_price)}</td>}<td>{money(product.default_price)}</td><td><span className="tax-chip">{product.tax_slab}%</span></td>{isAdmin && <td><div className="row-actions"><button className="text-button" onClick={() => beginEdit(product)}>Edit</button><button className="text-button danger" onClick={() => remove(product)}>Delete</button></div></td>}</tr> })}</tbody></table></div>}</div>
  </section>
}
