/** The sidebar yields focus to the existing modal/loading layers. */
export function attachSidebarFocus(sidebar: HTMLElement, trigger: HTMLElement, close: () => void): () => void {
  const doc = sidebar.ownerDocument;
  const blocked = () => Boolean(doc.querySelector('[aria-modal="true"]:not(#admin-sidebar-navigation), .admin-loading-overlay'));
  const items = () => Array.from(sidebar.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'));
  const focusFirst = () => (items()[0] ?? sidebar).focus();
  const keydown = (event: KeyboardEvent) => {
    if (blocked() || event.defaultPrevented) return;
    if (event.key === "Escape") { event.preventDefault(); close(); }
    if (event.key === "Tab") {
      const elements = items();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) { event.preventDefault(); sidebar.focus(); return; }
      if (event.shiftKey && doc.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && doc.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  };
  const focusin = () => { if (!blocked() && !sidebar.contains(doc.activeElement)) focusFirst(); };
  // Keep the sidebar mounted beneath a higher layer so that layer can restore
  // focus to its still-visible launcher when it closes.
  const observer = new MutationObserver(focusin);
  observer.observe(doc.body, { childList: true, subtree: true });
  doc.addEventListener("keydown", keydown);
  doc.addEventListener("focusin", focusin);
  if (!blocked()) focusFirst();
  return () => {
    observer.disconnect();
    doc.removeEventListener("keydown", keydown);
    doc.removeEventListener("focusin", focusin);
    if (!blocked() && trigger.isConnected) trigger.focus();
  };
}
