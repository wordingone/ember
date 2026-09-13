# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python
"""Boundary energy collector for the #1945 governed hour (SD032). Revision 3.

WHAT THIS IS
------------
SD032 requires the energy consumed DURING the governed hour, and no collector existed. This is the
smallest instrument that answers it honestly: two NVML samples of the device's total-energy counter,
one at the hour's first update boundary and one at its last, bound to the hour's run identity and
custody.

WHY BOUNDARY-ONLY
-----------------
A sampling daemon would be a live python process on the host for the whole hour, and the native
resource census refuses a governed launch when it finds one. The counter is monotonic since driver
load, so two reads answer the question and the instrument costs the hour nothing between them.

REVISION 2 -- what the other seat's review changed, and why each change was right
--------------------------------------------------------------------------------
1. BOUNDARY SOURCE. Revision 1 required the hour's own start/end wall clock and refused unless the
   energy window contained it with under 60 s of slack. The hour receipt carries NO wall-clock
   fields, and an outer begin-before-dispatch / end-after-job placement necessarily brackets model
   construction, parent load, capture and the terminal checkpoint write -- far more than 60 s. So
   revision 1 would have REFUSED every real invocation: a predicate its only consumer cannot satisfy.
   That is the prove-the-consumer failure, found by the reviewer rather than by me.

   Revision 2 makes the placement explicit instead of assumed, with --boundary-source:

     worker   -- the two samples ARE taken at the worker's own first/last update boundary, in
                 process. The measured interval then DEFINES the hour window rather than being
                 compared to one, slack is zero by construction, and the caller records how the
                 boundary was reached in --placement-evidence, which is written into the receipt and
                 into the claim boundary. No hour timestamps are required or invented.
     external -- the revision 1 path, unchanged and still strict: the caller supplies the hour's own
                 measured interval and the energy window must contain it within --max-slack-seconds.
                 Available for a caller that can supply real boundary timestamps.

   Neither mode guesses. The difference is which artifact carries the boundary claim, and the receipt
   says which one it was.

2. ENFORCED POWER LIMIT AND THE TWO-POINT RELATION. Each sample now reads the NVML version and the
   device's ENFORCED power limit, and the end refuses when the computed average power exceeds that
   limit -- an average above what the board is allowed to draw means the counter, the interval, or
   the device binding is wrong, and it is the one physical check available from two points. The two
   endpoint instantaneous readings are recorded and their bracket is REPORTED, never used to qualify:
   a real hour varies between its endpoints, so a value outside that bracket is information for the
   reader and not a refusal. Fields that do not qualify the verdict are labelled as such in the
   receipt rather than presented as if they had been checked.

3. EVERY EXIT WRITES A RECEIPT. Revision 1 caught its own named refusals but let an unexpected error
   -- a missing key in the begin receipt, a malformed field, an unwritable path -- escape as a
   traceback with no receipt. That is the exact failure I have already committed once on this
   campaign (a NameError instead of a REFUSED receipt). Both verbs now convert any unexpected
   exception into an internal_error refusal carrying its type and message, so no invocation can end
   without a durable statement of what happened.

4. nvmlShutdown's return code is checked and recorded rather than discarded.

REVISION 3 -- the reviewer's second finding, and it was a real one
-------------------------------------------------------------------
Revision 2 RECORDED nvml_shutdown_code at three call sites and refused on it at none of them,
so the documentation above claimed a check the code did not perform. The adjudication now lives
inside sample_device on its success path (it cannot live in the finally clause without masking a
real exception, and it must not live at the call sites, because three sites recording and none
refusing is exactly what happens again at a fourth site). Every caller inherits the refusal
before any SAMPLED or MEASURED receipt is written.

WHAT IT REFUSES ON (each writes its own receipt and exits 3)
------------------------------------------------------------
  nvml_absent, nvml_symbol_missing, nvml_init_failed, nvml_call_failed  -- the library, its symbols,
      or any individual call. Every ctypes signature is declared before use, because an untyped call
      already produced a probe on this campaign that failed on every sample and reported the most
      favourable number.
  counter_unsupported          -- pre-Volta returns NVML_ERROR_NOT_SUPPORTED. Unsupported is a
                                  refusal, never a zero.
  power_limit_unavailable      -- without the enforced limit the physical check cannot run.
  nvml_shutdown_failed         -- the sample completed but nvmlShutdown returned nonzero; the
                                  library was left in an unknown state, so the reading is not
                                  offered as a measurement.
  device_changed / driver_changed / nvml_version_changed -- the counter's origin moved between the
                                  samples, so the difference is not an energy.
  counter_reset                -- the end counter is below the begin counter (driver reload).
  non_positive_interval        -- the end sample does not follow the begin sample.
  average_power_above_enforced_limit -- physically impossible; the measurement is wrong somewhere.
  interval_not_covered / interval_slack_exceeded -- external mode only. Both directions are defects:
                                  a window missing part of the hour under-reports it, a window opened
                                  long before it charges idle energy to the hour.
  placement_evidence_missing   -- worker mode without a stated placement is an unsupported claim.
  begin_receipt_* / producer_mismatch -- the two ends must be one instrument.
  internal_error               -- anything unforeseen, with a receipt.

The duration is MEASURED from the two monotonic reads. Nothing here reads a nominal 3600.

USAGE
-----
  worker mode (preferred; the caller places the samples at the update boundary):

    begin --run-id <32 lowercase hex> --custody <hour custody root> --device-index 0
          --boundary-source worker --out <custody>/energy-boundary-begin.json
    end   --begin <custody>/energy-boundary-begin.json
          --placement-evidence "<how the two samples were placed at the first/last update boundary>"
          --out <custody>/energy-boundary-result.json

  external mode (the caller supplies the hour's own measured interval):

    begin ... --boundary-source external ...
    end   --begin ... --hour-start-unix <float> --hour-end-unix <float>
          [--max-slack-seconds 60] --out ...

Exit codes: 0 measured, 3 refused, 2 usage. --out is never overwritten.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import sys
import time
from ctypes import POINTER, byref, c_char_p, c_uint, c_ulonglong, c_void_p, create_string_buffer

SCHEMA = 'ember-issue1945-boundary-energy-v2'
REVISION = 3
RUN_ID_RE = re.compile(r'^[0-9a-f]{32}$')
NVML_SUCCESS = 0
NVML_ERROR_NOT_SUPPORTED = 3
BUF = 256


class Refused(Exception):
    def __init__(self, tag: str, message: str) -> None:
        super().__init__(message)
        self.tag = tag
        self.message = message


def need(cond: bool, tag: str, message: str) -> None:
    if not cond:
        raise Refused(tag, message)


# --------------------------------------------------------------------------------------- NVML glue

def _load_nvml() -> ctypes.CDLL:
    if platform.system() == 'Windows':
        sysroot = os.environ.get('SystemRoot', r'C:\Windows')
        candidates = [os.path.join(sysroot, 'System32', 'nvml.dll'),
                      r'C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll',
                      'nvml.dll']
    else:
        candidates = ['libnvidia-ml.so.1', 'libnvidia-ml.so']

    lib = None
    last = None
    for cand in candidates:
        try:
            lib = ctypes.CDLL(cand)
            break
        except OSError as exc:
            last = '%s: %s' % (cand, exc)
    if lib is None:
        raise Refused('nvml_absent', 'no NVML library could be loaded (last: %s)' % last)

    def bind(name, argtypes, restype=ctypes.c_int):
        try:
            fn = getattr(lib, name)
        except AttributeError:
            raise Refused('nvml_symbol_missing', 'NVML is loaded but does not export %s' % name)
        fn.argtypes = argtypes
        fn.restype = restype
        return fn

    lib.f_init = bind('nvmlInit_v2', [])
    lib.f_shutdown = bind('nvmlShutdown', [])
    lib.f_handle = bind('nvmlDeviceGetHandleByIndex_v2', [c_uint, POINTER(c_void_p)])
    lib.f_uuid = bind('nvmlDeviceGetUUID', [c_void_p, c_char_p, c_uint])
    lib.f_name = bind('nvmlDeviceGetName', [c_void_p, c_char_p, c_uint])
    lib.f_driver = bind('nvmlSystemGetDriverVersion', [c_char_p, c_uint])
    lib.f_nvmlver = bind('nvmlSystemGetNVMLVersion', [c_char_p, c_uint])
    lib.f_energy = bind('nvmlDeviceGetTotalEnergyConsumption', [c_void_p, POINTER(c_ulonglong)])
    lib.f_power = bind('nvmlDeviceGetPowerUsage', [c_void_p, POINTER(c_uint)])
    lib.f_enforced = bind('nvmlDeviceGetEnforcedPowerLimit', [c_void_p, POINTER(c_uint)])
    lib.f_errstr = bind('nvmlErrorString', [ctypes.c_int], c_char_p)
    return lib


def _errstr(lib, code: int) -> str:
    try:
        return (lib.f_errstr(code) or b'').decode('utf-8', 'replace')
    except Exception:
        return ''


def _check(lib, code: int, call: str, tag: str = 'nvml_call_failed') -> None:
    if code == NVML_SUCCESS:
        return
    detail = _errstr(lib, code)
    if code == NVML_ERROR_NOT_SUPPORTED:
        raise Refused('counter_unsupported',
                      '%s returned NVML_ERROR_NOT_SUPPORTED (%s); this device does not implement it, '
                      'and an unsupported reading is a refusal rather than a zero' % (call, detail))
    raise Refused(tag, '%s returned NVML code %d (%s)' % (call, code, detail))


def _str_call(lib, fn, call_name, *args) -> str:
    buf = create_string_buffer(BUF)
    _check(lib, fn(*(args + (buf, c_uint(BUF)))), call_name)
    return buf.value.decode('utf-8', 'replace')


def sample_device(device_index: int) -> dict:
    """One fully-checked boundary sample, refusing on a failed nvmlShutdown.

    The shutdown code cannot be raised from the finally clause without masking whatever real
    exception is already in flight, so it is recorded there and adjudicated here, on the success
    path only. Placing the check inside this function rather than at each caller is deliberate:
    the reviewer's finding was that three call sites recorded the code and none refused on it, and
    a per-call-site check is the same defect waiting for a fourth call site.
    """
    sample = _sample_device_inner(device_index)
    code = sample_device.last_shutdown_code
    if code not in (NVML_SUCCESS,):
        raise Refused('nvml_shutdown_failed',
                      'nvmlShutdown returned %r after an otherwise complete sample; the library was '
                      'left in an unknown state, so the reading it produced is not offered as a '
                      'measurement' % (code,))
    return sample


def _sample_device_inner(device_index: int) -> dict:
    lib = _load_nvml()
    _check(lib, lib.f_init(), 'nvmlInit_v2', 'nvml_init_failed')
    shutdown_code = None
    try:
        handle = c_void_p()
        _check(lib, lib.f_handle(c_uint(device_index), byref(handle)),
               'nvmlDeviceGetHandleByIndex_v2')

        uuid = _str_call(lib, lib.f_uuid, 'nvmlDeviceGetUUID', handle)
        name = _str_call(lib, lib.f_name, 'nvmlDeviceGetName', handle)
        driver = _str_call(lib, lib.f_driver, 'nvmlSystemGetDriverVersion')
        nvmlver = _str_call(lib, lib.f_nvmlver, 'nvmlSystemGetNVMLVersion')

        enforced = c_uint()
        code = lib.f_enforced(handle, byref(enforced))
        if code != NVML_SUCCESS:
            raise Refused('power_limit_unavailable',
                          'nvmlDeviceGetEnforcedPowerLimit returned %d (%s); without the enforced '
                          'limit the one physical check available from two points cannot run'
                          % (code, _errstr(lib, code)))

        energy = c_ulonglong()
        power = c_uint()
        t_mono_before = time.monotonic_ns()
        _check(lib, lib.f_energy(handle, byref(energy)), 'nvmlDeviceGetTotalEnergyConsumption')
        t_mono_after = time.monotonic_ns()
        t_wall = time.time()
        power_ok = lib.f_power(handle, byref(power)) == NVML_SUCCESS

        return {
            'device_index': device_index,
            'device_uuid': uuid,
            'device_name': name,
            'driver_version': driver,
            'nvml_version': nvmlver,
            'enforced_power_limit_mw': int(enforced.value),
            'energy_mj': int(energy.value),
            'read_monotonic_ns_before': t_mono_before,
            'read_monotonic_ns_after': t_mono_after,
            'read_wall_unix': t_wall,
            'read_cost_ns': t_mono_after - t_mono_before,
            'instantaneous_power_mw': int(power.value) if power_ok else None,
            'instantaneous_power_qualifies_nothing': True,
        }
    finally:
        try:
            shutdown_code = lib.f_shutdown()
        except Exception:
            shutdown_code = -1
        # recorded through a module-level slot so the finally clause never masks the real exception
        sample_device.last_shutdown_code = shutdown_code


sample_device.last_shutdown_code = None


# ------------------------------------------------------------------------------------- receipt I/O

def write_receipt(path: str, payload: dict) -> None:
    """Write once, never over: a receipt writer that silently reuses a path produced a false green on
    this campaign already, where five distinct refusal cases all printed the first case's text."""
    if os.path.exists(path):
        raise Refused('out_exists',
                      'refused to overwrite an existing receipt at %s; give each invocation a fresh '
                      '--out, because a stale receipt read as a fresh one is the false green this '
                      'refusal exists to prevent' % path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        raise Refused('out_dir_absent', 'receipt directory does not exist: %s' % parent)
    blob = json.dumps(payload, indent=2, sort_keys=True).encode('utf-8')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0))
    except OSError as exc:
        raise Refused('out_unwritable', 'could not create %s: %s' % (path, exc))
    try:
        os.write(fd, blob)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_receipt(path: str) -> dict:
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError as exc:
        raise Refused('begin_receipt_unreadable', 'could not read %s: %s' % (path, exc))
    try:
        doc = json.loads(raw.decode('utf-8'))
    except Exception as exc:
        raise Refused('begin_receipt_unreadable', 'could not parse %s: %s' % (path, exc))
    if not isinstance(doc, dict):
        raise Refused('begin_receipt_unreadable', '%s does not hold a JSON object' % path)
    doc['_self_sha256'] = hashlib.sha256(raw).hexdigest()
    return doc


