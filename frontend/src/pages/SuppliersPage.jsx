import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { fetchSuppliers, createSupplier, updateSupplier } from '../api/suppliers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

const emptySupplier = {
  name: '', contact_info: '', gstin: '',
  address: '', state: '', state_code: '',
}

export default function SuppliersPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [suppliers, setSuppliers] = useState([])
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [hasPrevious, setHasPrevious] = useState(false)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const latestLoad = useRef(0)

  const [form, setForm] = useState(emptySupplier)
  const [editing, setEditing] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const requestId = ++latestLoad.current
    setBusy(true); setError('')
    fetchSuppliers({ page, search, isActive: activeFilter })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setSuppliers(rows(data))
        setTotal(Number(data.count ?? 0))
        setHasNext(Boolean(data.next))
        setHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestLoad.current) return
        if (err?.response?.status === 404 && page > 1) { setPage(1); return }
        setError(apiErrorMessage(err))
      })
      .finally(() => { if (requestId === latestLoad.current) setBusy(false) })
  }, [page, search, activeFilter])

  async function reload() {
    try {
      const data = await fetchSuppliers({ page, search, isActive: activeFilter })
      setSuppliers(rows(data))
      setTotal(Number(data.count ?? 0))
      setHasNext(Boolean(data.next))
      setHasPrevious(Boolean(data.previous))
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  function beginCreate() { setEditing(null); setForm(emptySupplier); setShowForm(true) }
  function beginEdit(supplier) {
    setEditing(supplier.id)
    setForm({
      name: supplier.name || '',
      contact_info: supplier.contact_info || '',
      gstin: supplier.gstin || '',
      address: supplier.address || '',
      state: supplier.state || '',
      state_code: supplier.state_code || '',
    })
    setShowForm(true)
  }

  function change(event) {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
  }

  async function save(event) {
    event.preventDefault(); setSaving(true); setError('')
    try {
      if (editing) await updateSupplier(editing, form)
      else await createSupplier(form)
      setShowForm(false); await reload()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))
  const filtersActive = search || activeFilter

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Purchasing / master data</p><h1>Suppliers</h1><p className="page-subtitle">Vendor master data feeding the purchase workflow. Supplier settlement happens outside StockBill.</p></div>
      {isAdmin && <button className="primary-button" onClick={beginCreate}>Add supplier</button>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showForm && isAdmin && <form className="record-form" onSubmit={save}>
      <div className="form-heading"><div><p className="eyebrow">{editing ? 'Edit record' : 'New record'}</p><h2>{editing ? 'Update supplier' : 'Add supplier'}</h2></div><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Close</button></div>

      <div className="form-grid">
        <label>Supplier name<input name="name" value={form.name} onChange={change} required aria-required="true" /></label>
        <label>Phone / contact<input name="contact_info" value={form.contact_info} onChange={change} /></label>
        <label>GSTIN<input name="gstin" value={form.gstin} onChange={change} placeholder="15-character GSTIN (optional)" /></label>
        <label>State<input name="state" value={form.state} onChange={change} /></label>
        <label>State code<input name="state_code" value={form.state_code} onChange={change} placeholder="e.g. 27" /></label>
        <label className="full-width">Address<textarea name="address" value={form.address} onChange={change} rows={2} /></label>
      </div>

      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Cancel</button>
        <button className="primary-button" disabled={saving}>{saving ? 'Saving...' : (editing ? 'Update supplier' : 'Save supplier')}</button>
      </div>
    </form>}

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading suppliers...' : `${total} supplier${total === 1 ? '' : 's'}`}</span>
        <div className="filter-row">
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Name, GSTIN, phone" aria-label="Search suppliers" /></label>
          <label className="filter-field">Status<select value={activeFilter} onChange={(e) => { setActiveFilter(e.target.value); setPage(1) }} aria-label="Filter by status"><option value="">All</option><option value="true">Active</option><option value="false">Archived</option></select></label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading suppliers...</div> : suppliers.length === 0 ? <div className="empty-state">{filtersActive ? 'No suppliers match your filters.' : 'No suppliers yet.'}</div> : <div className="table-scroll"><table>
        <thead><tr><th>Supplier</th><th>Phone</th><th>GSTIN</th><th>State</th><th>Address</th><th>Status</th><th aria-label="Actions" /></tr></thead>
        <tbody>{suppliers.map((supplier) => <tr key={supplier.id} className={supplier.is_active ? '' : 'archived-row'}>
          <td><strong><Link className="text-button" to={`/suppliers/${supplier.id}`}>{supplier.name}</Link></strong></td>
          <td>{supplier.contact_info || '-'}</td>
          <td>{supplier.gstin || '-'}</td>
          <td>{supplier.state || supplier.state_code || '-'}</td>
          <td className="address-cell">{supplier.address || '-'}</td>
          <td>{supplier.is_active ? 'Active' : 'Archived'}</td>
          <td><div className="row-actions">
            <Link className="text-button" to={`/suppliers/${supplier.id}`}>View</Link>
            {isAdmin && <button className="text-button" onClick={() => beginEdit(supplier)}>Edit</button>}
          </div></td>
        </tr>)}</tbody>
      </table></div>}
      <div className="table-meta pager" role="navigation" aria-label="Supplier pagination">
        <button className="pager-button" onClick={() => setPage((c) => Math.max(1, c - 1))} disabled={!hasPrevious || busy}>← Previous</button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} suppliers` : ''}</span>
        <button className="pager-button" onClick={() => setPage((c) => c + 1)} disabled={!hasNext || busy}>Next →</button>
      </div>
    </div>
  </section>
}
