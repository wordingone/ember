// services/highlight-cache.ts — Shared highlight-cache singleton.
// Extracted from markdown-and-code.ts so that syntax-highlight.ts can import it
// without creating a circular dependency with markdown-and-code.ts.

export const HIGHLIGHT_CACHE_MAX = 500;

// LRU cache — promotes on hit so that the most-recently-used entry survives eviction.
export class LRUCache<K, V> {
  private _maxSize: number;
  private _map = new Map<K, V>();

  constructor(_maxSize: number) {
    this._maxSize = _maxSize;
  }

  get(key: K): V | undefined {
    if (!this._map.has(key)) return undefined;
    const value = this._map.get(key) as V;
    this._map.delete(key);
    this._map.set(key, value);
    return value;
  }

  set(key: K, value: V): void {
    if (this._map.has(key)) this._map.delete(key);
    this._map.set(key, value);
    if (this._map.size > this._maxSize) {
      const oldest = this._map.keys().next().value;
      if (oldest !== undefined) this._map.delete(oldest);
    }
  }

  has(key: K): boolean { return this._map.has(key); }
  get size(): number   { return this._map.size; }
}

/** Process-level singleton — avoids re-highlighting the same code on every render. */
export const highlightCache = new LRUCache<string, string>(HIGHLIGHT_CACHE_MAX);

/** Stable cache key for a (language, code) pair. */
export function hashPair(language: string, code: string): string {
  return `${language}\0${code}`;
}
