// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use crate::{
    server_supervisor::ServerLiveCycleRequest, Daemon, SchedulePrediction,
    MAX_DISPATCH_MANIFEST_BYTES,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::io;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const MAX_ASSESSMENT_DIRECTORY_UTF8_BYTES: usize = 4096;

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
struct SchedulePredictionParams {
    job_id: String,
    artifact_class: String,
    predicted_duration_ms: i64,
    predicted_tokens: i64,
    predicted_program_completion_ms: i64,
    absolute_deadline_ms: i64,
}

#[derive(Debug, Deserialize)]
struct ScheduleMeasurementParams {
    job_id: String,
    measured_duration_ms: i64,
    measured_tokens: i64,
    outcome: String,
    receipt_sha256: String,
}

#[derive(Debug, Deserialize)]
struct AlarmStateParams {
    path: PathBuf,
}

#[derive(Debug, Deserialize)]
struct JobIdParams {
    job_id: String,
}

#[derive(Debug, Deserialize)]
struct DispatchManifestParams {
    manifest_utf8: String,
    manifest_sha256: String,
}

#[derive(Debug, Deserialize)]
struct ExportReceiptParams {
    job_id: String,
    path: PathBuf,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ContentAddressedReceiptParams {
    job_id: String,
    directory: PathBuf,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AssessmentEvidenceParams {
    job_id: String,
    directory: PathBuf,
}

#[derive(Debug, Deserialize)]
struct PlanOutageParams {
    resource: String,
    starts_at_ms: i64,
    ends_at_ms: i64,
    reason: String,
}

#[derive(Debug, Deserialize)]
struct ResourceParams {
    resource: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ServerCycleParams {
    authority_path: PathBuf,
    authority_sha256: String,
    receipt_path: PathBuf,
    restore_manifest_path: PathBuf,
    serving_contract_path: PathBuf,
    serving_contract_sha256: String,
    required_headroom_bytes: u64,
    now_ms: i64,
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
        "error": {"code": -32000, "message": "ember-lab operation failed", "data": format!("{error:?}")},
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
        "runtime_identity" => (
            success(
                id,
                json!({
                    "schema_version": "ember-lab-runtime-identity-v1",
                    "pid": std::process::id(),
                }),
            ),
            false,
        ),
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
        "register_schedule_prediction" => {
            let params: SchedulePredictionParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            let prediction = SchedulePrediction {
                job_id: params.job_id,
                artifact_class: params.artifact_class,
                predicted_duration_ms: params.predicted_duration_ms,
                predicted_tokens: params.predicted_tokens,
                predicted_program_completion_ms: params.predicted_program_completion_ms,
                absolute_deadline_ms: params.absolute_deadline_ms,
            };
            match daemon.register_schedule_prediction(prediction) {
                Ok(()) => (success(id, json!({"registered": true})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "record_schedule_measurement" => {
            let params: ScheduleMeasurementParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.record_schedule_measurement(
                &params.job_id,
                params.measured_duration_ms,
                params.measured_tokens,
                &params.outcome,
                &params.receipt_sha256,
            ) {
                Ok(()) => (success(id, json!({"recorded": true})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "write_schedule_alarm_state" => {
            let params: AlarmStateParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.write_schedule_alarm_state(&params.path) {
                Ok(()) => (success(id, json!({"written": true})), false),
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
        "dispatch_manifest" => {
            let params: DispatchManifestParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            let manifest_bytes = params.manifest_utf8.into_bytes();
            if manifest_bytes.len() > MAX_DISPATCH_MANIFEST_BYTES {
                return (
                    invalid_params(id, "dispatch manifest exceeds the UTF-8 transport ceiling"),
                    false,
                );
            }
            match daemon.dispatch_manifest_bytes(&manifest_bytes, &params.manifest_sha256) {
                Ok(outcome) => (
                    success(
                        id,
                        json!({
                            "pid": outcome.handle.pid,
                            "preflight_receipt_path": outcome.receipt.path,
                            "preflight_receipt_sha256": outcome.receipt.sha256,
                        }),
                    ),
                    false,
                ),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "supervise_server_cycle" => {
            let params: ServerCycleParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            let request = ServerLiveCycleRequest {
                authority_path: params.authority_path,
                authority_sha256: params.authority_sha256,
                receipt_path: params.receipt_path,
                restore_manifest_path: params.restore_manifest_path,
                serving_contract_path: params.serving_contract_path,
                serving_contract_sha256: params.serving_contract_sha256,
                required_headroom_bytes: params.required_headroom_bytes,
                now_ms: params.now_ms,
            };
            match daemon.supervise_server_live_cycle(request) {
                Ok(receipt) => match serde_json::to_value(receipt) {
                    Ok(value) => (success(id, value), false),
                    Err(error) => (operation_error(id, error), false),
                },
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
        "export_content_addressed_receipt" => {
            let params: ContentAddressedReceiptParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.export_content_addressed_receipt(&params.job_id, &params.directory) {
                Ok(artifact) => (
                    success(id, json!({"path":artifact.path,"sha256":artifact.sha256})),
                    false,
                ),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "export_assessment_evidence" => {
            let params: AssessmentEvidenceParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            if params.directory.to_string_lossy().len() > MAX_ASSESSMENT_DIRECTORY_UTF8_BYTES {
                return (
                    invalid_params(id, "assessment evidence directory exceeds 4096 UTF-8 bytes"),
                    false,
                );
            }
            match daemon.export_assessment_evidence(&params.job_id, &params.directory) {
                Ok(artifact) => match serde_json::to_value(artifact) {
                    Ok(value) => (success(id, value), false),
                    Err(error) => (operation_error(id, error), false),
                },
                Err(error) => (operation_error(id, error), false),
            }
        }
        "plan_outage" => {
            let params: PlanOutageParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.plan_outage(
                &params.resource,
                params.starts_at_ms,
                params.ends_at_ms,
                &params.reason,
            ) {
                Ok(outage_id) => (success(id, json!({"outage_id":outage_id})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "cancel_outages" => {
            let params: ResourceParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.cancel_outages(&params.resource) {
                Ok(count) => (success(id, json!({"cancelled":count})), false),
                Err(error) => (operation_error(id, error), false),
            }
        }
        "job_exit_code" => {
            let params: JobIdParams = match decode(&id, request.params) {
                Ok(value) => value,
                Err(response) => return (response, false),
            };
            match daemon.job_exit_code(&params.job_id) {
                Ok(exit_code) => (success(id, json!({"exit_code":exit_code})), false),
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
const MAX_REQUEST_BYTES: usize = 64 * 1024;
#[cfg(windows)]
const REQUEST_IDLE_TIMEOUT: std::time::Duration = std::time::Duration::from_millis(500);

#[cfg(windows)]
struct TokenHandle(windows_sys::Win32::Foundation::HANDLE);

#[cfg(windows)]
impl Drop for TokenHandle {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(self.0) };
        }
    }
}

#[cfg(windows)]
struct LocalSecurityDescriptor(windows_sys::Win32::Security::PSECURITY_DESCRIPTOR);

#[cfg(windows)]
impl Drop for LocalSecurityDescriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { windows_sys::Win32::Foundation::LocalFree(self.0) };
        }
    }
}

#[cfg(windows)]
fn sid_to_string(sid: windows_sys::Win32::Security::PSID) -> io::Result<String> {
    use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;

    let mut sid_string = std::ptr::null_mut();
    if unsafe { ConvertSidToStringSidW(sid, &mut sid_string) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let mut len = 0usize;
    while unsafe { *sid_string.add(len) } != 0 {
        len += 1;
    }
    let result = String::from_utf16_lossy(unsafe { std::slice::from_raw_parts(sid_string, len) });
    unsafe { windows_sys::Win32::Foundation::LocalFree(sid_string.cast()) };
    Ok(result)
}

#[cfg(windows)]
fn current_process_token() -> io::Result<TokenHandle> {
    use windows_sys::Win32::Security::TOKEN_QUERY;
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    let mut token = std::ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(TokenHandle(token))
}

#[cfg(windows)]
fn current_user_sid_string() -> io::Result<String> {
    use windows_sys::Win32::Security::{TokenUser, TOKEN_USER};

    let token = current_process_token()?;
    let user_buffer = token_information_buffer(token.0, TokenUser)?;
    let user = unsafe { &*(user_buffer.as_ptr().cast::<TOKEN_USER>()) };
    sid_to_string(user.User.Sid)
}

#[cfg(windows)]
fn current_restricting_sid_strings() -> io::Result<Vec<String>> {
    use windows_sys::Win32::Security::{TokenRestrictedSids, TOKEN_GROUPS};

    let token = current_process_token()?;
    let groups_buffer = token_information_buffer(token.0, TokenRestrictedSids)?;
    let groups = unsafe { &*(groups_buffer.as_ptr().cast::<TOKEN_GROUPS>()) };
    let mut result = Vec::with_capacity(groups.GroupCount as usize);
    let first = groups.Groups.as_ptr();
    for index in 0..groups.GroupCount as usize {
        result.push(sid_to_string(unsafe { (*first.add(index)).Sid })?);
    }
    Ok(result)
}

#[cfg(windows)]
fn same_user_pipe_security() -> io::Result<LocalSecurityDescriptor> {
    use windows_sys::Win32::Security::Authorization::{
        ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1,
    };

    let mut sddl = format!("D:P(A;;GA;;;{})", current_user_sid_string()?);
    for sid in current_restricting_sid_strings()? {
        sddl.push_str(&format!("(A;;GA;;;{sid})"));
    }
    let mut wide: Vec<u16> = sddl.encode_utf16().collect();
    wide.push(0);
    let mut descriptor = std::ptr::null_mut();
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            wide.as_ptr(),
            SDDL_REVISION_1,
            &mut descriptor,
            std::ptr::null_mut(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(LocalSecurityDescriptor(descriptor))
}

#[cfg(windows)]
struct TokenInformationBuffer(Vec<usize>);

#[cfg(windows)]
impl TokenInformationBuffer {
    fn as_ptr(&self) -> *const u8 {
        self.0.as_ptr().cast()
    }
}

#[cfg(windows)]
fn token_information_buffer(
    token: windows_sys::Win32::Foundation::HANDLE,
    class: windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS,
) -> io::Result<TokenInformationBuffer> {
    use windows_sys::Win32::Security::GetTokenInformation;

    let mut bytes = 0u32;
    unsafe { GetTokenInformation(token, class, std::ptr::null_mut(), 0, &mut bytes) };
    if bytes == 0 {
        return Err(io::Error::last_os_error());
    }
    let words = (bytes as usize).div_ceil(std::mem::size_of::<usize>());
    let mut buffer = vec![0usize; words.max(1)];
    if unsafe { GetTokenInformation(token, class, buffer.as_mut_ptr().cast(), bytes, &mut bytes) }
        == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(TokenInformationBuffer(buffer))
}
#[cfg(windows)]
fn token_user_buffer(
    token: windows_sys::Win32::Foundation::HANDLE,
) -> io::Result<TokenInformationBuffer> {
    use windows_sys::Win32::Security::TokenUser;
    token_information_buffer(token, TokenUser)
}
#[cfg(windows)]
fn client_is_same_user(pipe: windows_sys::Win32::Foundation::HANDLE) -> io::Result<bool> {
    use windows_sys::Win32::Security::{
        EqualSid, RevertToSelf, TokenUser, TOKEN_QUERY, TOKEN_USER,
    };
    use windows_sys::Win32::System::Pipes::ImpersonateNamedPipeClient;
    use windows_sys::Win32::System::Threading::{
        GetCurrentProcess, GetCurrentThread, OpenProcessToken, OpenThreadToken,
    };

    let mut server_token = std::ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut server_token) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let server_token = TokenHandle(server_token);

    if unsafe { ImpersonateNamedPipeClient(pipe) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let client_token_result = (|| {
        let mut client_token = std::ptr::null_mut();
        if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut client_token) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(TokenHandle(client_token))
    })();
    let reverted = unsafe { RevertToSelf() };
    let client_token = client_token_result?;
    if reverted == 0 {
        return Err(io::Error::last_os_error());
    }

    let server = token_user_buffer(server_token.0)?;
    let client = token_user_buffer(client_token.0)?;
    let server_user = unsafe { &*(server.as_ptr().cast::<TOKEN_USER>()) };
    let client_user = unsafe { &*(client.as_ptr().cast::<TOKEN_USER>()) };
    let _ = TokenUser;
    Ok(unsafe { EqualSid(server_user.User.Sid, client_user.User.Sid) } != 0)
}

#[cfg(windows)]
enum RequestBytes {
    Line(String),
    TooLarge,
}

#[cfg(windows)]
fn read_request(
    stream: &mut std::fs::File,
    pipe: windows_sys::Win32::Foundation::HANDLE,
) -> io::Result<RequestBytes> {
    use std::io::Read;
    use windows_sys::Win32::System::Pipes::PeekNamedPipe;

    let deadline = std::time::Instant::now() + REQUEST_IDLE_TIMEOUT;
    let mut bytes = Vec::with_capacity(4096);
    loop {
        let mut available = 0u32;
        if unsafe {
            PeekNamedPipe(
                pipe,
                std::ptr::null_mut(),
                0,
                std::ptr::null_mut(),
                &mut available,
                std::ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        if available == 0 {
            if std::time::Instant::now() >= deadline {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "named-pipe request idle timeout",
                ));
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
            continue;
        }

        let remaining = MAX_REQUEST_BYTES
            .saturating_add(1)
            .saturating_sub(bytes.len());
        if remaining == 0 {
            return Ok(RequestBytes::TooLarge);
        }
        let mut chunk = vec![0u8; (available as usize).min(remaining)];
        let read = stream.read(&mut chunk)?;
        if read == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "named-pipe client disconnected",
            ));
        }
        if let Some(newline) = chunk[..read].iter().position(|byte| *byte == b'\n') {
            bytes.extend_from_slice(&chunk[..newline]);
            if bytes.len() > MAX_REQUEST_BYTES {
                return Ok(RequestBytes::TooLarge);
            }
            let line = String::from_utf8(bytes)
                .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
            return Ok(RequestBytes::Line(line));
        }
        bytes.extend_from_slice(&chunk[..read]);
        if bytes.len() > MAX_REQUEST_BYTES {
            return Ok(RequestBytes::TooLarge);
        }
    }
}

#[cfg(windows)]
fn write_response(stream: &mut std::fs::File, response: &Value) -> io::Result<()> {
    use std::io::Write;

    let encoded = serde_json::to_string(response)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    writeln!(stream, "{encoded}")?;
    stream.flush()
}

#[cfg(windows)]
fn handle_connection(
    daemon: &Daemon,
    mut stream: std::fs::File,
    pipe: windows_sys::Win32::Foundation::HANDLE,
) -> io::Result<bool> {
    let request = match read_request(&mut stream, pipe)? {
        RequestBytes::Line(line) => line,
        RequestBytes::TooLarge => {
            let response = invalid_request(Value::Null, "request exceeds 65536 bytes");
            write_response(&mut stream, &response)?;
            return Ok(false);
        }
    };
    if !client_is_same_user(pipe)? {
        let response = json!({
            "jsonrpc": "2.0",
            "id": Value::Null,
            "error": {"code": -32001, "message": "client user does not own this ember-lab"},
        });
        write_response(&mut stream, &response)?;
        return Ok(false);
    }
    let (response, shutdown) = parse_and_dispatch(daemon, &request);
    write_response(&mut stream, &response)?;
    Ok(shutdown)
}

#[cfg(windows)]
pub fn serve_named_pipe(daemon: Arc<Daemon>, pipe_name: &str) -> io::Result<()> {
    use std::fs::File;
    use std::os::windows::io::{FromRawHandle, RawHandle};
    use windows_sys::Win32::Foundation::{
        CloseHandle, GetLastError, ERROR_PIPE_CONNECTED, INVALID_HANDLE_VALUE,
    };
    use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
    use windows_sys::Win32::Storage::FileSystem::PIPE_ACCESS_DUPLEX;
    use windows_sys::Win32::System::Pipes::{
        ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_REJECT_REMOTE_CLIENTS,
        PIPE_TYPE_BYTE, PIPE_WAIT,
    };

    let mut wide: Vec<u16> = pipe_name.encode_utf16().collect();
    wide.push(0);
    let security_descriptor = same_user_pipe_security()?;
    let security_attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: security_descriptor.0,
        bInheritHandle: 0,
    };
    let shutdown = Arc::new(AtomicBool::new(false));
    let worker_shutdown = Arc::clone(&shutdown);
    let worker_daemon = Arc::clone(&daemon);
    let worker = thread::spawn(move || {
        while !worker_shutdown.load(Ordering::Acquire) {
            let now_ms = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|duration| duration.as_millis() as i64)
                .unwrap_or(0);
            if let Err(error) = worker_daemon.supervise_registered_server_once(now_ms) {
                if let Err(record_error) = worker_daemon.record_supervision_error(now_ms, &error) {
                    eprintln!("ember-lab supervision failure was not receipted: {record_error}");
                }
            }
            thread::sleep(Duration::from_secs(1));
        }
    });
    let result = (|| loop {
        let handle = unsafe {
            CreateNamedPipeW(
                wide.as_ptr(),
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                64 * 1024,
                64 * 1024,
                0,
                &security_attributes,
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let connected = unsafe { ConnectNamedPipe(handle, std::ptr::null_mut()) };
        if connected == 0 && unsafe { GetLastError() } != ERROR_PIPE_CONNECTED {
            unsafe { CloseHandle(handle) };
            continue;
        }

        let stream = unsafe { File::from_raw_handle(handle as RawHandle) };
        if handle_connection(&daemon, stream, handle).unwrap_or(false) {
            break Ok(());
        }
    })();
    shutdown.store(true, Ordering::Release);
    let _ = worker.join();
    result
}

#[cfg(not(windows))]
pub fn serve_named_pipe(_daemon: Arc<Daemon>, _pipe_name: &str) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "named-pipe transport is only available on Windows",
    ))
}

#[cfg(test)]
mod tests {
    use super::ServerCycleParams;

    #[test]
    fn server_cycle_params_reject_caller_restart_count() {
        let value = serde_json::json!({
            "authority_path": "authority.json",
            "authority_sha256": "a".repeat(64),
            "receipt_path": "receipt.json",
            "restore_manifest_path": "restore.json",
            "serving_contract_path": "serving-contract.json",
            "serving_contract_sha256": "b".repeat(64),
            "required_headroom_bytes": 1,
            "now_ms": 1,
            "restarts_last_hour": 3,
        });
        assert!(serde_json::from_value::<ServerCycleParams>(value).is_err());
    }

    #[test]
    fn server_cycle_params_require_content_addressed_serving_contract() {
        let value = serde_json::json!({
            "authority_path": "authority.json",
            "authority_sha256": "a".repeat(64),
            "receipt_path": "receipt.json",
            "restore_manifest_path": "restore.json",
            "required_headroom_bytes": 1,
            "now_ms": 1,
        });
        assert!(serde_json::from_value::<ServerCycleParams>(value).is_err());
    }
}
