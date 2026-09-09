import { useEffect, useRef, useState } from 'react'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

const emptyProduct = {
  name: '', sku: '', brand: '', catalogue_category: '',
  mrp: '', cost_price: '', default_price: '',
  base_unit: 'piece', tax: '', hsn_sac: '', is_tax_applicable: true,
  low_stock_threshold: '0',
}

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }
function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

function attributePlaceholder(schema) {
  if (schema.data_type === 'INTEGER') return 'Whole number'
  if (schema.data_type === 'DECIMAL') return `Number${schema.unit ? ` (${schema.unit})` : ''}`
  if (schema.data_type === 'DATE') return 'YYYY-MM-DD'
  return 'Text'
}

function attributeInputType(schema) {
  if (schema.data_type === 'INTEGER') return 'number'
  if (schema.data_type === 'DECIMAL') return 'number'
  if (schema.data_type === 'DATE') return 'date'
  return 'text'
}

function attributeStep(schema) {
  if (schema.data_type === 'INTEGER') return '1'
  if (schema.data_type === 'DECIMAL') return 'any'
  return undefined
}

function attributeErrorText(schema, value) {
  if (schema.is_required && (value === '' || value == null)) return `${schema.name} is required.`
  if (value === '' || value == null) return ''
  if (schema.data_type === 'INTEGER' && !/^-?\d+$/.test(String(value).trim())) return 'Enter a whole number.'
  if (schema.data_type === 'DECIMAL' && Number.isNaN(Number(value))) return 'Enter a valid number.'
  if (schema.data_type === 'DATE' && Number.isNaN(Date.parse(value))) return 'Enter a valid date.'
  return ''
}

function formatAttributes(attributes) {
  return Object.entries(attributes || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([code, value]) => `${code.replace(/_/g, ' ')}: ${String(value)}`)
    .join(' · ')
}

