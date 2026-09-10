import { useEffect, useState } from 'react'
import api from '../api/client'

// Shared metadata-driven product form used by both create (ProductsPage)
// and edit (EditProductPage). Owns core fields, dynamic attribute rendering,
// client-side attribute validation, and backend error mapping — one
// implementation so attribute handling stays identical everywhere.

export const emptyProductForm = {
  name: '', sku: '', brand: '', catalogue_category: '',
  mrp: '', cost_price: '', default_price: '',
  base_unit: 'piece', tax: '', hsn_sac: '', is_tax_applicable: true,
  low_stock_threshold: '0',
}

export function productFormFromProduct(product, isAdmin) {
  return {
    name: product.name || '', sku: product.sku || '', brand: product.brand || '',
    catalogue_category: product.catalogue_category || '',
    mrp: product.mrp ?? '', cost_price: isAdmin ? (product.cost_price ?? '') : '',
    default_price: product.default_price ?? '',
    base_unit: product.base_unit || 'piece', tax: product.tax ?? '',
    hsn_sac: product.hsn_sac || '', is_tax_applicable: product.is_tax_applicable !== false,
    low_stock_threshold: product.low_stock_threshold ?? '0',
  }
}

export function attributePlaceholder(schema) {
  if (schema.data_type === 'INTEGER') return 'Whole number'
  if (schema.data_type === 'DECIMAL') return `Number${schema.unit ? ` (${schema.unit})` : ''}`
  if (schema.data_type === 'DATE') return 'YYYY-MM-DD'
  return 'Text'
}

export function attributeInputType(schema) {
  if (schema.data_type === 'INTEGER') return 'number'
  if (schema.data_type === 'DECIMAL') return 'number'
  if (schema.data_type === 'DATE') return 'date'
  return 'text'
}

export function attributeStep(schema) {
  if (schema.data_type === 'INTEGER') return '1'
  if (schema.data_type === 'DECIMAL') return 'any'
  return undefined
}

export function attributeErrorText(schema, value) {
  if (schema.is_required && (value === '' || value == null)) return `${schema.name} is required.`
  if (value === '' || value == null) return ''
  if (schema.data_type === 'INTEGER' && !/^-?\d+$/.test(String(value).trim())) return 'Enter a whole number.'
  if (schema.data_type === 'DECIMAL' && Number.isNaN(Number(value))) return 'Enter a valid number.'
  if (schema.data_type === 'DATE' && Number.isNaN(Date.parse(value))) return 'Enter a valid date.'
  return ''
}

export function mapFieldErrors(errors, schema) {
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

// Fetch the attribute schema for a category (empty list when none selected).
export async function loadCategorySchema(categoryId) {
  if (!categoryId) return []
  try {
    const { data } = await api.get(`/categories/${categoryId}/attributes/`)
    return Array.isArray(data) ? data : []
  } catch {
    return []
  }
}

export async function loadCategoryOptions() {
  try {
    const { data } = await api.get('/categories/')
    const rows = Array.isArray(data) ? data : data?.results || []
    return { categories: rows, taxRates: await loadTaxRates() }
  } catch {
    return { categories: [], taxRates: [] }
  }
}

async function loadTaxRates() {
  try {
    const { data } = await api.get('/tax-rates/')
    return Array.isArray(data) ? data : data?.results || []
  } catch {
    return []
  }
}

export function buildProductPayload({ form, attributeValues, isAdmin, isEdit }) {
  const payload = {
    name: form.name,
    sku: form.sku || null,
    brand: form.brand,
    catalogue_category: form.catalogue_category || null,
    mrp: form.mrp === '' ? null : Number(form.mrp),
    default_price: form.default_price === '' ? '0' : Number(form.default_price),
    base_unit: form.base_unit,
    hsn_sac: form.hsn_sac,
    is_tax_applicable: form.is_tax_applicable,
    low_stock_threshold: Number(form.low_stock_threshold || 0),
    tax: form.tax === '' ? null : Number(form.tax),
    attributes: attributeValues,
  }
  // Cost price is admin-only data; never submit it for staff or when the
  // admin has no opinion on a create (backend keeps existing value on edit).
  if (isAdmin && form.cost_price !== '') payload.cost_price = Number(form.cost_price)
  if (isAdmin && isEdit && form.cost_price === '') payload.cost_price = 0
  return payload
}

export default function ProductForm({
  mode = 'create',
  form,
  setForm,
  attributeValues,
  setAttributeValues,
  categories,
  taxRates,
  schema,
  fieldErrors,
  onCancel,
  onSubmit,
  submitting,
  submitLabel,
}) {
  const [categoryChoice, setCategoryChoice] = useState(null)

  useEffect(() => {
    const match = categories.find((c) => String(c.id) === String(form.catalogue_category))
    setCategoryChoice(match || null)
  }, [form.catalogue_category, categories])

  function change(event) {
    const { name, value, type, checked } = event.target
    setForm((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }))
  }

  function changeAttribute(code, value) {
    setAttributeValues((current) => ({ ...current, [code]: value }))
  }

  async function changeCategory(event) {
    const newCategoryId = event.target.value
    const newSchema = await loadCategorySchema(newCategoryId)
    // Warn before dropping values that do not exist in the new category's schema.
    const newCodes = new Set(newSchema.map((s) => s.code))
    const dropping = Object.keys(attributeValues).filter(
      (code) => !newCodes.has(code) && attributeValues[code] !== '' && attributeValues[code] != null,
    )
    const preserved = {}
    Object.entries(attributeValues).forEach(([code, value]) => {
      if (newCodes.has(code)) preserved[code] = value
    })
    if (dropping.length > 0 && !window.confirm(`Changing the category will discard: ${dropping.join(', ')}. Continue?`)) {
      return // keep old selection
    }
    setForm((current) => ({ ...current, catalogue_category: newCategoryId }))
    setAttributeValues(preserved)
  }

  return <form className="record-form" onSubmit={onSubmit}>
    <div className="form-heading">
      <div>
        <p className="eyebrow">{mode === 'edit' ? 'Edit record' : 'New record'}</p>
        <h2>{mode === 'edit' ? 'Update product' : 'Add product'}</h2>
      </div>
      <button type="button" className="quiet-button" onClick={onCancel}>Close</button>
    </div>

    {fieldErrors.attributes && <div className="status-message error">{Array.isArray(fieldErrors.attributes) ? fieldErrors.attributes.join(', ') : fieldErrors.attributes}</div>}

    <p className="eyebrow">Basic details</p>
    <div className="form-grid">
      <label>Product name<input name="name" value={form.name} onChange={change} required aria-required="true" /></label>
      <label>SKU (internal)<input name="sku" value={form.sku} onChange={change} placeholder="Leave blank for none" /></label>
      <label>Category<select name="catalogue_category" value={form.catalogue_category} onChange={changeCategory} aria-label="Product category"><option value="">None</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_active ? '' : ' (inactive)'}</option>)}</select></label>
      <label>Brand<input name="brand" value={form.brand} onChange={change} /></label>
    </div>

    {categoryChoice && schema.length > 0 && <>
      <p className="eyebrow">{categoryChoice.name} attributes</p>
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
      <button type="button" className="quiet-button" onClick={onCancel}>Cancel</button>
      <button className="primary-button" disabled={submitting}>{submitting ? 'Saving...' : submitLabel}</button>
    </div>
  </form>
}
