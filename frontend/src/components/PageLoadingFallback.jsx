export default function PageLoadingFallback() {
  return (
    <div className="page-loading-skeleton" role="status" aria-live="polite" aria-label="Loading page">
      <div className="skeleton-bar skeleton-title" />
      <div className="skeleton-bar skeleton-subtitle" />
      <div className="skeleton-bar skeleton-table" />
    </div>
  )
}

