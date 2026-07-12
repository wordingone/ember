// goal_id: EMBER-01
// workstream_id: EMBER-01A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use crate::{Daemon, JobSpec};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io;
use std::path::PathBuf;

#[derive(Debug, Deserialize)]
struct WireRequest {
    jsonrpc: String,
    id: Value,
    method: String,
    #[serde(default)]
    params: Value,
}

#[derive(Debug, Deserialize)]
struct BindIdentityParams {
    job_id: String,
    path: PathBuf,
    sha256: String,
}

#[derive(Debug, Deserialize)]
struct LeaseParams {
    resource: String,
    job_id: String,
}

#[derive(Debug, Deserialize)]
struct JobIdParams {
    job_id: String,
}

#[derive(Debug, Deserialize)]
struct StartJobParams {
    job_id: String,
    program: String,
    args: Vec<String>,
    resource_lease: String,
    #[serde(default)]
    env: BTreeMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct ExportReceiptParams {
    job_id: String,
    path: PathBuf,
}

fn invalid_request(id: Value, message: impl Into<String>) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": -32600, "message": message.into()},
    })
}

fn invalid_params(id: Value, message: impl Into<String>) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": -32602, "message": message.into()},
    })
}

fn method_not_found(id: Value, method: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": -32601, "message": format!("unknown method {method}")},
    })
}

fn operation_error(id: Value, error: impl std::fmt::Debug) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": -32000, "message": "emberd operation failed", "data": format!("{error:?}")},
    })
}

fn success(id: Value, result: Value) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "result": result})
}

fn decode<T: for<'de> Deserialize<'de>>(id: &Value, params: Value) -> Result<T, Value> {
    serde_json::from_value(params).map_err(|error| invalid_params(id.clone(), error.to_string()))
}

fn dispatch(daemon: &Daemon, request: WireRequest) -> (Value, bool) {
    let id = request.id;
    if request.jsonrpc != "2.0" {
        return (invalid_request(id, "jsonrpc must be exactly 2.0"), false);
    }
    match request.method.as_str() {
        "ping" => (success(id, json!({"status": "ok"})), false),
        "bind_identity" => {
            let params: BindIdentityParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.bind_identity(&params.job_id, &params.path, &params.sha256) {
                Ok(()) => (success(id, json!({"bound": true})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "acquire_lease" => {
            let params: LeaseParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.acquire_lease(&params.resource, &params.job_id) {
                Ok(()) => (success(id, json!({"acquired": true})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "start_job" => {
            let params: StartJobParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            let mut spec = JobSpec::new(
                params.job_id,
                params.program,
                params.args,
                params.resource_lease,
            );
            for (key, value) in params.env {
                spec = spec.with_env(key, value);
            }
            match daemon.start_job(spec) {
                Ok(handle) => (success(id, json!({"pid": handle.pid})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "job_state" => {
            let params: JobIdParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.job_state(&params.job_id) {
                Ok(Some(state)) => (success(id, json!({"state": state.as_str()})), false),
                Ok(None) => (success(id, Value::Null), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "stop_job" => {
            let params: JobIdParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.stop_job(&params.job_id) {
                Ok(()) => (success(id, json!({"stopped": true})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "export_receipt" => {
            let params: ExportReceiptParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.export_receipt(&params.job_id, &params.path) {
                Ok(()) => (success(id, json!({"exported": true})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "shutdown" => (success(id, json!({"status": "shutting_down"})), true),
        method => (method_not_found(id, method), false),
    }
}

fn parse_and_dispatch(daemon: &Daemon, line: &str) -> (Value, bool) {
    match serde_json::from_str::<WireRequest>(line) {
        Ok(request) => dispatch(daemon, request),
        Err(error) => (
            json!({
                "jsonrpc": "2.0",
                "id": Value::Null,
                "error": {"code": -32700, "message": error.to_string()},
            }),
            false,
        ),
    }
}

#[cfg(windows)]
pub fn serve_named_pipe(daemon: &Daemon, pipe_name: &str) -> io::Result<()> {
    use std::fs::File;
    use std::io::{BufRead, BufReader, Write};
    use std::os::windows::io::{FromRawHandle, RawHandle};
    use windows_sys::Win32::Foundation::{
        GetLastError, ERROR_PIPE_CONNECTED, INVALID_HANDLE_VALUE,
    };
    use windows_sys::Win32::Storage::FileSystem::PIPE_ACCESS_DUPLEX;
    use windows_sys::Win32::System::Pipes::{
        ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE, PIPE_WAIT,
    };

    let mut wide: Vec<u16> = pipe_name.encode_utf16().collect();
    wide.push(0);
    loop {
        let handle = unsafe {
            CreateNamedPipeW(
                wide.as_ptr(),
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                1,
                64 * 1024,
                64 * 1024,
                0,
                std::ptr::null(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let connected = unsafe { ConnectNamedPipe(handle, std::ptr::null_mut()) };
        if connected == 0 && unsafe { GetLastError() } != ERROR_PIPE_CONNECTED {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(handle) };
            return Err(io::Error::last_os_error());
        }
        let mut stream = unsafe { File::from_raw_handle(handle as RawHandle) };
        let mut line = String::new();
        BufReader::new(stream.try_clone()?).read_line(&mut line)?;
        let (response, shutdown) = parse_and_dispatch(daemon, &line);
        let encoded = serde_json::to_string(&response)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        writeln!(stream, "{encoded}")?;
        stream.flush()?;
        drop(stream);
        if shutdown {
            return Ok(());
        }
    }
}

#[cfg(not(windows))]
pub fn serve_named_pipe(_daemon: &Daemon, _pipe_name: &str) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "named-pipe transport is only available on Windows",
    ))
}
