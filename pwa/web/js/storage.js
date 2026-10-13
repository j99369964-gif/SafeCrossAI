// localStorage can throw (private browsing, blocked cookies). Preferences are a convenience, never a requirement.
export function getItem(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
export function setItem(key, value) {
  try { window.localStorage.setItem(key, value); return true; } catch { return false; }
}
