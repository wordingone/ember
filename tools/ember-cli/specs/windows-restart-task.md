<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Windows-native cockpit restart registration

Status: CURRENT

Issue: #562

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/windows-restart-task.ts`

`ember liveness install` registers the exact installed `ember.exe` with Windows
Task Scheduler as the cockpit's model-free restart-on-failure authority. The
registration is current-user, interactive-token, least-privilege, single-instance,
and bounded to one-minute failure restarts. The task action may launch only the
verified Ember cockpit executable; model-server launch remains exclusively owned
by `ember-lab`.

The executable must be an absolute path with the exact basename `ember.exe`.
Registration hashes those bytes before and after task creation, writes the task
definition as BOM-prefixed UTF-16LE XML, queries the installed task, verifies its
security, trigger, action, and restart policy, and only then emits a path-free
`ember-windows-restart-task/v1` receipt. A byte change, task drift, unexpected
principal, extra action, or registration/query failure is terminal and emits no
verified-install claim.

This node specifies registration and verification logic only. Issue #562 remains
open until a built installed Ember cockpit is killed and independently proven to
restart with one current window, no dead shell, and a next-boot receipt.
