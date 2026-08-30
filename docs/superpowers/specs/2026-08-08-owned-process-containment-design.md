# Owned Process Containment Design

## Problem

Ember's existing process-supervision gate terminates only the immediate `subprocess.Popen` child. Descendants can outlive the controller, which allowed two Bun workers to spin for roughly 25 hours after local verification ended.

## Design

Add `src/ember/governance/scripts/owned_process.py` as the sole local automation boundary for commands that can create descendants. Its platform-neutral `OwnedProcessRunner` returns a closed result containing the root PID, exit code, stdout, stderr, status, timeout, backend, and cleanup outcome.

On Windows the runner creates a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, assigns the root process immediately, and fails closed if assignment fails. Closing the controller or timing out closes the Job Object and terminates the complete tree. On POSIX the same API launches a new session and terminates its process group on completion or timeout; automatic cleanup after a controller crash remains a separately visible portability-hardening obligation.

The existing process-supervision gate delegates to this implementation. Root `AGENTS.md` requires automated Bun, Node, Cargo, Python test, watcher, server, and build commands to use the owned runner with a finite timeout.

## Tests

The regression launches a Python parent that starts a long-lived grandchild and writes the grandchild PID. It first demonstrates that the existing immediate-child timeout leaves that grandchild alive. After the fix it proves timeout kills the complete tree. Additional checks cover normal exit/output and containment metadata.

## Portability boundary

The API and status schema are platform-neutral. Windows Job Objects are the immediate incident cure. Linux/macOS process-group behavior is implemented for ordinary completion/timeout, but crash-survival parity must remain visible in issue metadata and future hygiene until it has its own host-specific test.

`NO_NEW_PARALLEL_AUTHORITY`
