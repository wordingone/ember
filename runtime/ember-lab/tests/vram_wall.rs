// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 A VRAM wall

#![cfg(windows)]

use ember_lab::{
    evaluate_vram_wall_samples, VramDeviceCapacity, VramWallBreachClass, VramWallContract,
    VramWallDecision, VramWallSample,
};

const MIB: u64 = 1024 * 1024;
const UUID: &str = "GPU-00000000-1111-2222-3333-444444444444";

fn capacity(free_bytes: u64) -> VramDeviceCapacity {
    VramDeviceCapacity {
        provider: "nvidia_smi_nvml".into(),
        device_uuid: UUID.into(),
        total_bytes: 1_000 * MIB,
        free_bytes,
    }
}

fn contract() -> VramWallContract {
    VramWallContract {
        provider: "nvidia_smi_nvml".into(),
        device_uuid: UUID.into(),
        maximum_process_fraction_millionths: 500_000,
        minimum_free_bytes: 200 * MIB,
        consecutive_breach_samples: 3,
        sample_interval_ms: 2_000,
    }
}

fn sample(observed_at_ms: i64, used_bytes: u64, free_bytes: u64) -> VramWallSample {
    VramWallSample {
        observed_at_ms,
        pid: 4242,
        process_start_token: "01dcf00ddeadbeef".into(),
        used_bytes,
        capacity: capacity(free_bytes),
    }
}

#[test]
fn sentinel_requires_three_consecutive_over_fraction_observations() {
    let wall = contract();
    let one = evaluate_vram_wall_samples(&wall, &[sample(1_000, 501 * MIB, 499 * MIB)])
        .expect("one valid sample must evaluate");
    assert_eq!(
        one,
        VramWallDecision::Pending {
            breach_class: VramWallBreachClass::ProcessFraction,
            consecutive_observations: 1,
            required_observations: 3,
        }
    );

    let reset = evaluate_vram_wall_samples(
        &wall,
        &[
            sample(1_000, 501 * MIB, 499 * MIB),
            sample(3_000, 499 * MIB, 501 * MIB),
            sample(5_000, 501 * MIB, 499 * MIB),
        ],
    )
    .expect("healthy observation resets the debounce sequence");
    assert_eq!(
        reset,
        VramWallDecision::Pending {
            breach_class: VramWallBreachClass::ProcessFraction,
            consecutive_observations: 1,
            required_observations: 3,
        }
    );

    let stop = evaluate_vram_wall_samples(
        &wall,
        &[
            sample(1_000, 501 * MIB, 499 * MIB),
            sample(3_000, 502 * MIB, 498 * MIB),
            sample(5_000, 503 * MIB, 497 * MIB),
        ],
    )
    .expect("three bound samples must evaluate");
    assert_eq!(
        stop,
        VramWallDecision::ProtectiveStop {
            breach_class: VramWallBreachClass::ProcessFraction,
            consecutive_observations: 3,
            required_observations: 3,
        }
    );
}

#[test]
fn floor_breach_uses_the_same_debounced_owned_stop_rule() {
    let wall = contract();
    let decision = evaluate_vram_wall_samples(
        &wall,
        &[
            sample(1_000, 100 * MIB, 199 * MIB),
            sample(3_000, 100 * MIB, 198 * MIB),
            sample(5_000, 100 * MIB, 197 * MIB),
        ],
    )
    .unwrap();
    assert_eq!(
        decision,
        VramWallDecision::ProtectiveStop {
            breach_class: VramWallBreachClass::FreeFloor,
            consecutive_observations: 3,
            required_observations: 3,
        }
    );
}

#[test]
fn device_uuid_and_provider_mismatch_refuse_instead_of_skipping() {
    let mut wrong_uuid = sample(1_000, 1, 900 * MIB);
    wrong_uuid.capacity.device_uuid = "GPU-foreign".into();
    assert!(evaluate_vram_wall_samples(&contract(), &[wrong_uuid]).is_err());

    let mut wrong_provider = sample(1_000, 1, 900 * MIB);
    wrong_provider.capacity.provider = "caller_self_report".into();
    assert!(evaluate_vram_wall_samples(&contract(), &[wrong_provider]).is_err());
}

#[test]
fn sparse_or_non_monotone_samples_refuse_instead_of_counting_as_consecutive() {
    let sparse = [
        sample(1_000, 501 * MIB, 499 * MIB),
        sample(20_000, 502 * MIB, 498 * MIB),
        sample(40_000, 503 * MIB, 497 * MIB),
    ];
    assert!(evaluate_vram_wall_samples(&contract(), &sparse).is_err());

    let non_monotone = [
        sample(3_000, 501 * MIB, 499 * MIB),
        sample(1_000, 502 * MIB, 498 * MIB),
    ];
    assert!(evaluate_vram_wall_samples(&contract(), &non_monotone).is_err());
}

#[test]
fn pid_or_start_token_change_mid_window_refuses() {
    let first = sample(1_000, 501 * MIB, 499 * MIB);
    let mut changed_pid = sample(3_000, 502 * MIB, 498 * MIB);
    changed_pid.pid = 4243;
    assert!(evaluate_vram_wall_samples(&contract(), &[first.clone(), changed_pid]).is_err());

    let mut changed_token = sample(3_000, 502 * MIB, 498 * MIB);
    changed_token.process_start_token = "01dcf00d-reused".into();
    assert!(evaluate_vram_wall_samples(&contract(), &[first, changed_token]).is_err());
}

#[test]
fn debounce_count_and_cadence_are_daemon_fixed_not_caller_tunable() {
    let mut one_sample = contract();
    one_sample.consecutive_breach_samples = 1;
    assert!(
        evaluate_vram_wall_samples(&one_sample, &[sample(1_000, 501 * MIB, 499 * MIB)]).is_err()
    );

    let mut fast_poll = contract();
    fast_poll.sample_interval_ms = 1;
    assert!(
        evaluate_vram_wall_samples(&fast_poll, &[sample(1_000, 501 * MIB, 499 * MIB)]).is_err()
    );
}

#[test]
fn fraction_is_an_allocator_contract_not_a_total_vram_guarantee() {
    let wall = contract();
    let decision = evaluate_vram_wall_samples(&wall, &[sample(1_000, 499 * MIB, 50 * MIB)])
        .expect("bound sample must evaluate");
    assert_eq!(
        decision,
        VramWallDecision::Pending {
            breach_class: VramWallBreachClass::FreeFloor,
            consecutive_observations: 1,
            required_observations: 3,
        },
        "torch's allocator fraction is not a total-VRAM guarantee; the independent floor sentinel is load-bearing"
    );
}
