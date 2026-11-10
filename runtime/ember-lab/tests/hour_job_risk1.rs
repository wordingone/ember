// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! RISK 1 (lead ruling on the lab hour job): the hour must not inherit its daemon's lane. This test makes ITS OWN process
//! a below-normal, single-CPU process (the shape of a daemon started from a reduced-priority lane), starts an hour through
//! `Daemon::start_hour`, and reads the live hour process back through the Win32 API: NORMAL priority, full system mask.
//! One test per file: it changes process-wide state, so it runs in its own test binary.
#![cfg(windows)]

use ember_lab::hour_job::{hour_env, HourStartRequest};
use ember_lab::Daemon;
use sha2::{Digest, Sha256};
use std::fs;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::System::Threading::{
    GetCurrentProcess, GetPriorityClass, GetProcessAffinityMask, OpenProcess, SetPriorityClass,
    SetProcessAffinityMask, BELOW_NORMAL_PRIORITY_CLASS, NORMAL_PRIORITY_CLASS,
    PROCESS_QUERY_LIMITED_INFORMATION,
};

const SCRIPT: &str = "#!/bin/bash\nwhile [ ! -f \"$STOP_FILE\" ]; do sleep 1; done\nexit 0\n";

#[test]
fn the_hour_child_is_normal_priority_on_every_cpu_even_from_a_below_normal_single_cpu_daemon() {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let dir = std::env::temp_dir().join(format!("ember-lab-hour-risk1-{}-{nonce}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let script = dir.join("h99_dispatch_v1.sh");
    fs::write(&script, SCRIPT).unwrap();
    let stop = dir.join("stop.flag");
    let mut env = hour_env(std::env::vars());
    env.insert("STOP_FILE".into(), stop.to_string_lossy().replace('\\', "/"));

    let me = unsafe { GetCurrentProcess() };
    let (mut original_process, mut system) = (0usize, 0usize);
    assert_ne!(unsafe { GetProcessAffinityMask(me, &mut original_process, &mut system) }, 0);
    assert!(system.count_ones() >= 2, "the host needs at least two logical CPUs for this test");
    let original_priority = unsafe { GetPriorityClass(me) };

    // Become the worst-case daemon: below normal, pinned to the lowest single CPU.
    assert_ne!(unsafe { SetPriorityClass(me, BELOW_NORMAL_PRIORITY_CLASS) }, 0);
    let lowest = 1usize << system.trailing_zeros();
    assert_ne!(unsafe { SetProcessAffinityMask(me, lowest) }, 0);
    let daemon = Daemon::open(&dir.join("lab.sqlite3")).unwrap();
    let started = daemon.start_hour(HourStartRequest {
        script: script.clone(),
        sha256: format!("{:x}", Sha256::digest(SCRIPT.as_bytes())),
        log: dir.join("hour.log"),
        cwd: Some(dir.clone()),
        bash: None,
        env,
    });
    // Restore the test process before any assertion can fail.
    unsafe {
        SetProcessAffinityMask(me, original_process);
        SetPriorityClass(me, original_priority);
    }
    let started = started.expect("start_hour from a below-normal single-CPU daemon");

    let deadline = Instant::now() + Duration::from_secs(10);
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, started.pid) };
    assert!(!handle.is_null(), "cannot open the hour process {}", started.pid);
    let (mut child_mask, mut child_system) = (0usize, 0usize);
    let child_priority = unsafe { GetPriorityClass(handle) };
    assert_ne!(unsafe { GetProcessAffinityMask(handle, &mut child_mask, &mut child_system) }, 0);
    unsafe { CloseHandle(handle) };
    assert!(Instant::now() < deadline);

    fs::write(&stop, b"stop").unwrap();
    thread::sleep(Duration::from_millis(200));
    assert_eq!(child_priority, NORMAL_PRIORITY_CLASS, "hour child priority class");
    assert_eq!(child_mask, system, "hour child CPU mask must be the full system mask");
    // The receipt records what the daemon was, as a covariate.
    let receipt: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(&started.receipt_path).unwrap()).unwrap();
    assert_eq!(receipt["daemon_priority_class"], BELOW_NORMAL_PRIORITY_CLASS);
    assert_eq!(receipt["daemon_affinity_mask"], lowest);
    assert_eq!(receipt["daemon_system_mask"], system);
}
