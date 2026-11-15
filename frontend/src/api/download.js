// Save a blob API response as a file. Uses the server's filename from
// Content-Disposition when the browser can read it, else `fallbackName`.
export function filenameFromDisposition(disposition) {
  const match = /filename="?([^";]+)"?/i.exec(disposition || '')
  return match ? match[1] : ''
}

function istStamp(date = new Date()) {
  const ist = new Date(date.getTime() + (5.5 * 60 + date.getTimezoneOffset()) * 60000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${ist.getFullYear()}${pad(ist.getMonth() + 1)}${pad(ist.getDate())}-${pad(ist.getHours())}${pad(ist.getMinutes())}`
}

export const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export function defaultExportName(name) {
  return `stockbill-${name}-${istStamp()}.xlsx`
}

export function saveBlobResponse(response, fallbackName, type) {
  const blob = response.data instanceof Blob ? response.data : new Blob([response.data], { type })
  const filename = filenameFromDisposition(response.headers?.['content-disposition']) || fallbackName
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
  return filename
}
