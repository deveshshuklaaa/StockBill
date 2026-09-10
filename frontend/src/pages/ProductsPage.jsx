import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import ProductForm, {
  attributeErrorText,
  buildProductPayload,
  emptyProductForm,
  loadCategorySchema,
  mapFieldErrors,
} from '../components/ProductForm'
import { useAuth } from '../context/AuthContext'

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }
function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

function formatAttributes(attributes) {
  return Object.entries(attributes || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([code, value]) => `${code.replace(/_/g, ' ')}: ${String(value)}`)
    .join(' · ')
}

export default function ProductsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'
  const [products, setProducts] = useState([])
  const [categories, setCategories] = useState([])
  const [taxRates, setTaxRates] = useState([])
  const [schema, setSchema] = useState([])
  const [form, setForm] = useState(emptyProductForm)
  const [attributeValues, setAttributeValues] = useState({})
  const [showForm, setShowForm] = useState(false)
  const [fieldErrors, setFieldErrors] = useState({})
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('active')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [hasPrevious, setHasPrevious] = useState(false)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const latestLoad = useRef(0)

  const pageSize = 25

  // Debounce the search box so typing does not fire a request per keystroke.
  // The reset to page 1 is batched with the search update so the load effect
  // below runs exactly once per change.
  useEffect(() => {
    const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  async function loadProducts(pageToLoad = 1) {
    setBusy(true); setError('')
    const requestId = ++latestLoad.current
    try {
      const params = { page: pageToLoad }
      if (search) params.search = search
      if (categoryFilter) params.category = categoryFilter
      if (statusFilter) params.is_active = statusFilter === 'active' ? 'true' : 'false'
      const { data } = await api.get('/products/', { params })
      if (requestId !== latestLoad.current) return // superseded by a newer request
      setProducts(rows(data))
      setTotal(Number(data.count ?? rows(data).length ?? 0))
      setHasNext(Boolean(data.next))
      setHasPrevious(Boolean(data.previous))
    } catch (err) {
      if (requestId !== latestLoad.current) return
      // The current page fell out of range (e.g. filtering shrank the result
      // set); fall back to page 1 instead of showing a dead-end error.
      if (err?.response?.status === 404 && pageToLoad > 1) { setPage(1); return }
      setError(apiErrorMessage(err))
    } finally {
      if (requestId === latestLoad.current) setBusy(false)
    }
  }

  useEffect(() => {
    loadProducts(page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, categoryFilter, statusFilter])

  useEffect(() => {
    api.get('/categories/').then(({ data }) => setCategories(rows(data))).catch(() => {})
    api.get('/tax-rates/').then(({ data }) => setTaxRates(rows(data))).catch(() => {})
  }, [])

  // Load the attribute schema whenever the form category changes.
  useEffect(() => {
    const categoryId = form.catalogue_category
    if (!categoryId) { setSchema([]); return }
    let cancelled = false
    loadCategorySchema(categoryId).then((loaded) => { if (!cancelled) setSchema(loaded) })
    return () => { cancelled = true }
  }, [form.catalogue_category])

  const pageOf = (page - 1) * pageSize
  const lastOnPage = Math.min(pageOf + products.length, total)
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  function beginCreate() {
    setForm(emptyProductForm); setAttributeValues({}); setFieldErrors({}); setShowForm(true)
  }

  function beginEdit(product) {
    navigate(`/products/${product.id}/edit`)
  }

  async function save(event) {
    event.preventDefault(); setSaving(true); setError(''); setFieldErrors({})
    const localErrors = {}
    schema.forEach((s) => {
      const problem = attributeErrorText(s, attributeValues[s.code])
      if (problem) localErrors[s.code] = problem
    })
    if (Object.keys(localErrors).length) { setFieldErrors(localErrors); setSaving(false); return }

    const payload = buildProductPayload({ form, attributeValues, isAdmin, isEdit: false })
    try {
      await api.post('/products/', payload)
      setShowForm(false); await loadProducts(page)
    } catch (err) {
      if (err?.response?.status === 400) setFieldErrors(mapFieldErrors(err.response.data, schema))
      else setError(apiErrorMessage(err))
    } finally { setSaving(false) }
  }

  async function archive(product) {
    if (!window.confirm(`Archive ${product.name}? It stays in history but cannot be sold until reactivated.`)) return
    try { await api.delete(`/products/${product.id}/`); await loadProducts(page) }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  async function reactivate(product) {
    try { await api.patch(`/products/${product.id}/`, { is_active: true }); await loadProducts(page) }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Inventory / catalogue</p><h1>Products</h1><p className="page-subtitle">Metadata-driven catalogue with category-specific attributes.</p></div>
      {isAdmin && <button className="primary-button" onClick={beginCreate}>Add product</button>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading products...' : `${total === 0 ? 0 : pageOf + 1}–${lastOnPage} of ${total} products`}</span>
        <div className="filter-row">
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Name, SKU, brand" aria-label="Search products" /></label>
          <label className="filter-field">Category<select value={categoryFilter} onChange={(e) => { setCategoryFilter(e.target.value); setPage(1) }} aria-label="Filter by category"><option value="">All</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label className="filter-field">Status<select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }} aria-label="Filter by status"><option value="active">Active</option><option value="inactive">Archived</option><option value="">All</option></select></label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading products...</div> : products.length === 0 ? <div className="empty-state">{search || categoryFilter || statusFilter !== '' ? 'No products match your filters.' : 'No products yet.'}</div> : <div className="table-scroll"><table>
        <thead><tr><th>Product</th><th>SKU</th><th>Category</th><th>Brand</th><th>MRP</th>{isAdmin && <th>Cost price</th>}<th>Selling price</th><th>Stock</th><th>Tax</th><th>Status</th>{isAdmin && <th aria-label="Actions" />}</tr></thead>
        <tbody>{products.map((product) => { const low = Number(product.current_stock) <= Number(product.low_stock_threshold); return <tr key={product.id} className={product.is_active ? '' : 'archived-row'}>
          <td><strong>{product.name}</strong><small className="attribute-summary">{formatAttributes(product.attributes)}</small></td>
          <td><code>{product.sku || '-'}</code></td>
          <td>{product.category_name || '-'}</td>
          <td>{product.brand || '-'}</td>
          <td>{product.mrp != null ? money(product.mrp) : '-'}</td>
          {isAdmin && <td>{money(product.cost_price)}</td>}
          <td>{money(product.default_price)}</td>
          <td><span className={low ? 'stock-value low' : 'stock-value'}>{product.current_stock}{low && <em>Low</em>}</span></td>
          <td><span className="tax-chip">{product.tax_rate != null ? `${Number(product.tax_rate).toFixed(0)}%` : '-'}</span></td>
          <td>{product.is_active ? 'Active' : 'Archived'}</td>
          {isAdmin && <td><div className="row-actions">
            <button className="text-button" onClick={() => beginEdit(product)}>Edit</button>
            {product.is_active
              ? <button className="text-button danger" onClick={() => archive(product)}>Archive</button>
              : <button className="text-button" onClick={() => reactivate(product)}>Reactivate</button>}
          </div></td>}
        </tr> })}</tbody>
      </table></div>}
      <div className="table-meta pager" role="navigation" aria-label="Product pagination">
        <button className="pager-button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={!hasPrevious || busy}>← Previous</button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} products` : ''}</span>
        <button className="pager-button" onClick={() => setPage((current) => current + 1)} disabled={!hasNext || busy}>Next →</button>
      </div>
    </div>

    {showForm && isAdmin && <ProductForm
      mode="create"
      form={form}
      setForm={setForm}
      attributeValues={attributeValues}
      setAttributeValues={setAttributeValues}
      categories={categories}
      taxRates={taxRates}
      schema={schema}
      fieldErrors={fieldErrors}
      onCancel={() => setShowForm(false)}
      onSubmit={save}
      submitting={saving}
      submitLabel="Save product"
    />}
  </section>
}
