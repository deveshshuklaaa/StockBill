import { useCallback, useEffect, useState } from 'react'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

const DATA_TYPES = ['TEXT', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'CHOICE', 'DATE']

const emptyCategory = { code: '', name: '', description: '' }
const emptyAttribute = { code: '', name: '', data_type: 'TEXT', unit: '', decimal_places: '', description: '' }

export default function CataloguePage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [categories, setCategories] = useState([])
  const [attributes, setAttributes] = useState([])
  const [assignments, setAssignments] = useState([])
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [categoryForm, setCategoryForm] = useState(emptyCategory)
  const [editingCategory, setEditingCategory] = useState(null)
  const [attributeForm, setAttributeForm] = useState(emptyAttribute)
  const [editingAttribute, setEditingAttribute] = useState(null)
  const [choiceForm, setChoiceForm] = useState({ attributeId: null, value: '', label: '' })
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const [cats, attrs] = await Promise.all([
        api.get('/categories/'),
        api.get('/attributes/'),
      ])
      setCategories(Array.isArray(cats.data) ? cats.data : cats.data?.results || [])
      setAttributes(Array.isArray(attrs.data) ? attrs.data : attrs.data?.results || [])
      if (selectedCategory) {
        const list = await api.get(`/categories/${selectedCategory}/attribute-assignments/`)
        setAssignments(Array.isArray(list.data) ? list.data : list.data?.results || [])
      }
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setBusy(false) }
  }, [selectedCategory])

  useEffect(() => { load() }, [load])

  async function selectCategory(categoryId) {
    setSelectedCategory(categoryId)
    try {
      const list = await api.get(`/categories/${categoryId}/attribute-assignments/`)
      setAssignments(Array.isArray(list.data) ? list.data : list.data?.results || [])
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  function beginCategoryCreate() { setEditingCategory(null); setCategoryForm(emptyCategory) }
  function beginCategoryEdit(category) {
    setEditingCategory(category.id)
    setCategoryForm({ code: category.code || '', name: category.name || '', description: category.description || '' })
  }

  async function saveCategory(event) {
    event.preventDefault(); setSaving(true); setError('')
    try {
      if (editingCategory) await api.patch(`/categories/${editingCategory}/`, categoryForm)
      else await api.post('/categories/', categoryForm)
      setCategoryForm(emptyCategory); setEditingCategory(null); await load()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }

  async function toggleCategoryActive(category) {
    try {
      await api.patch(`/categories/${category.id}/`, { is_active: !category.is_active })
      await load()
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  function beginAttributeCreate() { setEditingAttribute(null); setAttributeForm(emptyAttribute) }
  function beginAttributeEdit(attribute) {
    setEditingAttribute(attribute.id)
    setAttributeForm({
      code: attribute.code || '', name: attribute.name || '', data_type: attribute.data_type || 'TEXT',
      unit: attribute.unit || '', decimal_places: attribute.decimal_places ?? '',
      description: attribute.description || '',
    })
  }

  async function saveAttribute(event) {
    event.preventDefault(); setSaving(true); setError('')
    const payload = { ...attributeForm }
    if (payload.data_type === 'DECIMAL' && payload.decimal_places === '') payload.decimal_places = 3
    if (payload.data_type !== 'DECIMAL') payload.decimal_places = null
    try {
      if (editingAttribute) await api.patch(`/attributes/${editingAttribute}/`, payload)
      else await api.post('/attributes/', payload)
      setAttributeForm(emptyAttribute); setEditingAttribute(null); await load()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }

  async function addChoice(event) {
    event.preventDefault(); setSaving(true); setError('')
    try {
      await api.post('/attribute-choices/', {
        attribute_definition: choiceForm.attributeId,
        value: choiceForm.value.trim(),
        label: choiceForm.label.trim() || choiceForm.value.trim(),
      })
      setChoiceForm({ attributeId: choiceForm.attributeId, value: '', label: '' })
      await load()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }

  async function assignAttribute(attributeDefinitionId) {
    if (!selectedCategory) return
    try {
      await api.post(`/categories/${selectedCategory}/attribute-assignments/`, {
        attribute_definition: attributeDefinitionId,
        display_order: assignments.length + 1,
      })
      await selectCategory(selectedCategory)
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  async function updateAssignment(assignmentId, patch) {
    try {
      await api.patch(`/categories/${selectedCategory}/attribute-assignments/${assignmentId}/`, patch)
      await selectCategory(selectedCategory)
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  async function removeAssignment(assignmentId) {
    if (!window.confirm('Remove this attribute from the category?')) return
    try {
      await api.delete(`/categories/${selectedCategory}/attribute-assignments/${assignmentId}/`)
      await selectCategory(selectedCategory)
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Catalogue / structure</p><h1>Catalogue management</h1>
      <p className="page-subtitle">Categories, attribute definitions, and per-category assignments that drive product forms.</p></div>
    </header>
    <StatusMessage>{error}</StatusMessage>
    {busy ? <div className="empty-state">Loading catalogue...</div> : <div className="catalogue-layout">
      <div className="table-frame">
        <div className="table-meta"><span>Categories</span><span className="table-note">{categories.length} total</span></div>
        {isAdmin && <form className="record-form" onSubmit={saveCategory}>
          <div className="form-grid">
            <label>Code<input name="code" value={categoryForm.code} onChange={(e) => setCategoryForm({ ...categoryForm, code: e.target.value })} pattern="[a-z0-9-]+" required disabled={Boolean(editingCategory)} /></label>
            <label>Name<input name="name" value={categoryForm.name} onChange={(e) => setCategoryForm({ ...categoryForm, name: e.target.value })} required /></label>
            <label className="full-width">Description<input name="description" value={categoryForm.description} onChange={(e) => setCategoryForm({ ...categoryForm, description: e.target.value })} /></label>
          </div>
          <div className="form-actions">
            <button type="button" className="quiet-button" onClick={beginCategoryCreate}>Clear</button>
            <button className="primary-button" disabled={saving}>{editingCategory ? 'Update category' : 'Add category'}</button>
          </div>
        </form>}
        <div className="table-scroll"><table><thead><tr><th>Code</th><th>Name</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{categories.map((category) => <tr key={category.id} className={selectedCategory === category.id ? 'selected' : ''}>
            <td><code>{category.code}</code></td><td>{category.name}</td>
            <td>{category.is_active ? 'Active' : 'Inactive'}</td>
            <td><div className="row-actions">
              <button className="text-button" onClick={() => selectCategory(category.id)}>Select</button>
              {isAdmin && <button className="text-button" onClick={() => beginCategoryEdit(category)}>Edit</button>}
              {isAdmin && <button className="text-button" onClick={() => toggleCategoryActive(category)}>{category.is_active ? 'Deactivate' : 'Activate'}</button>}
            </div></td>
          </tr>)}</tbody></table></div>
      </div>

      <div className="table-frame">
        <div className="table-meta"><span>Attribute definitions</span><span className="table-note">{attributes.length} total · shared across categories</span></div>
        {isAdmin && <form className="record-form" onSubmit={saveAttribute}>
          <div className="form-grid">
            <label>Code<input value={attributeForm.code} onChange={(e) => setAttributeForm({ ...attributeForm, code: e.target.value })} pattern="[a-z0-9_]+" required disabled={Boolean(editingAttribute)} /></label>
            <label>Name<input value={attributeForm.name} onChange={(e) => setAttributeForm({ ...attributeForm, name: e.target.value })} required /></label>
            <label>Data type<select value={attributeForm.data_type} onChange={(e) => setAttributeForm({ ...attributeForm, data_type: e.target.value })} disabled={Boolean(editingAttribute)}>{DATA_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
            <label>Unit<input value={attributeForm.unit} onChange={(e) => setAttributeForm({ ...attributeForm, unit: e.target.value })} placeholder="kg, ml, mm" /></label>
            {attributeForm.data_type === 'DECIMAL' && <label>Decimal places<input type="number" min="0" max="6" value={attributeForm.decimal_places} onChange={(e) => setAttributeForm({ ...attributeForm, decimal_places: e.target.value })} required /></label>}
            <label className="full-width">Description<input value={attributeForm.description} onChange={(e) => setAttributeForm({ ...attributeForm, description: e.target.value })} /></label>
          </div>
          <div className="form-actions">
            <button type="button" className="quiet-button" onClick={beginAttributeCreate}>Clear</button>
            <button className="primary-button" disabled={saving}>{editingAttribute ? 'Update attribute' : 'Add attribute'}</button>
          </div>
        </form>}
        <div className="table-scroll"><table><thead><tr><th>Attribute</th><th>Type</th><th>Unit</th><th>Choices</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{attributes.map((attribute) => <tr key={attribute.id}>
            <td><strong>{attribute.name}</strong><small><code>{attribute.code}</code></small></td>
            <td>{attribute.data_type}{attribute.data_type === 'DECIMAL' && attribute.decimal_places != null ? ` (${attribute.decimal_places}dp)` : ''}</td>
            <td>{attribute.unit || '-'}</td>
            <td>{attribute.choices?.length ? attribute.choices.map((choice) => choice.value).join(', ') : '-'}</td>
            <td>{attribute.is_active ? 'Active' : 'Inactive'}</td>
            <td><div className="row-actions">
              {isAdmin && <button className="text-button" onClick={() => beginAttributeEdit(attribute)}>Edit</button>}
              {isAdmin && attribute.data_type === 'CHOICE' && <button className="text-button" onClick={() => setChoiceForm({ attributeId: attribute.id, value: '', label: '' })}>Choices</button>}
            </div></td>
          </tr>)}</tbody></table></div>
        {isAdmin && choiceForm.attributeId != null && <form className="record-form" onSubmit={addChoice}>
          <div className="form-heading"><div><p className="eyebrow">Choice values</p><h2>Add choice for {attributes.find((a) => a.id === choiceForm.attributeId)?.name}</h2></div></div>
          <div className="form-grid">
            <label>Value<input value={choiceForm.value} onChange={(e) => setChoiceForm({ ...choiceForm, value: e.target.value })} required /></label>
            <label>Label<input value={choiceForm.label} onChange={(e) => setChoiceForm({ ...choiceForm, label: e.target.value })} placeholder="Display label (defaults to value)" /></label>
          </div>
          <div className="form-actions">
            <button type="button" className="quiet-button" onClick={() => setChoiceForm({ attributeId: null, value: '', label: '' })}>Close</button>
            <button className="primary-button" disabled={saving}>Add choice</button>
          </div>
        </form>}
      </div>

      <div className="table-frame">
        <div className="table-meta"><span>Category assignments</span><span className="table-note">{selectedCategory ? `For ${categories.find((c) => c.id === selectedCategory)?.name || 'selected category'}` : 'Select a category first'}</span></div>
        {selectedCategory ? <div className="table-scroll"><table><thead><tr><th>Order</th><th>Attribute</th><th>Type</th><th>Required</th><th>Filterable</th><th>Invoice-visible</th>{isAdmin && <th>Actions</th>}</tr></thead>
          <tbody>{assignments.map((assignment) => <tr key={assignment.id}>
            <td><input type="number" min="1" value={assignment.display_order} onChange={(e) => updateAssignment(assignment.id, { display_order: Number(e.target.value) })} disabled={!isAdmin} aria-label={`Display order for ${assignment.attribute_name}`} /></td>
            <td><strong>{assignment.attribute_name}</strong><small><code>{assignment.attribute_code}</code></small></td>
            <td>{assignment.data_type}{assignment.unit ? ` (${assignment.unit})` : ''}</td>
            <td><input type="checkbox" checked={assignment.is_required} onChange={(e) => updateAssignment(assignment.id, { is_required: e.target.checked })} disabled={!isAdmin} aria-label={`Required for ${assignment.attribute_name}`} /></td>
            <td><input type="checkbox" checked={assignment.is_filterable} onChange={(e) => updateAssignment(assignment.id, { is_filterable: e.target.checked })} disabled={!isAdmin} aria-label={`Filterable for ${assignment.attribute_name}`} /></td>
            <td><input type="checkbox" checked={assignment.is_invoice_visible} onChange={(e) => updateAssignment(assignment.id, { is_invoice_visible: e.target.checked })} disabled={!isAdmin} aria-label={`Invoice visible for ${assignment.attribute_name}`} /></td>
            {isAdmin && <td><div className="row-actions"><button className="text-button danger" onClick={() => removeAssignment(assignment.id)}>Remove</button></div></td>}
          </tr>)}</tbody></table></div>
          : <div className="empty-state">Select a category to manage its attribute assignments.</div>}
        {selectedCategory && isAdmin && <form className="record-form" onSubmit={(e) => { e.preventDefault(); const id = Number(e.target.elements.attribute_definition.value); if (id) assignAttribute(id) }}>
          <div className="form-grid">
            <label>Assign attribute<select name="attribute_definition" required>{attributes.filter((attribute) => !assignments.some((a) => a.attribute_definition === attribute.id)).map((attribute) => <option key={attribute.id} value={attribute.id}>{attribute.name} ({attribute.data_type})</option>)}</select></label>
          </div>
          <div className="form-actions"><button className="primary-button" disabled={saving}>Assign to category</button></div>
        </form>}
      </div>
    </div>}
  </section>
}
