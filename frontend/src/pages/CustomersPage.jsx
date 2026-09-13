import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import { fetchCustomers } from '../api/customers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }
function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const emptyCustomer = {
  name: '', contact_info: '', customer_type: 'B2C',
  gst_registration_type: 'unregistered', gstin: '',
  billing_address: '', shipping_address: '',
  state: '', state_code: '', pincode: '',
  credit_limit: '0', credit_days: '0', is_regular: false,
}

export default function CustomersPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [customers, setCustomers] = useState([])
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

  const [form, setForm] = useState(emptyCustomer)
  const [sameAsBilling, setSameAsBilling] = useState(true)
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
    fetchCustomers({ page, search, isActive: activeFilter })
      .then((data) => {
        if (requestId !== latestLoad.current) return
        setCustomers(rows(data))
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
      const data = await fetchCustomers({ page, search, isActive: activeFilter })
      setCustomers(rows(data))
      setTotal(Number(data.count ?? 0))
      setHasNext(Boolean(data.next))
      setHasPrevious(Boolean(data.previous))
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  function beginCreate() { setEditing(null); setForm(emptyCustomer); setSameAsBilling(true); setShowForm(true) }
  function beginEdit(customer) {
    setEditing(customer.id)
    setForm({
      name: customer.name || '', contact_info: customer.contact_info || '',
      customer_type: customer.customer_type || 'B2C',
      gst_registration_type: customer.gst_registration_type || 'unregistered',
      gstin: customer.gstin || '',
      billing_address: customer.billing_address || '', shipping_address: customer.shipping_address || '',
      state: customer.state || '', state_code: customer.state_code || '', pincode: customer.pincode || '',
      credit_limit: customer.credit_limit ?? '0', credit_days: customer.credit_days ?? '0',
      is_regular: Boolean(customer.is_regular),
    })
    setSameAsBilling(customer.shipping_address === customer.billing_address)
    setShowForm(true)
  }

  function change(event) {
    const { name, value, type, checked } = event.target
    setForm((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }))
  }

  function changeBillingAddress(event) {
    const value = event.target.value
    setForm((current) => ({
      ...current,
      billing_address: value,
      shipping_address: sameAsBilling ? value : current.shipping_address,
    }))
  }

  async function save(event) {
    event.preventDefault(); setSaving(true); setError('')
    const payload = {
      ...form,
      credit_limit: Number(form.credit_limit || 0),
      credit_days: Number(form.credit_days || 0),
      shipping_address: sameAsBilling ? form.billing_address : form.shipping_address,
    }
    try {
      if (editing) await api.patch(`/customers/${editing}/`, payload)
      else await api.post('/customers/', payload)
      setShowForm(false); await reload()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }

  async function archive(customer) {
    if (!window.confirm(`Archive ${customer.name}? Their history is preserved.`)) return
    try { await api.delete(`/customers/${customer.id}/`); await reload() }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  async function reactivate(customer) {
    try { await api.patch(`/customers/${customer.id}/`, { is_active: true }); await reload() }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  const totalPages = Math.max(1, Math.ceil(total / 25))
  const filtersActive = search || activeFilter

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Relationships / ledger</p><h1>Customers</h1><p className="page-subtitle">Accounts, tax identity, credit terms, and authoritative outstanding balances.</p></div>
      {isAdmin && <button className="primary-button" onClick={beginCreate}>Add customer</button>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showForm && isAdmin && <form className="record-form" onSubmit={save}>
      <div className="form-heading"><div><p className="eyebrow">{editing ? 'Edit record' : 'New record'}</p><h2>{editing ? 'Update customer' : 'Add customer'}</h2></div><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Close</button></div>

      <p className="eyebrow">Basic</p>
      <div className="form-grid">
        <label>Customer name<input name="name" value={form.name} onChange={change} required aria-required="true" /></label>
        <label>Phone<input name="contact_info" value={form.contact_info} onChange={change} /></label>
        <label>Customer type<select name="customer_type" value={form.customer_type} onChange={change}><option value="B2C">B2C</option><option value="B2B">B2B</option></select></label>
        <label className="checkbox-label"><input type="checkbox" name="is_regular" checked={form.is_regular} onChange={change} /> Regular customer account</label>
      </div>

      <p className="eyebrow">GST</p>
      <div className="form-grid">
        <label>GST registration<select name="gst_registration_type" value={form.gst_registration_type} onChange={change}><option value="unregistered">Unregistered</option><option value="registered">Registered</option></select></label>
        <label>GSTIN<input name="gstin" value={form.gstin} onChange={change} placeholder="15-character GSTIN" /></label>
        <label>State<input name="state" value={form.state} onChange={change} /></label>
        <label>State code<input name="state_code" value={form.state_code} onChange={change} placeholder="e.g. 29" /></label>
      </div>

      <p className="eyebrow">Billing address</p>
      <div className="form-grid">
        <label className="full-width">Address<textarea name="billing_address" value={form.billing_address} onChange={changeBillingAddress} rows={2} /></label>
        <label>Pincode<input name="pincode" value={form.pincode} onChange={change} /></label>
      </div>

      <p className="eyebrow">Shipping address</p>
      <div className="form-grid">
        <label className="checkbox-label full-width"><input type="checkbox" checked={sameAsBilling} onChange={(e) => {
          const nowSame = e.target.checked
          setSameAsBilling(nowSame)
          if (nowSame) setForm((current) => ({ ...current, shipping_address: current.billing_address }))
        }} /> Shipping address same as billing</label>
        {!sameAsBilling && <label className="full-width">Shipping address<textarea name="shipping_address" value={form.shipping_address} onChange={change} rows={2} /></label>}
      </div>

      <p className="eyebrow">Credit</p>
      <div className="form-grid">
        <label>Credit limit<input name="credit_limit" type="number" min="0" step="0.01" value={form.credit_limit} onChange={change} /></label>
        <label>Credit days<input name="credit_days" type="number" min="0" step="1" value={form.credit_days} onChange={change} /></label>
      </div>

      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Cancel</button>
        <button className="primary-button" disabled={saving}>{saving ? 'Saving...' : (editing ? 'Update customer' : 'Save customer')}</button>
      </div>
    </form>}

    <div className="table-frame">
      <div className="table-meta">
        <span>{busy ? 'Loading customers...' : `${total} customer${total === 1 ? '' : 's'}`}</span>
        <div className="filter-row">
          <label className="filter-field">Search<input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Name, phone, GSTIN" aria-label="Search customers" /></label>
          <label className="filter-field">Status<select value={activeFilter} onChange={(e) => { setActiveFilter(e.target.value); setPage(1) }} aria-label="Filter by status"><option value="">All</option><option value="true">Active</option><option value="false">Archived</option></select></label>
        </div>
      </div>
      {busy ? <div className="empty-state">Loading customers...</div> : customers.length === 0 ? <div className="empty-state">{filtersActive ? 'No customers match your filters.' : 'No customers yet.'}</div> : <div className="table-scroll"><table>
        <thead><tr><th>Customer</th><th>Phone</th><th>GSTIN</th><th>State</th><th>Credit limit</th><th>Outstanding</th><th>Status</th><th aria-label="Actions" /></tr></thead>
        <tbody>{customers.map((customer) => <tr key={customer.id} className={customer.is_active ? '' : 'archived-row'}>
          <td><strong><Link className="text-button" to={`/customers/${customer.id}`}>{customer.name}</Link></strong><small>{customer.customer_type}{customer.is_regular ? ' · regular' : ''}</small></td>
          <td>{customer.contact_info || '-'}</td>
          <td>{customer.gstin || '-'}</td>
          <td>{customer.state || customer.state_code || '-'}</td>
          <td className="stock-value">{Number(customer.credit_limit) > 0 ? money(customer.credit_limit) : '—'}</td>
          <td><strong className={Number(customer.outstanding_balance) > 0 ? 'balance due' : 'stock-value'}>{money(customer.outstanding_balance)}</strong></td>
          <td>{customer.is_active ? 'Active' : 'Archived'}</td>
          <td><div className="row-actions">
            <Link className="text-button" to={`/customers/${customer.id}`}>View</Link>
            {isAdmin && <button className="text-button" onClick={() => beginEdit(customer)}>Edit</button>}
            {isAdmin && (customer.is_active
              ? <button className="text-button danger" onClick={() => archive(customer)}>Archive</button>
              : <button className="text-button" onClick={() => reactivate(customer)}>Reactivate</button>)}
          </div></td>
        </tr>)}</tbody>
      </table></div>}
      <div className="table-meta pager" role="navigation" aria-label="Customer pagination">
        <button className="pager-button" onClick={() => setPage((c) => Math.max(1, c - 1))} disabled={!hasPrevious || busy}>← Previous</button>
        <span>Page {page} of {totalPages}{total > 0 ? ` · ${total} customers` : ''}</span>
        <button className="pager-button" onClick={() => setPage((c) => c + 1)} disabled={!hasNext || busy}>Next →</button>
      </div>
    </div>
  </section>
}
