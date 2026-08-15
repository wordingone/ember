// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// This entire file exercises the Windows named-pipe dispatch-token transport
// (EMBER_LAB_PIPE, windows_sys Win32 pipe APIs, raw Windows handles). Nothing
// in it targets Linux, so the whole file is gated rather than individual
// imports/usages -- an ungated top-level `use std::os::windows::io::...`
// here previously failed the whole ember-lab crate to COMPILE on
// ubuntu-latest CI (#1751), meaning zero tests in this crate ever ran there.
#![cfg(windows)]

use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::windows::io::{FromRawHandle, RawHandle};
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn hidden_command(program: &str) -> Command {
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

fn sandbox(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path =
        std::env::temp_dir().join(format!("ember-lab-{name}-{}-{nonce}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn fake_pipe(name: &str) -> String {
    format!(
        r"\\.\pipe\ember-lab-{name}-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    )
}

fn serve_forged_consumed_once(pipe_name: String) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        use windows_sys::Win32::Foundation::{
            GetLastError, ERROR_PIPE_CONNECTED, INVALID_HANDLE_VALUE,
        };
        use windows_sys::Win32::Storage::FileSystem::PIPE_ACCESS_DUPLEX;
        use windows_sys::Win32::System::Pipes::{
            ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_TYPE_BYTE, PIPE_WAIT,
        };

        let mut wide: Vec<u16> = pipe_name.encode_utf16().collect();
        wide.push(0);
        let handle = unsafe {
            CreateNamedPipeW(
                wide.as_ptr(),
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                4096,
                4096,
                0,
                std::ptr::null(),
            )
        };
        assert_ne!(handle, INVALID_HANDLE_VALUE);
        let connected = unsafe { ConnectNamedPipe(handle, std::ptr::null_mut()) };
        assert!(connected != 0 || unsafe { GetLastError() } == ERROR_PIPE_CONNECTED);
        let mut stream = unsafe { fs::File::from_raw_handle(handle as RawHandle) };
        let mut request = String::new();
        if BufReader::new(stream.try_clone().unwrap())
            .read_line(&mut request)
            .unwrap()
            > 0
        {
            writeln!(
                stream,
                "{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{\"consumed\":true}}}}"
            )
            .unwrap();
        }
    })
}

#[test]
fn direct_verify_training_without_daemon_token_refuses_before_receipt_or_source_read() {
    let root = sandbox("verify-training-direct-refusal");
    let missing_source = root.join("missing-source");
    let receipt = root.join("must-not-exist.json");
    let output = hidden_command(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "verify-training",
            "--root",
            missing_source.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
        ])
        .env_remove("EMBER_LAB_PIPE")
        .env_remove("EMBER_LAB_DISPATCH_JOB_ID")
        .env_remove("EMBER_LAB_DISPATCH_TOKEN")
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("VERIFIER_DISPATCH_TOKEN_REQUIRED"));
    assert!(!receipt.exists());
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn malformed_token_refuses_before_named_pipe_open_or_receipt_write() {
    let root = sandbox("verify-training-malformed-token");
    let receipt = root.join("must-not-exist.json");
    let output = hidden_command(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "verify-training",
            "--root",
            root.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
        ])
        .env("EMBER_LAB_PIPE", r"\\.\pipe\must-not-open")
        .env("EMBER_LAB_DISPATCH_JOB_ID", "job-1344")
        .env("EMBER_LAB_DISPATCH_TOKEN", "A".repeat(64))
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("VERIFIER_DISPATCH_TOKEN_INVALID"));
    assert!(!receipt.exists());
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn well_formed_token_and_forged_pipe_cannot_authorize_verifier_effects() {
    let root = sandbox("verify-training-forged-pipe");
    let missing_source = root.join("missing-source");
    let receipt = root.join("must-not-exist.json");
    let pipe = fake_pipe("forged-consume");
    let server = serve_forged_consumed_once(pipe.clone());
    let output = hidden_command(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "verify-training",
            "--root",
            missing_source.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
        ])
        .env("EMBER_LAB_PIPE", pipe)
        .env("EMBER_LAB_DISPATCH_JOB_ID", "job-1344")
        .env("EMBER_LAB_DISPATCH_TOKEN", "a".repeat(64))
        .env(
            "EMBER_LAB_DISPATCH_DAEMON_PID",
            std::process::id().to_string(),
        )
        .output()
        .unwrap();
    server.join().unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr)
        .contains("VERIFIER_DISPATCH_DAEMON_IDENTITY_REFUSED"));
    assert!(!receipt.exists());
    fs::remove_dir_all(root).unwrap();
}
