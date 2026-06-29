// event-system — terminal event class hierarchy and focus management.
// Provides a lightweight DOM-like event model for terminal UI components.

// ---------------------------------------------------------------------------
// Base terminal event
// ---------------------------------------------------------------------------

export class TerminalEvent {
  defaultPrevented   = false;
  propagationStopped = false;
  immediateStopped   = false;

  stopPropagation(): void {
    this.propagationStopped = true;
  }
  preventDefault(): void {
    this.defaultPrevented = true;
  }
  stopImmediatePropagation(): void {
    this.propagationStopped = true;
    this.immediateStopped   = true;
  }
}

// ---------------------------------------------------------------------------
// Concrete event classes
// ---------------------------------------------------------------------------

export interface MouseModifiers {
  ctrl:  boolean;
  shift: boolean;
  alt:   boolean;
  meta:  boolean;
}

export class ClickEvent extends TerminalEvent {
  readonly type        = "click" as const;
  readonly bubbles     = true;
  readonly cancelable  = true;
  col:        number;
  row:        number;
  localCol:   number;
  localRow:   number;
  cellIsBlank: boolean;
  button:     number;
  modifiers:  MouseModifiers;
  clickCount: number;

  constructor(
    col:        number,
    row:        number,
    localCol:   number,
    localRow:   number,
    cellIsBlank: boolean,
    button:     number,
    modifiers:  MouseModifiers,
    clickCount: number,
  ) {
    super();
    this.col        = col;
    this.row        = row;
    this.localCol   = localCol;
    this.localRow   = localRow;
    this.cellIsBlank = cellIsBlank;
    this.button     = button;
    this.modifiers  = modifiers;
    this.clickCount = clickCount;
  }
}

export class FocusEvent extends TerminalEvent {
  readonly bubbles    = true;
  readonly cancelable = false;
  type: "focus" | "blur";

  constructor(type: "focus" | "blur") {
    super();
    this.type = type;
  }
}

export class InputEvent extends TerminalEvent {
  readonly type       = "input" as const;
  readonly bubbles    = true;
  readonly cancelable = false;
  data: string;

  constructor(data: string) {
    super();
    this.data = data;
  }
}

export class TerminalFocusEvent extends TerminalEvent {
  readonly bubbles    = false;
  readonly cancelable = false;
  type: "focus" | "blur";

  constructor(type: "focus" | "blur") {
    super();
    this.type = type;
  }
}

// ---------------------------------------------------------------------------
// DOM prop names that carry event handlers
// ---------------------------------------------------------------------------

export const EVENT_HANDLER_PROPS = new Set<string>([
  "onClick",
  "onFocus",
  "onBlur",
  "onKeyDown",
  "onInput",
  "onPaste",
  "onResize",
  "onTerminalFocus",
  "onTerminalBlur",
]);

// ---------------------------------------------------------------------------
// Focus manager
// ---------------------------------------------------------------------------

export type FocusNode = object;

export interface EventDispatcher {
  dispatch(event: TerminalEvent, target: FocusNode): void;
}

export class FocusManager {
  private _nodes:      FocusNode[] = [];
  private _focused:    FocusNode | null = null;
  private _dispatcher: EventDispatcher | undefined;

  setDispatcher(d: EventDispatcher): void {
    this._dispatcher = d;
  }

  register(node: FocusNode, options?: { autoFocus?: boolean }): void {
    if (!this._nodes.includes(node)) this._nodes.push(node);
    if (options?.autoFocus && this._focused === null) this.focus(node);
  }

  unregister(node: FocusNode): void {
    const idx = this._nodes.indexOf(node);
    if (idx >= 0) this._nodes.splice(idx, 1);
    if (this._focused === node) this._focused = null;
  }

  focus(node: FocusNode): void {
    if (this._focused === node) return;
    if (this._focused && this._dispatcher) {
      this._dispatcher.dispatch(new FocusEvent("blur"), this._focused);
    }
    this._focused = node;
    if (this._dispatcher) {
      this._dispatcher.dispatch(new FocusEvent("focus"), node);
    }
  }

  blur(node: FocusNode): void {
    if (this._focused === node) {
      this._focused = null;
      if (this._dispatcher) {
        this._dispatcher.dispatch(new FocusEvent("blur"), node);
      }
    }
  }

  focusNext(): void {
    if (this._nodes.length === 0) return;
    if (this._focused === null) {
      this.focus(this._nodes[0]!);
      return;
    }
    const idx  = this._nodes.indexOf(this._focused);
    const next = this._nodes[(idx + 1) % this._nodes.length]!;
    this.focus(next);
  }

  focusPrev(): void {
    if (this._nodes.length === 0) return;
    if (this._focused === null) {
      this.focus(this._nodes[this._nodes.length - 1]!);
      return;
    }
    const idx  = this._nodes.indexOf(this._focused);
    const prev = this._nodes[(idx - 1 + this._nodes.length) % this._nodes.length]!;
    this.focus(prev);
  }

  getFocused(): FocusNode | null   { return this._focused; }
  isFocused(node: FocusNode): boolean { return this._focused === node; }
  getRegistered(): FocusNode[]     { return [...this._nodes]; }
}
