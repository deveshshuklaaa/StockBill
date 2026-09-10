import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import ProductForm, {
  attributeErrorText,
  buildProductPayload,
  loadCategorySchema,
  loadCategoryOptions,
  mapFieldErrors,
  productFormFromProduct,
} from '../components/ProductForm'
import { useAuth } from '../context/AuthContext'

export default function EditProductPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [product, setProduct] = useState(null)
  const [form, setForm] = useState(null)
  const [attributeValues, setAttributeValues] = useState({})
  const [categories, setCategories] = useState([])
  const [taxRates, setTaxRates] = useState([])
  const [schema, setSchema] = useState([])
  const [fieldErrors, setFieldErrors] = useState({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [{ data: fetched }, options] = await Promise.all([
          api.get(`/products/${id}/`),
          loadCategoryOptions(),
        ])
        if (cancelled) return
        setProduct(fetched)
        setForm(productFormFromProduct(fetched, isAdmin))
        setAttributeValues({ ...(fetched.attributes || {}) })
        setCategories(options.categories)
        setTaxRates(options.taxRates)
        setSchema(await loadCategorySchema(fetched.catalogue_category))
      } catch (err) {
        if (!cancelled) setError(apiErrorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [id, isAdmin])

  async function save(event) {
    event.preventDefault()
    setSaving(true); setError(''); setFieldErrors({})
    const localErrors = {}
    schema.forEach((s) => {
      const problem = attributeErrorText(s, attributeValues[s.code])
      if (problem) localErrors[s.code] = problem
    })
    if (Object.keys(localErrors).length) { setFieldErrors(localErrors); setSaving(false); return }

    const payload = buildProductPayload({ form, attributeValues, isAdmin, isEdit: true })
    try {
      await api.patch(`/products/${id}/`, payload)
      navigate('/products')
    } catch (err) {
      if (err?.response?.status === 400) setFieldErrors(mapFieldErrors(err.response.data, schema))
      else setError(apiErrorMessage(err))
    } finally { setSaving(false) }
  }

  if (!isAdmin) return <section className="page-section">
    <header className="page-header"><div><p className="eyebrow">Inventory / catalogue</p><h1>Edit product</h1></div></header>
    <StatusMessage>You do not have permission to edit products.</StatusMessage>
    <Link className="quiet-button" to="/products">Back to products</Link>
  </section>

  if (loading) return <section className="page-section"><div className="empty-state">Loading product...</div></section>
  if (error && !form) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/products">Back to products</Link></section>
  if (!form) return null

  return <section className="page-section">
    <header className="page-header">
      <div>
        <p className="eyebrow">Inventory / catalogue</p>
        <h1>Edit product</h1>
        <p className="page-subtitle">{product?.name} · ID {product?.id}{product.sku ? ` · ${product.sku}` : ''}</p>
      </div>
      <Link className="quiet-button" to="/products">Back to products</Link>
    </header>
    <StatusMessage>{error}</StatusMessage>
    <ProductForm
      mode="edit"
      form={form}
      setForm={setForm}
      attributeValues={attributeValues}
      setAttributeValues={setAttributeValues}
      categories={categories}
      taxRates={taxRates}
      schema={schema}
      fieldErrors={fieldErrors}
      onCancel={() => navigate('/products')}
      onSubmit={save}
      submitting={saving}
      submitLabel="Save changes"
    />
  </section>
}