export default function ProductsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [products, setProducts] = useState([])
  const [categories, setCategories] = useState([])
  const [taxRates, setTaxRates] = useState([])
  const [schema, setSchema] = useState([])
  const [form, setForm] = useState(emptyProduct)
  const [attributeValues, setAttributeValues] = useState({})
  const [editing, setEditing] = useState(null)
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
    api.get(`/categories/${categoryId}/attributes/`)
      .then(({ data }) => { if (!cancelled) setSchema(Array.isArray(data) ? data : []) })
      .catch(() => { if (!cancelled) setSchema([]) })
    return () => { cancelled = true }
  }, [form.catalogue_category])

  const pageOf = (page - 1) * pageSize
  const lastOnPage = Math.min(pageOf + products.length, total)
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  function beginCreate() {
    setEditing(null); setForm(emptyProduct); setAttributeValues({}); setFieldErrors({}); setShowForm(true)
  }

  function beginEdit(product) {
    setEditing(product.id)
    setForm({
      name: product.name || '', sku: product.sku || '', brand: product.brand || '',
      catalogue_category: product.catalogue_category || '',
      mrp: product.mrp ?? '', cost_price: isAdmin ? (product.cost_price ?? '') : '',
      default_price: product.default_price ?? '',
      base_unit: product.base_unit || 'piece', tax: product.tax ?? '',
      hsn_sac: product.hsn_sac || '', is_tax_applicable: product.is_tax_applicable !== false,
      low_stock_threshold: product.low_stock_threshold ?? '0',
    })
    setAttributeValues({ ...(product.attributes || {}) })
    setFieldErrors({}); setShowForm(true)
  }

  function change(event) {
    const { name, value, type, checked } = event.target
    setForm((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }))
  }

  async function changeCategory(event) {
    const newCategoryId = event.target.value
    const newSchema = newCategoryId
      ? await api.get(`/categories/${newCategoryId}/attributes/`).then(({ data }) => (Array.isArray(data) ? data : [])).catch(() => [])
      : []
    // Warn before dropping values that do not exist in the new category's schema.
    const newCodes = new Set(newSchema.map((s) => s.code))
    const dropping = Object.keys(attributeValues).filter((code) => !newCodes.has(code) && attributeValues[code] !== '' && attributeValues[code] != null)
    const preserved = {}
    Object.entries(attributeValues).forEach(([code, value]) => {
      if (newCodes.has(code)) preserved[code] = value
    })
    if (dropping.length > 0 && !window.confirm(`Changing the category will discard: ${dropping.join(', ')}. Continue?`)) {
      setForm((current) => ({ ...current })) // no-op; keep old selection
      return
    }
    setForm((current) => ({ ...current, catalogue_category: newCategoryId }))
    setSchema(newSchema)
    setAttributeValues(preserved)
  }

  function changeAttribute(code, value) {
    setAttributeValues((current) => ({ ...current, [code]: value }))
  }

  function mapFieldErrors(errors) {
    const mapped = {}
    Object.entries(errors || {}).forEach(([key, messages]) => {
      if (key === 'attributes' && Array.isArray(messages)) {
        // Attribute errors map back onto their inputs where recognisable.
        messages.forEach((message) => {
          const match = schema.find((s) => message.includes(s.name) || message.includes(s.code))
          if (match) mapped[match.code] = message
          else mapped.attributes = (mapped.attributes || []).concat(message)
        })
      } else {
        mapped[key] = Array.isArray(messages) ? messages.join(', ') : String(messages)
      }
    })
    return mapped
  }

  async function save(event) {
    event.preventDefault(); setSaving(true); setError(''); setFieldErrors({})
    const localErrors = {}
    schema.forEach((s) => {
      const problem = attributeErrorText(s, attributeValues[s.code])
      if (problem) localErrors[s.code] = problem
    })
    if (Object.keys(localErrors).length) { setFieldErrors(localErrors); setSaving(false); return }

    const payload = {
      name: form.name, sku: form.sku || null, brand: form.brand,
      catalogue_category: form.catalogue_category || null,
      mrp: form.mrp === '' ? null : Number(form.mrp),
      default_price: form.default_price === '' ? '0' : Number(form.default_price),
      base_unit: form.base_unit,
      hsn_sac: form.hsn_sac, is_tax_applicable: form.is_tax_applicable,
      low_stock_threshold: Number(form.low_stock_threshold || 0),
      tax: form.tax === '' ? null : Number(form.tax),
      attributes: attributeValues,
    }
    if (isAdmin) payload.cost_price = form.cost_price === '' ? '0' : Number(form.cost_price)

    try {
      if (editing) await api.patch(`/products/${editing}/`, payload)
      else await api.post('/products/', payload)
      setShowForm(false); await loadProducts(page)
    } catch (err) {
      if (err?.response?.status === 400) setFieldErrors(mapFieldErrors(err.response.data))
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

  const selectedCategory = categories.find((c) => String(c.id) === String(form.catalogue_category))

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

    {showForm && isAdmin && <form className="record-form" onSubmit={save}>
      <div className="form-heading"><div><p className="eyebrow">{editing ? 'Edit record' : 'New record'}</p><h2>{editing ? 'Update product' : 'Add product'}</h2></div><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Close</button></div>

      {fieldErrors.attributes && <div className="status-message error">{Array.isArray(fieldErrors.attributes) ? fieldErrors.attributes.join(', ') : fieldErrors.attributes}</div>}

      <p className="eyebrow">Basic details</p>
      <div className="form-grid">
        <label>Product name<input name="name" value={form.name} onChange={change} required aria-required="true" /></label>
        <label>SKU (internal)<input name="sku" value={form.sku} onChange={change} placeholder="Leave blank for none" /></label>
        <label>Category<select name="catalogue_category" value={form.catalogue_category} onChange={changeCategory} aria-label="Product category"><option value="">None</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_active ? '' : ' (inactive)'}</option>)}</select></label>
        <label>Brand<input name="brand" value={form.brand} onChange={change} /></label>
      </div>

      {selectedCategory && schema.length > 0 && <>
        <p className="eyebrow">{selectedCategory.name} attributes</p>
        <div className="form-grid">
          {schema.map((s) => {
            const value = attributeValues[s.code] ?? ''
            const problem = fieldErrors[s.code] || attributeErrorText(s, value)
            return <label key={s.code} className={problem ? 'input-warning' : ''}>
              {s.name}{s.is_required ? ' *' : ''}{s.unit ? ` (${s.unit})` : ''}
              {s.data_type === 'CHOICE'
                ? <select value={value} onChange={(e) => changeAttribute(s.code, e.target.value)} required={s.is_required} aria-required={s.is_required ? 'true' : undefined}>
                    <option value="">Select {s.name}...</option>
                    {s.choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
                  </select>
                : s.data_type === 'BOOLEAN'
                  ? <select value={value} onChange={(e) => changeAttribute(s.code, e.target.value === '' ? '' : e.target.value === 'true')} aria-label={s.name}>
                      <option value="">Not set</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  : <input
                      type={attributeInputType(s)}
                      step={attributeStep(s)}
                      min={s.data_type === 'INTEGER' ? undefined : undefined}
                      value={value}
                      onChange={(e) => changeAttribute(s.code, e.target.value)}
                      placeholder={attributePlaceholder(s)}
                      required={s.is_required}
                      aria-required={s.is_required ? 'true' : undefined}
                      aria-label={s.name}
                    />}
              {s.description && <small className="field-help">{s.description}</small>}
              {problem && <small className="field-error" role="alert">{problem}</small>}
            </label>
          })}
        </div>
      </>}

      <p className="eyebrow">Commercial</p>
      <div className="form-grid">
        <label>MRP (printed)<input name="mrp" type="number" min="0" step="0.01" value={form.mrp} onChange={change} aria-describedby="mrp-help" /><small id="mrp-help" className="field-help">Manufacturer's printed maximum retail price.</small></label>
        <label>Cost price<input name="cost_price" type="number" min="0" step="0.01" value={form.cost_price} onChange={change} aria-describedby="cost-help" /><small id="cost-help" className="field-help">Purchase cost used for margin reporting; enter actual cost, not MRP.</small></label>
        <label>Default selling price<input name="default_price" type="number" min="0" step="0.01" value={form.default_price} onChange={change} required aria-describedby="price-help" /><small id="price-help" className="field-help">Pre-fill rate for invoices.</small></label>
      </div>

      <p className="eyebrow">Unit and tax</p>
      <div className="form-grid">
        <label>Base unit<select name="base_unit" value={form.base_unit} onChange={change}><option value="piece">Piece</option><option value="box">Box</option><option value="carton">Carton</option></select></label>
        <label>Tax<select name="tax" value={form.tax} onChange={change} aria-label="GST tax rate"><option value="">None configured</option>{taxRates.map((rate) => <option key={rate.id} value={rate.id}>{rate.name} ({Number(rate.rate).toFixed(0)}%)</option>)}</select></label>
        <label>HSN/SAC<input name="hsn_sac" value={form.hsn_sac} onChange={change} /></label>
        <label className="checkbox-label"><input type="checkbox" name="is_tax_applicable" checked={form.is_tax_applicable} onChange={change} /> Tax applicable</label>
        <label>Low-stock threshold<input name="low_stock_threshold" type="number" min="0" step="0.001" value={form.low_stock_threshold} onChange={change} /></label>
      </div>

      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Cancel</button>
        <button className="primary-button" disabled={saving}>{saving ? 'Saving...' : (editing ? 'Update product' : 'Save product')}</button>
      </div>
    </form>}
  </section>
}
