import React from 'react'

export default function UnsavedChangesDialog({
  isOpen,
  title = 'Unsaved Changes',
  message = 'You have unsaved changes. What would you like to do before leaving?',
  isSaving = false,
  error = '',
  onSaveDraft,
  onLeaveWithoutSaving,
  onCancel,
}) {
  if (!isOpen) return null

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="unsaved-changes-dialog-title"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        className="modal-content"
        style={{
          backgroundColor: 'white',
          borderRadius: '8px',
          padding: '1.5rem',
          maxWidth: '480px',
          width: '90%',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
        }}
      >
        <h3 id="unsaved-changes-dialog-title" style={{ marginTop: 0, color: '#111827' }}>
          {title}
        </h3>
        <p style={{ color: '#4b5563', lineHeight: 1.5, margin: '0.75rem 0' }}>
          {message}
        </p>

        {error && (
          <div
            role="alert"
            style={{
              padding: '0.75rem',
              backgroundColor: '#fef2f2',
              color: '#991b1b',
              borderRadius: '6px',
              fontSize: '0.875rem',
              marginBottom: '1rem',
              border: '1px solid #fecaca',
            }}
          >
            {error}
          </div>
        )}

        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'flex-end',
            gap: '0.75rem',
            marginTop: '1.5rem',
          }}
        >
          <button
            type="button"
            className="quiet-button"
            onClick={onCancel}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="text-button danger"
            onClick={onLeaveWithoutSaving}
            disabled={isSaving}
            style={{ color: 'var(--red, #dc2626)' }}
          >
            Leave Without Saving
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={onSaveDraft}
            disabled={isSaving}
          >
            {isSaving ? 'Saving Draft...' : 'Save as Draft'}
          </button>
        </div>
      </div>
    </div>
  )
}
