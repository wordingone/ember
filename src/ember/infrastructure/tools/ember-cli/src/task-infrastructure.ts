// task-infrastructure.ts — killable task primitive shared across agent task types.

export interface KillableTask {
  kill(): void;
  isKilled(): boolean;
}

export function stopTask(task: KillableTask): void {
  task.kill();
}

export function createKillableTask(): KillableTask {
  let killed = false;
  return {
    kill() { killed = true; },
    isKilled() { return killed; },
  };
}