def field(doc: dict, key: str, where: str):
    if key not in doc:
        raise Refused('begin_receipt_malformed',
                      'the %s is missing %r; a missing field is a refusal, never a default'
                      % (where, key))
    return doc[key]


def self_sha256() -> str:
    with open(os.path.abspath(__file__), 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def base_record(verb: str) -> dict:
    return {
        'schema': SCHEMA,
        'revision': REVISION,
        'verb': verb,
        'producer': os.path.basename(__file__),
        'producer_sha256': self_sha256(),
        'host': platform.node(),
        'python': sys.version.split()[0],
        'written_wall_unix': time.time(),
    }


def emit_refusal(out: str, verb: str, exc: Refused, extra: dict) -> int:
    rec = base_record(verb)
    rec.update(extra)
    rec['verdict'] = 'REFUSED'
    rec['refusal_tag'] = exc.tag
    rec['refusal'] = exc.message
    rec['nvml_shutdown_code'] = sample_device.last_shutdown_code
    try:
        write_receipt(out, rec)
        print('receipt: %s' % out, file=sys.stderr)
    except Refused as inner:
        # The receipt itself could not be written. Say both things; never exit silently.
        print('REFUSED [%s] %s' % (inner.tag, inner.message), file=sys.stderr)
    print('REFUSED [%s] %s' % (exc.tag, exc.message), file=sys.stderr)
    return 3


def guarded(fn, out: str, verb: str, extra_fn) -> int:
    """Every exit writes a receipt. An unexpected exception becomes a named internal_error refusal
    rather than a traceback, because a traceback is the one outcome that leaves no durable statement."""
    try:
        return fn()
    except Refused as exc:
        return emit_refusal(out, verb, exc, extra_fn())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - deliberate: nothing may escape without a receipt
        return emit_refusal(out, verb,
                            Refused('internal_error', '%s: %s' % (type(exc).__name__, exc)),
                            extra_fn())


# ----------------------------------------------------------------------------------------- the two

def cmd_begin(args) -> int:
    binding = {
        'run_id': args.run_id,
        'custody': os.path.abspath(args.custody),
        'device_index': args.device_index,
        'boundary_source': args.boundary_source,
    }

    def body():
        need(bool(RUN_ID_RE.match(args.run_id)), 'run_id_shape',
             'run id must be 32 lowercase hex characters, got %r' % args.run_id)
        need(os.path.isdir(args.custody), 'custody_absent',
             'custody root does not exist: %s' % args.custody)
        sample = sample_device(args.device_index)

        rec = base_record('begin')
        rec['binding'] = binding
        rec['sample'] = sample
        rec['nvml_shutdown_code'] = sample_device.last_shutdown_code
        rec['verdict'] = 'SAMPLED'
        rec['note'] = ('the total-energy counter is monotonic since driver load, so this value is a '
                       'cursor and not an energy; only its difference against a matching end sample is')
        write_receipt(args.out, rec)
        print('SAMPLED begin: counter %d mJ on %s (%s), driver %s, NVML %s, enforced limit %.1f W'
              % (sample['energy_mj'], sample['device_name'], sample['device_uuid'],
                 sample['driver_version'], sample['nvml_version'],
                 sample['enforced_power_limit_mw'] / 1000.0))
        print('receipt: %s' % args.out)
        return 0

    return guarded(body, args.out, 'begin', lambda: {'binding': binding})


def cmd_end(args) -> int:
    ctx = {'begin_receipt': os.path.abspath(args.begin)}

    def body():
        begin = read_receipt(args.begin)
        ctx['begin_receipt_sha256'] = begin['_self_sha256']
        need(begin.get('schema') == SCHEMA and begin.get('verb') == 'begin',
             'begin_receipt_wrong_kind', 'the --begin path is not a begin receipt of %s' % SCHEMA)
        need(begin.get('verdict') == 'SAMPLED', 'begin_receipt_not_sampled',
             'the begin receipt records %r, so there is no opening sample to difference'
             % begin.get('verdict'))
        need(begin.get('producer_sha256') == self_sha256(), 'producer_mismatch',
             'the begin sample was taken by a different build of this collector (%s) than the one '
             'closing it (%s); the two ends must be one instrument'
             % (begin.get('producer_sha256'), self_sha256()))

        b = field(begin, 'sample', 'begin receipt')
        binding = field(begin, 'binding', 'begin receipt')
        need(isinstance(b, dict) and isinstance(binding, dict), 'begin_receipt_malformed',
             'the begin receipt\'s sample or binding is not an object')
        for k in ('device_uuid', 'driver_version', 'nvml_version', 'energy_mj',
                  'read_monotonic_ns_after', 'read_wall_unix', 'enforced_power_limit_mw'):
            field(b, k, 'begin sample')
        ctx['binding'] = binding

        mode = binding.get('boundary_source')
        need(mode in ('worker', 'external'), 'begin_receipt_malformed',
             'the begin receipt declares boundary_source %r, which is neither worker nor external'
             % mode)

        end = sample_device(int(field(binding, 'device_index', 'begin binding')))

        need(end['device_uuid'] == b['device_uuid'], 'device_changed',
             'begin sampled %s and end sampled %s; a difference across two devices is not an energy'
             % (b['device_uuid'], end['device_uuid']))
        need(end['driver_version'] == b['driver_version'], 'driver_changed',
             'driver moved from %s to %s between the samples; the counter origin moved with it'
             % (b['driver_version'], end['driver_version']))
        need(end['nvml_version'] == b['nvml_version'], 'nvml_version_changed',
             'NVML moved from %s to %s between the samples' % (b['nvml_version'], end['nvml_version']))
        need(end['energy_mj'] >= b['energy_mj'], 'counter_reset',
             'end counter %d mJ is below begin counter %d mJ, so the counter reset (driver reload) '
             'and the interval does not exist' % (end['energy_mj'], b['energy_mj']))

        measured_ns = end['read_monotonic_ns_before'] - b['read_monotonic_ns_after']
        need(measured_ns > 0, 'non_positive_interval',
             'the measured monotonic interval is %d ns; the end sample does not follow the begin '
             'sample' % measured_ns)
        measured_s = measured_ns / 1e9

        delta_mj = end['energy_mj'] - b['energy_mj']
        joules = delta_mj / 1000.0
        avg_w = joules / measured_s

        # The one physical check two points can support.
        enforced_w = min(b['enforced_power_limit_mw'], end['enforced_power_limit_mw']) / 1000.0
        need(avg_w <= enforced_w, 'average_power_above_enforced_limit',
             'average power %.2f W over the measured interval exceeds the enforced limit %.2f W, '
             'which is physically impossible; the counter, the interval, or the device binding is '
             'wrong' % (avg_w, enforced_w))

        coverage = {'boundary_source': mode}
        if mode == 'external':
            need(args.hour_start_unix is not None and args.hour_end_unix is not None,
                 'hour_interval_missing',
                 'external boundary source requires --hour-start-unix and --hour-end-unix from the '
                 'hour\'s own receipt; this collector does not invent an interval')
            h0, h1 = float(args.hour_start_unix), float(args.hour_end_unix)
            need(h1 > h0, 'hour_interval_shape',
                 'the hour interval [%r, %r] is not increasing' % (h0, h1))
            lead = h0 - b['read_wall_unix']
            trail = end['read_wall_unix'] - h1
            need(lead >= 0 and trail >= 0, 'interval_not_covered',
                 'the energy window [%.3f, %.3f] does not contain the hour [%.3f, %.3f] (lead %.3f s, '
                 'trail %.3f s); a window that misses part of the hour under-reports it'
                 % (b['read_wall_unix'], end['read_wall_unix'], h0, h1, lead, trail))
            slack = lead + trail
            need(slack <= args.max_slack_seconds, 'interval_slack_exceeded',
                 'the energy window exceeds the hour by %.3f s (lead %.3f, trail %.3f), above the '
                 '%.3f s bound; energy drawn outside the hour would be reported as the hour\'s'
                 % (slack, lead, trail, args.max_slack_seconds))
            coverage.update({'hour_start_unix': h0, 'hour_end_unix': h1,
                             'hour_duration_s': h1 - h0, 'energy_lead_s': lead,
                             'energy_trail_s': trail, 'energy_slack_s': slack,
                             'max_slack_seconds': args.max_slack_seconds,
                             'basis': 'the hour interval was supplied by the caller from the hour '
                                      'receipt and the energy window was proved to contain it'})
        else:
            need(bool(args.placement_evidence and args.placement_evidence.strip()),
                 'placement_evidence_missing',
                 'worker boundary source requires --placement-evidence stating how the two samples '
                 'were placed at the hour\'s first and last update boundary; without it the coverage '
                 'claim has no support')
            coverage.update({'placement_evidence': args.placement_evidence.strip(),
                             'energy_slack_s': 0.0,
                             'basis': 'the samples ARE the hour boundary, so the measured interval '
                                      'defines the window rather than being compared to one; the '
                                      'coverage claim rests entirely on the placement evidence above, '
                                      'which this collector records and cannot verify'})

        rec = base_record('end')
        rec['binding'] = binding
        rec['begin_receipt'] = ctx['begin_receipt']
        rec['begin_receipt_sha256'] = ctx['begin_receipt_sha256']
        rec['begin_sample'] = b
        rec['end_sample'] = end
        rec['nvml_shutdown_code'] = sample_device.last_shutdown_code
        rec['coverage'] = coverage
        rec['measurement'] = {
            'energy_delta_mj': delta_mj,
            'energy_joules': joules,
            'energy_wh': joules / 3600.0,
            'measured_interval_s': measured_s,
            'measured_interval_basis': 'monotonic_ns difference between the two counter reads',
            'average_power_w': avg_w,
            'enforced_power_limit_w': enforced_w,
            'checked': ['average_power_w <= enforced_power_limit_w'],
            'recorded_but_qualifying_nothing': {
                'endpoint_instantaneous_power_w': {
                    'begin': (b['instantaneous_power_mw'] / 1000.0)
                             if b.get('instantaneous_power_mw') is not None else None,
                    'end': (end['instantaneous_power_mw'] / 1000.0)
                           if end.get('instantaneous_power_mw') is not None else None,
                },
                'why': 'a real hour varies between its endpoints, so the average lying outside the '
                       'endpoint bracket is information for the reader and not a defect; these two '
                       'readings were NOT used to qualify the verdict and must not be reported as '
                       'though they had been',
            },
        }
        rec['verdict'] = 'MEASURED'
        rec['claim_boundary'] = (
            'Device total energy over an interval whose relation to the governed hour is stated in '
            'coverage.basis above. It is the whole board\'s draw, not the training process\'s, and it '
            'includes whatever else used the device inside the window. Not a per-token or per-update '
            'energy, and not terminal acceptance of anything.'
        )
        write_receipt(args.out, rec)
        print('MEASURED %.3f J (%.4f Wh) over %.3f s measured, average %.2f W against an enforced '
              'limit of %.2f W' % (joules, joules / 3600.0, measured_s, avg_w, enforced_w))
        print('coverage: %s' % coverage['basis'])
        print('receipt: %s' % args.out)
        return 0

    return guarded(body, args.out, 'end', lambda: dict(ctx))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Boundary energy collector for the #1945 governed hour.')
    sub = ap.add_subparsers(dest='verb', required=True)

    b = sub.add_parser('begin')
    b.add_argument('--run-id', required=True)
    b.add_argument('--custody', required=True)
    b.add_argument('--device-index', type=int, default=0)
    b.add_argument('--boundary-source', required=True, choices=('worker', 'external'),
                   help='worker: these samples ARE the hour boundary. external: the caller supplies '
                        'the hour interval at end and containment is proved.')
    b.add_argument('--out', required=True)
    b.set_defaults(func=cmd_begin)

    e = sub.add_parser('end')
    e.add_argument('--begin', required=True)
    e.add_argument('--hour-start-unix', type=float, default=None, help='external mode only')
    e.add_argument('--hour-end-unix', type=float, default=None, help='external mode only')
    e.add_argument('--max-slack-seconds', type=float, default=60.0, help='external mode only')
    e.add_argument('--placement-evidence', default=None,
                   help='worker mode only: how the two samples were placed at the first and last '
                        'update boundary. Recorded verbatim; this collector cannot verify it.')
    e.add_argument('--out', required=True)
    e.set_defaults(func=cmd_end)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
