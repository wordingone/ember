# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed host commit-capacity contract for ember mechanisms that pin
large host-resident state (for example ``FullStateAdamWCPUOffload``'s
CPU-offloaded optimizer moments in ``a1_optimizer.py``).

An ember mechanism that needs more host commit headroom than the reference
host currently provides must not be admitted by silent ad-hoc OS tuning
mid-run. This module gives each such mechanism a declared, testable
capacity requirement, checked by a fail-closed pre-execution probe. A host
that does not meet the requirement is refused with a precise statement of
the shortfall -- never a suggestion to tune the OS by hand while a run is
in flight.

Receipted defect this formalizes (#898, 2026-08-21 amendment): the E8 dense
A1 launch needed a manual, undocumented, unreceipted pagefile increase
(32 GiB -> 64 GiB) to proceed. The operator ruled that ember must either fit
the host envelope, provision prerequisites through a deliberate documented
automated auditable setup contract, redesign the workload, or fail closed
with a precise statement -- manual mid-run OS tuning is never an accepted
path.

Scoping ruling (operator, 2026-08-21, binds this module): the 2026-08-21
pagefile change is recorded here as a TEMPORARY operator intervention and
technical debt, acceptable only to finish the current dense control run --
never as a formalized, repeatable Ember setup requirement. A mechanism's
elevated commit need is a property of that mechanism's own declared
control-experiment profile (see ``HostMechanismProfile`` /
``dense_a1_full_state_cpu_offload_profile``), never a redefinition of
Ember's normal host floor. This module declares that per-mechanism
requirement and validates it with a fail-closed probe
(``validate_host_setup_contract``); it is not yet wired into any live
launch/dispatch path, so it does not yet satisfy the operator's requirement
that an elevated-commit need be "declared in the host envelope contract and
validated before execution" -- that wiring, scoped to the declaring
mechanism's own experiment declaration, is required follow-up before this
issue can claim that requirement met (see the #898 PR body boundary-honesty
note).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

BYTES_PER_GIB = 1024**3

# fp32 master_copy + exp_avg + exp_avg_sq: three 4-byte tensors per parameter,
# each touched in full on every optimizer.step() call (a1_optimizer.py
# FullStateAdamWCPUOffload.step). All three are commit-charged CPU tensors.
_FULL_STATE_ADAMW_CPU_OFFLOAD_BYTES_PER_PARAM = 12

# Declared transient working-set the checkpoint publication path allocates
# above the resident optimizer state for this mechanism's shard sizes
# (matches the #898 2026-08-21 amendment's receipted math: 8 GiB transient).
DENSE_A1_TRANSIENT_CHECKPOINT_BYTES = 8 * BYTES_PER_GIB

# Frozen safety reserve held back from the headroom computation, matching the
# reserve already receipted for this run in the same amendment.
DENSE_A1_RESERVE_BYTES = 6 * BYTES_PER_GIB

# The active-parameter count the #898 2026-08-21 amendment measured against
# (3.84B dense specialist-plus-shared parameters).
DENSE_A1_REFERENCE_ACTIVE_PARAMETERS = 3_840_000_000

# The single documented, auditable provisioning step this contract accepts:
# a FIXED (not system-managed) pagefile of at least this many MiB, set via
# the documented registry path below, applied before launch (not mid-run).
DOCUMENTED_PAGEFILE_REGISTRY_PATH = (
    r"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager"
    r"\Memory Management\PagingFiles"
)
DOCUMENTED_PAGEFILE_MINIMUM_MIB = 65536  # 64 GiB fixed; see docs/host-setup-contract.md
DOCUMENTED_PAGEFILE_VALUE_NAME = "PagingFiles"


@dataclass(frozen=True)
class HostMechanismProfile:
    """One ember mechanism's declared host commit-capacity requirement."""

    name: str
    active_parameters: int
    bytes_per_param: int
    transient_bytes: int
    reserve_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("host mechanism profile name must be a nonempty string")
        for field_name, value in (
            ("active_parameters", self.active_parameters),
            ("bytes_per_param", self.bytes_per_param),
            ("transient_bytes", self.transient_bytes),
            ("reserve_bytes", self.reserve_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"host mechanism profile {field_name} must be a positive integer")

    @property
    def optimizer_state_bytes(self) -> int:
        return self.active_parameters * self.bytes_per_param

    @property
    def required_headroom_bytes(self) -> int:
        return self.optimizer_state_bytes + self.transient_bytes + self.reserve_bytes


def dense_a1_full_state_cpu_offload_profile(
    active_parameters: int = DENSE_A1_REFERENCE_ACTIVE_PARAMETERS,
) -> HostMechanismProfile:
    """The declared host commit-capacity profile for dense-arm A1 training.

    Defaults to the #898 2026-08-21 amendment's reference parameter count
    (3.84B), which yields ~56.9 GiB required headroom -- matching the
    amendment's receipted math (42.9 GiB optimizer state + 8 GiB transient +
    6 GiB reserve).
    """

    if type(active_parameters) is not int or active_parameters <= 0:
        raise ValueError("active parameters must be a positive integer")
    return HostMechanismProfile(
        name="dense-a1-full-state-cpu-offload",
        active_parameters=active_parameters,
        bytes_per_param=_FULL_STATE_ADAMW_CPU_OFFLOAD_BYTES_PER_PARAM,
        transient_bytes=DENSE_A1_TRANSIENT_CHECKPOINT_BYTES,
        reserve_bytes=DENSE_A1_RESERVE_BYTES,
    )


class HostSetupContractRefusal(RuntimeError):
    """The live host cannot host a mechanism's declared commit-capacity profile.

    Distinct from an in-run resource-preflight refusal (``CheckpointDeferredLowCommit``
    in ``checkpoint_artifacts.py``): this fires BEFORE a run is dispatched, at
    host-setup time, and its message always names the exact shortfall in GiB
    plus the one documented remediation step. It never suggests ad-hoc OS
    tuning as a substitute -- the message says explicitly that mid-training
    manual tuning is not a supported path.
    """

    def __init__(self, *, profile: HostMechanismProfile, available_commit_bytes: int) -> None:
        if type(available_commit_bytes) is not int or available_commit_bytes < 0:
            raise ValueError("available commit bytes must be a nonnegative integer")
        self.profile = profile
        self.available_commit_bytes = available_commit_bytes
        self.required_headroom_bytes = profile.required_headroom_bytes
        self.shortfall_bytes = max(0, profile.required_headroom_bytes - available_commit_bytes)
        required_gib = profile.required_headroom_bytes / BYTES_PER_GIB
        available_gib = available_commit_bytes / BYTES_PER_GIB
        shortfall_gib = self.shortfall_bytes / BYTES_PER_GIB
        super().__init__(
            f"host setup contract refused mechanism '{profile.name}': requires "
            f"{required_gib:.2f} GiB host commit headroom (optimizer state "
            f"{profile.optimizer_state_bytes / BYTES_PER_GIB:.2f} GiB + transient "
            f"{profile.transient_bytes / BYTES_PER_GIB:.2f} GiB + reserve "
            f"{profile.reserve_bytes / BYTES_PER_GIB:.2f} GiB), but only "
            f"{available_gib:.2f} GiB is available -- shortfall {shortfall_gib:.2f} GiB. "
            f"This headroom is a property of the '{profile.name}' control-experiment "
            f"profile itself, not Ember's normal host floor. The one exception on "
            f"record is a fixed pagefile of at least {DOCUMENTED_PAGEFILE_MINIMUM_MIB} "
            f"MiB (registry value '{DOCUMENTED_PAGEFILE_VALUE_NAME}' under "
            f"{DOCUMENTED_PAGEFILE_REGISTRY_PATH}, effective after reboot), authorized "
            f"2026-08-21 as a temporary operator intervention to finish the current "
            f"dense control run (see docs/host-setup-contract.md) -- it is recorded "
            f"technical debt, not a durable or repeatable answer for future mechanisms. "
            f"Manual ad-hoc OS tuning mid-training is not a supported path; a mechanism "
            f"whose declared profile exceeds this exception's headroom must fit the "
            f"existing envelope, redesign to need less, or obtain its own fresh "
            f"operator-reviewed exception -- never assume this one as a default."
        )


def validate_host_setup_contract(
    profile: HostMechanismProfile,
    *,
    available_commit_bytes_probe: Callable[[], int],
) -> dict[str, int | str]:
    """Refuse admission when the live host cannot host ``profile``.

    ``available_commit_bytes_probe`` is injected so this validates against
    any headroom source -- the real Windows probe
    (``checkpoint_artifacts.available_host_commit_bytes``) in production, a
    fixed value in tests -- without this module importing platform-specific
    machinery itself.
    """

    if not callable(available_commit_bytes_probe):
        raise ValueError("available commit bytes probe must be callable")
    available_commit_bytes = available_commit_bytes_probe()
    if type(available_commit_bytes) is not int or available_commit_bytes < 0:
        raise ValueError("available commit bytes probe must return a nonnegative integer")
    if available_commit_bytes < profile.required_headroom_bytes:
        raise HostSetupContractRefusal(profile=profile, available_commit_bytes=available_commit_bytes)
    return {
        "status": "PASS",
        "mechanism": profile.name,
        "required_headroom_bytes": profile.required_headroom_bytes,
        "available_commit_bytes": available_commit_bytes,
    }
