export default function StatusMessage({ type = 'error', children }) {
  if (!children) return null
  return <div className={`status-message ${type}`} role={type === 'error' ? 'alert' : 'status'}>{children}</div>
}
