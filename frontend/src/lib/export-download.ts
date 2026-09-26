/**
 * Browser-safe Blob download for persisted export bytes (Phase-16).
 * The backend owns all artifact bytes; the frontend only persists the
 * returned Blob under the server-provided safe filename. Object URLs are
 * always revoked and the app never navigates away.
 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    // Keep the anchor out of layout; Firefox requires it in the DOM.
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
