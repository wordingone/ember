// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Simple in-memory cache with TTL expiry

export class Cache<V> {
  private ttl: number
  private map: Map<string, { value: V; ts: number }>
  private writes: number

  constructor(ttlMs: number) {
    this.ttl = ttlMs
    this.map = new Map()
    this.writes = 0
  }

  get(key: string): V | undefined {
    const entry = this.map.get(key)
    if (!entry) return undefined
    if (Date.now() - entry.ts > this.ttl) {
      this.map.delete(key)
      return undefined
    }
    return entry.value
  }

  set(key: string, value: V): void {
    this.map.set(key, { value, ts: Date.now() })
    if (++this.writes % 100 === 0) this._prune()
  }

  clear(): void {
    this.map.clear()
  }

  private _prune(): void {
    const now = Date.now()
    for (const [k, v] of this.map) {
      if (now - v.ts > this.ttl) this.map.delete(k)
    }
  }
}
