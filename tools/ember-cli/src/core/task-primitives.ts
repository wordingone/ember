// core/task-primitives.ts
// Cancellable async task wrapper with state tracking, timeout enforcement, and
// duration measurement.
// L1 leaf: no intra-ember dependencies.

// ---- State ----

/** Lifecycle state of a task. */
export type TaskState = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

/**
 * Minimum shape shared by all task representations stored in AppState.
 * Concrete task types extend this base.
 */
export interface TaskStateBase {
  taskId: string;
  status: TaskState;
  startedAt?: number;  // epoch ms
  completedAt?: number; // epoch ms
  error?: Error;
}

// ---- Result and options ----

/** Value returned when a task finishes (any terminal state). */
export interface TaskResult<T> {
  state: TaskState;
  output?: T;
  error?: Error;
  duration: number; // ms
}

/** Per-task configuration. */
export interface TaskOptions {
  timeout?: number;   // ms
  priority?: number;
  retryCount?: number;
}

// ---- Task interface ----

/** Handle for an async unit of work that can be cancelled and queried for state. */
export interface Task<T> {
  run(): Promise<TaskResult<T>>;
  cancel(): void;
  getState(): TaskState;
}

// ---- Factory ----

/**
 * Wraps an async function with state tracking and cancellation support.
 * The returned Task starts in 'pending' state; call run() to begin execution.
 */
export function createTask<T>(
  fn: () => Promise<T>,
  _options?: TaskOptions,
): Task<T> {
  // Use getter/setter so TypeScript cannot narrow the return value across async
  // await boundaries — cancel() may mutate _state while fn() is awaited.
  let _state: TaskState = 'pending';
  const getState = (): TaskState => _state;
  const setState = (s: TaskState): void => { _state = s; };

  return {
    run: async (): Promise<TaskResult<T>> => {
      if (getState() !== 'pending') {
        return { state: getState(), duration: 0 };
      }
      setState('running');
      const startMs = Date.now();
      try {
        const output = await fn();
        // Respect a cancel() that raced with completion.
        if (getState() === 'cancelled') {
          return { state: 'cancelled', duration: Date.now() - startMs };
        }
        setState('completed');
        return { state: 'completed', output, duration: Date.now() - startMs };
      } catch (err: unknown) {
        if (getState() === 'cancelled') {
          return { state: 'cancelled', duration: Date.now() - startMs };
        }
        setState('failed');
        const error = err instanceof Error ? err : new Error(String(err));
        return { state: 'failed', error, duration: Date.now() - startMs };
      }
    },

    cancel: (): void => {
      if (getState() === 'pending' || getState() === 'running') {
        setState('cancelled');
      }
    },

    getState: (): TaskState => getState(),
  };
}

// ---- Timeout helper ----

/**
 * Races a task against a timeout.
 * If the timeout fires first, the task is cancelled and a 'cancelled' result
 * is returned. Otherwise the task's own result is returned.
 */
export function taskWithTimeout<T>(
  task: Task<T>,
  ms: number,
): Promise<TaskResult<T>> {
  return new Promise<TaskResult<T>>((resolve) => {
    const timer = setTimeout(() => {
      task.cancel();
      resolve({ state: 'cancelled', duration: ms });
    }, ms);

    task.run().then(
      (result) => {
        clearTimeout(timer);
        resolve(result);
      },
      (err: unknown) => {
        clearTimeout(timer);
        const error = err instanceof Error ? err : new Error(String(err));
        resolve({ state: 'failed', error, duration: ms });
      },
    );
  });
}
