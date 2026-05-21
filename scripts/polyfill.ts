/**
 * localStorage polyfill for Node.js subprocess execution.
 *
 * The @cofhe/sdk uses zustand persist middleware which defaults to
 * localStorage. In Node.js environments where a broken localStorage
 * polyfill exists (e.g. from node-localstorage without a valid path),
 * zustand gets a storage object without setItem, causing
 * "storage.setItem is not a function".
 *
 * This module installs a working in-memory localStorage before any
 * SDK code loads.
 */

if (typeof globalThis !== "undefined" && (!globalThis.localStorage || typeof globalThis.localStorage.setItem !== "function")) {
  const store = new Map<string, string>()
  Object.defineProperty(globalThis, "localStorage", {
    value: {
      getItem(key: string): string | null {
        return store.get(key) ?? null
      },
      setItem(key: string, value: string): void {
        store.set(key, String(value))
      },
      removeItem(key: string): void {
        store.delete(key)
      },
      clear(): void {
        store.clear()
      },
      get length(): number {
        return store.size
      },
      key(index: number): string | null {
        return Array.from(store.keys())[index] ?? null
      },
    },
    writable: false,
    configurable: false,
  })
}
