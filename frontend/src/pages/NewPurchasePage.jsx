import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api, { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import {
  fetchNextPurchaseNumber,
  fetchPurchase,
  fetchWarehouses,
  postPurchase,
  searchPurchaseProducts,
  updatePurchase,
} from '../api/purchases'
import { fetchActiveSuppliers, fetchSupplierPricing } from '../api/suppliers'
import StatusMessage from '../components/StatusMessage'
import { formatNetWeight, formatStockWithBoxes, masterBoxSize } from '../utils/format'
import { sortProductsByMrpForSameName } from '../utils/productSearch'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

function today() { return new Date().toISOString().slice(0, 10) }

// Variant identity line: weight + MRP distinguish same-name products.
function variantSummary(product) {
  const parts = []
  const weight = formatNetWeight(product?.attributes?.net_weight)
  if (weight) parts.push(weight)
  if (product.mrp != null) parts.push(`MRP: ₹${Number(product.mrp).toFixed(2)}`)
  if (product.sku) parts.push(`SKU: ${product.sku}`)
  if (product.category_name) parts.push(product.category_name)
  if (product.base_unit && product.base_unit !== 'piece') parts.push(product.base_unit)
  return parts.join(' · ')
}

function calculateLine(line, taxMode) {
  const quantity = Number(line.quantity) || 0
  const factor = Number(line.conversionFactor ?? line.conversion_factor) || 1
  const baseQty = quantity * factor
  const rate = Number(line.rate) || 0
  const discount = Number(line.discountAmount ?? line.discount_amount) || 0
  const taxRate = Number(line.taxRate ?? line.tax_rate) || 0

  const gross = baseQty * rate
  const net = Math.max(0, gross - discount)
  let taxable = net
  let tax = net * taxRate / 100
  if (taxMode === 'inclusive') {
    taxable = net / (1 + taxRate / 100)
    tax = net - taxable
  }
  const unitCost = baseQty > 0 ? taxable / baseQty : 0
  return { gross, discount, taxable, tax, total: taxable + tax, baseQty, unitCost, taxRate }
}

export default function NewPurchasePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const editDraftId = searchParams.get('edit')
  const isEditMode = Boolean(editDraftId)

  const productSearchInputRef = useRef(null)
  const rowRefs = useRef({})
  const pendingFocusRef = useRef(null)

  const [warehouses, setWarehouses] = useState([])
  const [supplier, setSupplier] = useState(null)
  const [supplierSearch, setSupplierSearch] = useState('')
  const [supplierResults, setSupplierResults] = useState([])
  const [supplierBusy, setSupplierBusy] = useState(false)
  const [supplierPricingMap, setSupplierPricingMap] = useState({})
  const [invoiceDate, setInvoiceDate] = useState(today())
  const [supplierInvoiceNo, setSupplierInvoiceNo] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [taxMode, setTaxMode] = useState('exclusive')
  const [notes, setNotes] = useState('')
  const [nextNumber, setNextNumber] = useState('')

  const [productSearch, setProductSearch] = useState('')
  const [productResults, setProductResults] = useState([])
  const [productBusy, setProductBusy] = useState(false)
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0)
  const [lines, setLines] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [posting, setPosting] = useState(false)

  useEffect(() => {
    fetchWarehouses({ is_active: 'true' })
      .then((warehouseRows) => {
        setWarehouses(warehouseRows)
        if (!isEditMode && warehouseRows.length === 1) setWarehouseId(String(warehouseRows[0].id))
      })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => {
        if (!isEditMode) setLoading(false)
      })
  }, [isEditMode])

  // Preload draft for edit mode
  useEffect(() => {
    if (!editDraftId) return
    let cancelled = false
    setLoading(true)
    fetchPurchase(editDraftId)
      .then(async (draft) => {
        if (cancelled) return
        if (draft.state !== 'DRAFT') {
          setError('Only draft purchases can be edited. This purchase is ' + draft.state.toLowerCase() + '.')
          setLoading(false)
          return
        }
        setInvoiceDate(draft.invoice_date || today())
        setSupplierInvoiceNo(draft.supplier_invoice_no || '')
        if (draft.warehouse) setWarehouseId(String(draft.warehouse))
        setTaxMode(draft.tax_mode || 'exclusive')
        setNotes(draft.notes || '')

        if (draft.supplier) {
          try {
            const { data: sup } = await api.get(`/suppliers/${draft.supplier}/`)
            if (!cancelled) setSupplier(sup)
          } catch {
            if (!cancelled) {
              setSupplier({
                id: draft.supplier,
                name: draft.supplier_name_snapshot || draft.supplier_name,
                gstin: draft.supplier_gstin_snapshot || '',
                state: draft.supplier_state_snapshot || '',
                state_code: draft.supplier_state_code_snapshot || '',
              })
            }
          }
        }

        const loadedLines = await Promise.all(
          (draft.line_items || []).map(async (line) => {
            try {
              const { data: product } = await api.get(`/products/${line.product}/`)
              return {
                key: line.id || `${line.product}-${Math.random()}`,
                product: line.product,
                productData: product,
                quantity: Number(line.quantity),
                purchaseUnit: line.purchase_unit_name || 'piece',
                conversionFactor: Number(line.conversion_factor || 1),
                rate: Number(line.rate),
                hasSupplierPrice: false,
                isManualRate: true,
                discountAmount: Number(line.discount_amount || 0) || '',
                taxRate: Number(line.tax_rate ?? product.tax_rate ?? 0),
              }
            } catch {
              return {
                key: line.id || `${line.product}-${Math.random()}`,
                product: line.product,
                productData: {
                  id: line.product,
                  name: line.product_name_snapshot || `Product #${line.product}`,
                  mrp: null,
                  sku: line.sku_snapshot || '',
                  base_unit: line.base_unit_snapshot || 'piece',
                  tax_rate: Number(line.tax_rate || 0),
                },
                quantity: Number(line.quantity),
                purchaseUnit: line.purchase_unit_name || 'piece',
                conversionFactor: Number(line.conversion_factor || 1),
                rate: Number(line.rate),
                hasSupplierPrice: false,
                isManualRate: true,
                discountAmount: Number(line.discount_amount || 0) || '',
                taxRate: Number(line.tax_rate || 0),
              }
            }
          })
        )
        if (!cancelled) {
          setLines(loadedLines)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(apiErrorMessage(err))
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [editDraftId])

  // Server-side supplier search, debounced; only active suppliers are
  // offered because the backend rejects inactive ones for new purchases.
  useEffect(() => {
    const query = supplierSearch.trim()
    if (!query || supplier?.id) { setSupplierResults([]); setSupplierBusy(false); return undefined }
    let cancelled = false
    setSupplierBusy(true)
    const timer = setTimeout(() => {
      fetchActiveSuppliers(query)
        .then((results) => { if (!cancelled) setSupplierResults(results.slice(0, 8)) })
        .catch(() => { if (!cancelled) setSupplierResults([]) })
        .finally(() => { if (!cancelled) setSupplierBusy(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer); setSupplierBusy(false) }
  }, [supplierSearch, supplier])

  // Fetch supplier-wise purchase rates whenever supplier changes.
  // Auto-fills configured rates for products that have not been manually overridden.
  useEffect(() => {
    if (!supplier?.id) {
      setSupplierPricingMap({})
      return undefined
    }
    let cancelled = false
    fetchSupplierPricing(supplier.id, { isActive: 'true' })
      .then((data) => {
        if (cancelled) return
        const map = {}
        ;(data?.pricing || []).forEach((p) => {
          if (p.is_active && p.mrp != null) {
            map[Number(p.mrp).toFixed(2)] = Number(p.rate_per_piece)
          }
        })
        setSupplierPricingMap(map)
        // Refresh rates for lines that haven't been manually overridden
        setLines((currentLines) =>
          currentLines.map((line) => {
            if (line.isManualRate) return line
            const lineMrp = line.productData?.mrp != null ? Number(line.productData.mrp).toFixed(2) : null
            if (lineMrp && map[lineMrp] !== undefined) {
              return {
                ...line,
                rate: map[lineMrp],
                hasSupplierPrice: true,
              }
            }
            return {
              ...line,
              rate: '',
              hasSupplierPrice: false,
            }
          })
        )
      })
      .catch(() => {
        if (!cancelled) setSupplierPricingMap({})
      })
    return () => {
      cancelled = true
    }
  }, [supplier])

  useEffect(() => {
    let cancelled = false
    fetchNextPurchaseNumber(invoiceDate)
      .then((number) => { if (!cancelled) setNextNumber(number) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [invoiceDate])

  useEffect(() => {
    const query = productSearch.trim()
    if (!query) {
      setProductResults([])
      setProductBusy(false)
      setActiveSuggestionIndex(0)
      return undefined
    }
    let cancelled = false
    setProductBusy(true)
    const timer = setTimeout(() => {
      searchPurchaseProducts(query)
        .then(({ data }) => {
          if (!cancelled) {
            const raw = data.results || []
            const sorted = sortProductsByMrpForSameName(raw)
            setProductResults(sorted.slice(0, 8))
            setActiveSuggestionIndex(0)
          }
        })
        .catch(() => { if (!cancelled) setProductResults([]) })
        .finally(() => { if (!cancelled) setProductBusy(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer); setProductBusy(false) }
  }, [productSearch])

  useEffect(() => {
    if (pendingFocusRef.current) {
      const { key, field } = pendingFocusRef.current
      const tryFocus = () => {
        const el = rowRefs.current[key]?.[field]
        if (el) {
          pendingFocusRef.current = null
          el.focus()
          if (typeof el.select === 'function') {
            el.select()
          }
          el.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
          return true
        }
        return false
      }
      if (!tryFocus()) {
        const frame = requestAnimationFrame(() => {
          tryFocus()
        })
        return () => cancelAnimationFrame(frame)
      }
    }
  }, [lines])

  const totals = useMemo(() => lines.reduce((result, line) => {
    const calculated = calculateLine(line, taxMode)
    result.subtotal += calculated.gross
    result.discount += calculated.discount
    result.taxable += calculated.taxable
    result.tax += calculated.tax
    result.total += calculated.total
    return result
  }, { subtotal: 0, discount: 0, taxable: 0, tax: 0, total: 0 }), [lines, taxMode])

  function handleNumericFocus(e) {
    e.target.select?.()
  }

  function handleSearchKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (productResults.length > 0) {
        setActiveSuggestionIndex((prev) => (prev + 1) % productResults.length)
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (productResults.length > 0) {
        setActiveSuggestionIndex((prev) => (prev - 1 + productResults.length) % productResults.length)
      }
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (productResults.length > 0 && productResults[activeSuggestionIndex]) {
        addProduct(productResults[activeSuggestionIndex])
      }
    } else if (e.key === 'Escape') {
      setProductSearch('')
      setProductResults([])
      setActiveSuggestionIndex(0)
    }
  }

  function addProduct(product) {
    const existing = lines.find((line) => line.product === product.id)
    let targetKey
    if (existing) {
      targetKey = existing.key
      updateLine(existing.key, 'quantity', Number(existing.quantity || 0) + 1)
    } else {
      targetKey = `${product.id}-${Date.now()}`
      const productMrp = product.mrp != null ? Number(product.mrp).toFixed(2) : null
      const supplierRate =
        supplier?.id && productMrp && supplierPricingMap[productMrp] !== undefined
          ? supplierPricingMap[productMrp]
          : null
      const hasSupplierPrice = supplierRate !== null

      setLines((current) => [...current, {
        key: targetKey,
        product: product.id,
        productData: product,
        quantity: 1,
        purchaseUnit: 'piece',
        conversionFactor: 1,
        rate: hasSupplierPrice ? supplierRate : '',
        hasSupplierPrice,
        isManualRate: false,
        discountAmount: '',
        taxRate: Number(product.tax_rate) || 0,
      }])
    }
    pendingFocusRef.current = { key: targetKey, field: 'unit' }
    setProductSearch('')
    setProductResults([])
    setActiveSuggestionIndex(0)
  }

  function updateLine(key, field, value) {
    setLines((current) => current.map((line) => {
      if (line.key !== key) return line
      const next = { ...line, [field]: value }
      if (field === 'rate') {
        next.isManualRate = true
      }
      if (field === 'purchaseUnit') {
        const box = masterBoxSize(line.productData)
        if (value === 'master box' && box) {
          next.conversionFactor = box
          next.quantity = 1
        } else {
          next.conversionFactor = 1
        }
      }
      return next
    }))
  }

  function removeLine(key) {
    delete rowRefs.current[key]
    setLines((current) => current.filter((line) => line.key !== key))
  }

  function chooseSupplier(value) {
    setSupplier(value)
    setSupplierSearch('')
  }

  function validate() {
    if (!supplier?.id) return 'Select a supplier before saving.'
    if (!warehouseId) return 'Select a receiving warehouse.'
    if (!lines.length) return 'Add at least one product line.'
    for (const line of lines) {
      if (!(Number(line.quantity) > 0)) return `Quantity for ${line.productData.name} must be positive.`
      if (!(Number(line.rate) >= 0) || line.rate === '') return `Enter the purchase rate for ${line.productData.name}.`
    }
    return ''
  }

  async function submit(post) {
    const problem = validate()
    if (problem) { setError(problem); return }
    if (post) { setPosting(true) } else { setSaving(true) }
    setError('')
    try {
      const lineItems = lines.map((line) => ({
        product: line.product,
        quantity: Number(line.quantity),
        purchase_unit_name: line.purchaseUnit,
        conversion_factor: Number(line.conversionFactor),
        rate: Number(line.rate),
        discount_amount: Number(line.discount_amount || line.discountAmount || 0),
      }))
      const payload = {
        supplier: supplier.id,
        warehouse: Number(warehouseId),
        supplier_invoice_no: supplierInvoiceNo.trim(),
        invoice_date: invoiceDate,
        tax_mode: taxMode,
        notes,
        line_items: lineItems,
      }

      if (isEditMode) {
        await updatePurchase(editDraftId, payload)
        if (post) {
          const posted = await postPurchase(editDraftId)
          navigate(`/purchases/${posted.id || editDraftId}`)
        } else {
          navigate(`/purchases/${editDraftId}`)
        }
      } else {
        const createPayload = { ...payload, post }
        const idempotencyKey = `purchase-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
        const { data } = await api.post('/purchase-invoices/', createPayload, {
          headers: { 'Idempotency-Key': idempotencyKey },
        })
        navigate(`/purchases/${data.id}`)
      }
    } catch (err) {
      setError(
        apiForbiddenMessage(
          err,
          post ? 'post purchases' : (isEditMode ? 'update purchase drafts' : 'save purchase drafts'),
          post ? 'posting purchase' : (isEditMode ? 'updating purchase draft' : 'saving purchase draft'),
        ),
      )
    } finally {
      setSaving(false); setPosting(false)
    }
  }

  if (loading) return <section className="page-section"><div className="empty-state">Loading purchase workspace...</div></section>

  return <section className="page-section invoice-page">
    <header className="page-header invoice-header">
      <div>
        <p className="eyebrow">Purchasing / goods inward</p>
        <h1>{isEditMode ? 'Edit draft purchase' : 'New purchase'}</h1>
        <p className="page-subtitle">
          {isEditMode
            ? <>Editing draft purchase <strong>#{editDraftId}</strong> · Next number on posting: <strong>{nextNumber || '—'}</strong></>
            : <>Next number on posting: <strong>{nextNumber || '—'}</strong></>}
        </p>
      </div>
      <Link className="quiet-button" to="/purchases">Back to purchases</Link>
    </header>
    <StatusMessage>{error}</StatusMessage>


    <div className="invoice-layout">
      <div className="invoice-workspace">
        <section className="invoice-card customer-card">
          <div className="section-kicker">01 / Supplier</div>
          <div className="customer-picker">
            <input value={supplier?.id ? supplier.name : supplierSearch} onChange={(event) => { setSupplierSearch(event.target.value); if (supplier?.id) setSupplier(null) }} placeholder="Search active suppliers by name, GSTIN, or phone..." aria-label="Search supplier" />
            {supplierSearch && !supplier?.id && <div className="suggestion-list">
              {supplierBusy && !supplierResults.length && <div className="suggestion-empty">Searching...</div>}
              {supplierResults.map((item) => <button type="button" key={item.id} onClick={() => chooseSupplier(item)}>
                <strong>{item.name}</strong>
                <span>{item.gstin || 'Unregistered'}{item.state ? ` · ${item.state}` : ''}{item.contact_info ? ` · ${item.contact_info}` : ''}</span>
              </button>)}
              {!supplierBusy && !supplierResults.length && <div className="suggestion-empty">No active supplier matches. Archived suppliers cannot receive purchases.</div>}
            </div>}
          </div>
          {supplier?.id && <div className="customer-context">
            <strong>{supplier.name}</strong>
            <span>{supplier.gstin || 'Unregistered'}</span>
            <b>{supplier.state ? `${supplier.state} (${supplier.state_code || '?'})` : 'State not set'}</b>
          </div>}
        </section>

        <section className="invoice-card">
          <div className="section-heading">
            <div><div className="section-kicker">02 / Document</div><h2>Bill details</h2></div>
          </div>
          <div className="form-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
            <label>Purchase date<input type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} required /></label>
            <label>Supplier bill no<input value={supplierInvoiceNo} onChange={(e) => setSupplierInvoiceNo(e.target.value)} placeholder="As printed on the bill" /></label>
            <label>Receiving warehouse<select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} required><option value="">Select warehouse</option>{warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
            <label className="purchase-inline-field"><span>Tax Mode</span><select value={taxMode} onChange={(e) => setTaxMode(e.target.value)}><option value="exclusive">Exclusive</option><option value="inclusive">Inclusive</option></select></label>
          </div>
          <label className="purchase-inline-field" style={{ marginTop: 14 }}><span>Notes</span><textarea className="form-input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional reference notes" /></label>
        </section>

        <section className="invoice-card lines-card">
          <div className="section-heading">
            <div><div className="section-kicker">03 / Items</div><h2>What is coming in?</h2></div>
            <span className="line-count">{lines.length} line{lines.length === 1 ? '' : 's'}</span>
          </div>

          {lines.length > 0 && (
            <div className="invoice-lines">
              {lines.map((line) => {
                const calculated = calculateLine(line, taxMode)
                const box = masterBoxSize(line.productData)
                const isMasterBox = line.purchaseUnit === 'master box'
                return (
                  <div className="invoice-line new-purchase-line" key={line.key}>
                    <div className="line-product">
                      <span className="line-field-title">Product</span>
                      <strong className="line-product-name">{line.productData.name}</strong>
                      <span className="variant-line">{variantSummary(line.productData) || line.productData.base_unit}</span>
                      <span className="line-conversion-badge">
                        {isMasterBox && box
                          ? `Conversion: ${line.quantity || 0} × ${box} = ${calculated.baseQty} Pieces`
                          : `${calculated.baseQty} ${line.productData.base_unit || 'Pieces'}`}
                        {' · '}Effective cost: {money(calculated.unitCost)} / pc
                      </span>
                    </div>
                    <label className="line-field line-field-unit">
                      <span className="line-field-title">Unit</span>
                      <select
                        ref={(el) => {
                          if (!rowRefs.current[line.key]) rowRefs.current[line.key] = {}
                          rowRefs.current[line.key].unit = el
                        }}
                        value={line.purchaseUnit}
                        onChange={(e) => updateLine(line.key, 'purchaseUnit', e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            const qtyEl = rowRefs.current[line.key]?.qty
                            if (qtyEl) {
                              qtyEl.focus()
                              qtyEl.select?.()
                              qtyEl.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
                            }
                          }
                        }}
                        aria-label={`Unit for ${line.productData.name}`}
                      >
                        <option value="piece">Pieces</option>
                        {box && <option value="master box">Master Box ({box} pcs)</option>}
                      </select>
                    </label>
                    <label className="line-field line-field-qty">
                      <span className="line-field-title">Qty</span>
                      <input
                        ref={(el) => {
                          if (!rowRefs.current[line.key]) rowRefs.current[line.key] = {}
                          rowRefs.current[line.key].qty = el
                        }}
                        type="number"
                        min="0.001"
                        step={isMasterBox ? '1' : '0.001'}
                        value={line.quantity}
                        onChange={(e) => updateLine(line.key, 'quantity', e.target.value)}
                        onFocus={handleNumericFocus}
                        onKeyDown={(e) => {
                          if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                            e.preventDefault()
                          } else if (e.key === 'Enter') {
                            e.preventDefault()
                            const rateEl = rowRefs.current[line.key]?.rate
                            if (rateEl) {
                              rateEl.focus()
                              rateEl.select?.()
                              rateEl.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
                            }
                          }
                        }}
                        placeholder={isMasterBox ? 'Boxes' : 'Pieces'}
                        className="no-spinner"
                        aria-label={`Quantity in ${isMasterBox ? 'master boxes' : 'pieces'} for ${line.productData.name}`}
                      />
                    </label>
                    <label className="line-field line-field-mrp">
                      <span className="line-field-title">MRP</span>
                      <input
                        type="text"
                        readOnly
                        tabIndex={-1}
                        value={line.productData?.mrp != null ? `₹${Number(line.productData.mrp).toFixed(2)}` : '—'}
                        className="line-mrp-input"
                        aria-label={`MRP for ${line.productData.name}`}
                      />
                    </label>
                    <label className="line-field line-field-rate">
                      <span className="line-field-title">Purchase Rate</span>
                      <input
                        ref={(el) => {
                          if (!rowRefs.current[line.key]) rowRefs.current[line.key] = {}
                          rowRefs.current[line.key].rate = el
                        }}
                        type="number"
                        min="0"
                        step="0.01"
                        value={line.rate}
                        onChange={(e) => updateLine(line.key, 'rate', e.target.value)}
                        onFocus={handleNumericFocus}
                        onKeyDown={(e) => {
                          if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                            e.preventDefault()
                          } else if (e.key === 'Enter') {
                            e.preventDefault()
                            const discEl = rowRefs.current[line.key]?.disc
                            if (discEl) {
                              discEl.focus()
                              discEl.select?.()
                              discEl.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
                            }
                          }
                        }}
                        placeholder="₹ / pc"
                        className="no-spinner line-rate-input"
                        aria-label={`Purchase rate per piece for ${line.productData.name}`}
                      />
                      {line.hasSupplierPrice && !line.isManualRate && (
                        <span
                          className="line-rate-hint rate-supplier supplier-rate-badge"
                          title={`Supplier rate${line.productData?.mrp != null ? ` (MRP ₹${Number(line.productData.mrp).toFixed(2)})` : ''}: ₹${Number(line.rate).toFixed(2)}/pc`}
                        >
                          Supplier rate{line.productData?.mrp != null ? ` (MRP ₹${Number(line.productData.mrp).toFixed(2)})` : ''}: ₹{Number(line.rate).toFixed(2)}/pc
                        </span>
                      )}
                      {line.isManualRate && line.hasSupplierPrice && (
                        <span className="line-rate-hint rate-manual manual-override-badge">
                          Manually overridden
                        </span>
                      )}
                    </label>
                    <label className="line-field line-field-disc">
                      <span className="line-field-title">Disc.</span>
                      <div className="disc-input-wrap">
                        <input
                          ref={(el) => {
                            if (!rowRefs.current[line.key]) rowRefs.current[line.key] = {}
                            rowRefs.current[line.key].disc = el
                          }}
                          type="number"
                          min="0"
                          step="0.01"
                          value={line.discountAmount}
                          onChange={(e) => updateLine(line.key, 'discountAmount', e.target.value)}
                          onFocus={handleNumericFocus}
                          onKeyDown={(e) => {
                            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                              e.preventDefault()
                            } else if (e.key === 'Enter') {
                              e.preventDefault()
                              if (productSearchInputRef.current) {
                                productSearchInputRef.current.focus()
                                productSearchInputRef.current.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
                              }
                            }
                          }}
                          placeholder="0.00"
                          className="no-spinner line-disc-input"
                          aria-label={`Discount amount for ${line.productData.name}`}
                        />
                        <span className="disc-symbol">%</span>
                      </div>
                    </label>
                    <div className="line-field line-field-tax">
                      <span className="line-field-title">GST</span>
                      <div className="line-val-display">{calculated.taxRate}%</div>
                    </div>
                    <div className="line-field line-field-taxable">
                      <span className="line-field-title">Taxable</span>
                      <div className="line-val-display line-val-taxable">
                        <span className="sr-only">{`Taxable: ${money(calculated.taxable)}`}</span>
                        <span aria-hidden="true">{money(calculated.taxable)}</span>
                      </div>
                    </div>
                    <div className="line-field line-field-total">
                      <span className="line-field-title">Total</span>
                      <div className="line-val-display line-val-total">
                        <strong>{money(calculated.total)}</strong>
                      </div>
                    </div>
                    <div className="line-field line-field-remove">
                      <span className="line-field-title">&nbsp;</span>
                      <button type="button" className="remove-line" onClick={() => removeLine(line.key)} aria-label="Remove line" title="Remove line">×</button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div className="product-search">
            <input
              ref={productSearchInputRef}
              value={productSearch}
              onChange={(event) => setProductSearch(event.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search products by name to add..."
              aria-label="Search products"
            />
            {productSearch && (
              <div className="suggestion-list product-suggestions">
                {productBusy && !productResults.length && <div className="suggestion-empty">Searching...</div>}
                {productResults.map((product, idx) => {
                  const box = masterBoxSize(product)
                  const summary = variantSummary(product)
                  const isSelected = idx === activeSuggestionIndex
                  return (
                    <button
                      type="button"
                      key={product.id}
                      className={isSelected ? 'active-suggestion' : ''}
                      onClick={() => addProduct(product)}
                      onMouseEnter={() => setActiveSuggestionIndex(idx)}
                    >
                      <strong>{product.name}</strong>
                      {summary && <span className="variant-line">{summary}</span>}
                      <span>{box ? `M.Box ${box} · ` : ''}{formatStockWithBoxes(product.current_stock, product)}</span>
                    </button>
                  )
                })}
                {!productBusy && !productResults.length && <div className="suggestion-empty">No matching product</div>}
              </div>
            )}
          </div>
        </section>
      </div>

      <aside className="invoice-summary">
        <div className="summary-label">Preview summary</div>
        <div className="summary-customer">{supplier?.name || 'No supplier selected'}<span>{taxMode === 'inclusive' ? 'Tax-inclusive bill' : 'Tax-exclusive bill'}</span></div>
        <div className="summary-rows">
          <div><span>Subtotal</span><strong>{money(totals.subtotal)}</strong></div>
          <div><span>Discount</span><strong>{money(totals.discount)}</strong></div>
          <div><span>Taxable</span><strong>{money(totals.taxable)}</strong></div>
          <div className="summary-tax"><span>GST</span><strong>{money(totals.tax)}</strong></div>
        </div>
        <div className="grand-total"><span>Bill total (est.)</span><strong>{money(totals.total)}</strong></div>
        <button type="button" className="quiet-button submit-invoice" onClick={() => submit(false)} disabled={saving || posting}>{saving ? (isEditMode ? 'Saving changes...' : 'Saving draft...') : (isEditMode ? 'Save changes' : 'Save draft')}</button>
        <button type="button" className="primary-button submit-invoice" onClick={() => submit(true)} disabled={saving || posting}>{posting ? 'Receiving stock...' : 'Post & receive stock'}</button>
        <p className="summary-note">Posting receives stock, updates the weighted-average cost, and writes the stock ledger. Drafts affect nothing until posted.</p>
      </aside>
    </div>
  </section>
}
