// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import {
  createLiveMemoryFootprintService,
  type LiveMemoryFootprintServiceOptions,
} from "./memory-footprint-live.ts";
import type { BoundMemoryTripReceipt, MemoryFootprintService } from "./memory-footprint-service.ts";

export const MEMORY_FOOTPRINT_RESTART_EXIT_CODE = 75;

export interface CockpitMemoryFootprintSupervisorOptions
  extends Omit<LiveMemoryFootprintServiceOptions, "requestCorrectiveAction"> {
  currentPid?: number;
  exitCockpit?: (code: number) => void;
  requestEmberLabRestart?: (pid: number, receipt: BoundMemoryTripReceipt) => void;
  warn?: (message: string) => void;
}

export function createCockpitMemoryFootprintSupervisor(
  options: CockpitMemoryFootprintSupervisorOptions,
): MemoryFootprintService {
  const currentPid = options.currentPid ?? process.pid;
  const exitCockpit = options.exitCockpit ?? ((code: number) => process.exit(code));
  const warn = options.warn ?? console.warn;

  return createLiveMemoryFootprintService({
    ...options,
    cockpitPid: currentPid,
    requestCorrectiveAction: (receipt) => {
      if (receipt.process_class === "cockpit") {
        if (receipt.pid !== currentPid) {
          warn(
            `[memory-footprint] refusing to exit cockpit pid ${currentPid} for foreign ` +
              `trip pid ${receipt.pid}; receipt preserved for operator action`,
          );
          return;
        }
        warn(
          `[memory-footprint] cockpit pid ${receipt.pid} exceeded ${receipt.threshold} GiB; ` +
            `trip receipt is durable, exiting for Task Scheduler restart-on-failure`,
        );
        exitCockpit(MEMORY_FOOTPRINT_RESTART_EXIT_CODE);
        return;
      }

      if (options.requestEmberLabRestart) {
        warn(
          `[memory-footprint] brain-server pid ${receipt.pid} exceeded ${receipt.threshold} GiB; ` +
            `notifying Ember Lab restart authority`,
        );
        options.requestEmberLabRestart(receipt.pid, receipt);
      } else {
        warn(
          `[memory-footprint] brain-server pid ${receipt.pid} exceeded ${receipt.threshold} GiB; ` +
            `restart remains pending with the Ember Lab owner`,
        );
      }
    },
  });
}
