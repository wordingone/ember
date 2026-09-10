from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                     / 'src/ember/infrastructure/tools/ember-restart-3b'))
"""Opt-in full-population CUDA conformance, never trained capability or throughput.

Revision CIA3-R1-N61-numerical-split-v1. The preceding revision asserted exact free-route equality
across backends and failed on one of 60 selections, which told us the winners differed and nothing
about why. This revision separates the three questions that failure fused together:

  1. MEASURED FREE ROUTING -- both backends select freely, and every corresponding selection is
     compared on its shared vector, its candidate pair, and its two signed scores.
  2. SELECTOR ISOLATION -- every recorded selector input is evaluated on both backends. Identical
     inputs must give identical candidate and winner identities. Agreement here while the free runs
     disagree places the divergence upstream of the selector.
  3. FIXED-PLAN CONSUMPTION -- CUDA consumes the complete CPU route plan, so the logit and gradient
     comparisons are made on one plan rather than on two. Exact route equality in that computation
     establishes consumption of the control only; it can never substitute for step 1.

Then two optimizer updates: an excluded warmup at learning rate 0.0 that allocates the moments and
must leave every selected parameter's bytes untouched, and one measured update at 0.001 that must
allocate no new optimizer state. Zero applied-training, admitted-token, throughput, paging,
recovery, checkpoint or qualification credit is claimed by any of it.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import os
import sys
import time
import unittest
import torch
import checkpoint_artifacts as artifacts
from ember.model.ember_v0_decoder import CIADecoder
from ember.model.ember_v0_routing import GlobalObservation, LocalObservation, _local_scores
from ember.governance.scripts.cia_conformance import fixed_input_values, require_current_dispatch
from ember.governance.scripts.cia_numerical_split import (
    FIXED_PLAN_LOGIT_ATOL, FIXED_PLAN_LOGIT_RTOL, GRADIENT_RELATIVE_L2_MAX, LOCAL_ROUTES, REVISION,
    compare_global_selections, compare_local_routes, cross_evaluate_selector, digest_of,
    local_route_report, refuse_if_inadmissible, route_plan)

LIVE = '--live' in sys.argv
if LIVE:
    sys.argv.remove('--live')
REQUESTED = os.environ.get('EMBER_CIA_CUDA_CONFORMANCE') == '1'
if REQUESTED and (not LIVE or os.environ.get('EMBER_GATE_AUTHORIZED') != '1'):
    raise RuntimeError('full CUDA conformance requires --live and existing launch authorization')

WARMUP_LEARNING_RATE = 0.0
MEASURED_LEARNING_RATE = 0.001
GRADIENT_NAMES = ('layers.0.attention.q.weight', 'router.global_query.weight',
                  'router.local_query.weight')


class Collector:
    """Accumulates what the selector computed, separated by kind."""

    def __init__(self):
        self.local = []
        self.globals = []

    def __call__(self, observation):
        if type(observation) is LocalObservation:
            self.local.append(observation)
        elif type(observation) is GlobalObservation:
            self.globals.append(observation)
        else:
            raise ValueError(f'unexpected observation type {type(observation)!r}')


def optimizer_state_identity(optimizer, parameters):
    """Which state tensors exist and where they live.

    Both halves matter. A new key means state was allocated; a moved data pointer means the state
    was reallocated under the same key, which is the same failure wearing the old name.
    """
    identity = {}
    for name, parameter in parameters.items():
        state = optimizer.state.get(parameter)
        if not state:
            continue
        identity[name] = {key: (tuple(value.shape), value.data_ptr())
                          for key, value in state.items() if torch.is_tensor(value)}
    return identity


@unittest.skipUnless(REQUESTED, 'requires owned full-population CUDA resource window')
class FullPopulationCUDA(unittest.TestCase):
    def test_free_route_measurement_selector_isolation_and_fixed_plan_update(self):
        binding = json.loads(Path(os.environ["EMBER_CIA_SUBJECT_BINDING"]).read_text(encoding="utf-8"))
        require_current_dispatch(Path(__file__).resolve().parents[1], binding)
        torch.set_num_threads(1)
        self.assertTrue(torch.cuda.is_available(), 'CUDA unavailable in governed runtime')
        device = torch.device('cuda:0')
        total = torch.cuda.get_device_properties(device).total_memory
        limit = int(os.environ['EMBER_CIA_GPU_MAX_BYTES'])
        self.assertGreater(limit, 0)
        self.assertLess(limit, total)
        torch.cuda.set_per_process_memory_fraction(limit / total, device)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        started = time.perf_counter()
        print('CIA_CUDA_PHASE', {'revision': REVISION, 'phase': 'materialize_cpu',
                                 'elapsed_seconds': 0}, flush=True)
        config_path = Path(__file__).resolve().parents[1] / "configs/ember-cia-3b.json"
        architecture_config = json.loads(config_path.read_text(encoding="utf-8"))
        model = CIADecoder(architecture_config=architecture_config).materialize_cpu(seed=2163)
        parameters = model.parameter_inventory()
        self.assertEqual(sum(value.numel() for value in parameters.values()), 3082539008)
        print('CIA_CUDA_PHASE', {'phase': 'cpu_reference', 'unique_parameters': 3082539008,
              'elapsed_seconds': time.perf_counter() - started}, flush=True)

        # ---- 1. CPU reference: free routing, observed --------------------------------------
        token_values, position_values = fixed_input_values()
        tokens = torch.tensor(token_values, dtype=torch.long)
        positions = torch.tensor(position_values, dtype=torch.long)
        cpu_observed = Collector()
        cpu_logits, cpu_routes = model(model.embed_text(tokens), positions, return_routes=True,
                                       route_observer=cpu_observed)
        self.assertEqual(len(cpu_observed.local), LOCAL_ROUTES)
        experts = tuple(sorted({row[-1] for row in cpu_routes}))
        self.assertGreater(len(experts), 2, 'fixture must exercise eviction beyond two global experts')
        loss = cpu_logits[:, :64].float().square().mean()
        loss.backward()
        last_layer_expert = next(row[-1] for row in reversed(cpu_routes) if row[1] == 23)
        names = GRADIENT_NAMES + (f'experts.{last_layer_expert}.layers.23.up.weight',)
        reference_gradients = {}
        for name in names:
            self.assertIsNotNone(parameters[name].grad, name)
            self.assertTrue(torch.isfinite(parameters[name].grad).all(), name)
            self.assertGreater(float(parameters[name].grad.float().abs().sum()), 0, name)
            reference_gradients[name] = parameters[name].grad.detach().clone()
        reference_logits = cpu_logits.detach()
        # The host copy of the selector projection has to be taken BEFORE the model moves, because
        # cross-evaluating a CUDA-recorded input on CPU needs a CPU parameter to evaluate it with,
        # and after activation there is no longer one.
        host_selector_projection = parameters['router.local_query.weight'].detach().cpu().clone()
        del loss, cpu_logits
        for value in parameters.values():
            value.grad = None
        print('CIA_CUDA_PHASE', {'phase': 'activate_cuda', 'visited_experts': experts,
              'observed_local_routes': len(cpu_observed.local),
              'observed_global_selections': len(cpu_observed.globals),
              'elapsed_seconds': time.perf_counter() - started}, flush=True)
        model.activate_cuda(device)
        parameters = model.parameter_inventory()
        tokens = tokens.to(device)
        positions = positions.to(device)
        torch.cuda.reset_peak_memory_stats(device)

        # ---- 2. CUDA free routing, measured against the CPU reference ----------------------
        # No gradients here, and the reason is the residency contract rather than economy. A paged
        # expert forward that will need a gradient registers a debt on the step, and the step
        # refuses to close while any debt is outstanding -- because an expert whose backward never
        # ran while grads were live is an expert whose weights the cache may already have evicted.
        # This section measures routing decisions and logits, never gradients, so running it with
        # grad enabled would register debts that nothing in the section could ever pay, and the
        # step would refuse on a defect of the measurement rather than of the subject. Gradients
        # are measured in section 4, against the fixed plan, where the backward actually runs.
        # Autograd does not change forward arithmetic, so the comparison against the CPU reference
        # is unaffected by the mode.
        cuda_observed = Collector()
        with torch.no_grad(), model.candidate_step():
            free_logits, free_routes = model(model.embed_text(tokens), positions,
                                             return_routes=True, route_observer=cuda_observed)
        free_logits = free_logits.detach().cpu()
        self.assertEqual(len(cuda_observed.local), LOCAL_ROUTES)
        global_rows = compare_global_selections(cpu_observed.globals, cuda_observed.globals)
        comparisons = compare_local_routes(cpu_observed.local, cuda_observed.local)
        report = local_route_report(comparisons)
        report['global_selections'] = list(global_rows)
        report['free_logit_max_absolute_delta'] = float(
            (free_logits.float() - reference_logits.float()).abs().max())
        # Reported BEFORE the admissibility refusal, so a failing run publishes its measurement
        # instead of only its verdict. A refused run whose numbers never reached the log is a run
        # that has to be spent again to learn anything.
        print('CIA_FREE_ROUTE_MEASUREMENT', json.dumps(report), flush=True)
        # The admissibility refusal is deferred to the end of the method, deliberately. Raising
        # here aborts before sections 3, 4 and 5 ever run, so a single nonconforming route costs
        # the selector isolation, the fixed-plan gradient comparison and the measured update --
        # three obligations that the route in question does not bear on. Nothing inadmissible is
        # admitted by the move: the same comparisons are refused at the same bounds, after every
        # section has published what it was able to measure.

        # ---- 3. Selector isolation on identical inputs -------------------------------------
        cross = cross_evaluate_selector(
            tuple(cpu_observed.local) + tuple(cuda_observed.local),
            {'cpu': host_selector_projection, 'cuda': parameters['router.local_query.weight']},
            _local_scores)
        print('CIA_SELECTOR_CROSS_EVALUATION', json.dumps(
            {key: value for key, value in cross.items() if key != 'evaluations'}), flush=True)

        # ---- 4. Fixed-plan CUDA computation ------------------------------------------------
        # The numerical comparisons here are measured and collected rather than asserted in place,
        # for the reason the section-2 refusal is deferred: an assertion aborts the method, so a
        # logit difference would cost the gradient comparison -- the only measurement in this unit
        # that exercises the paged expert backward against a CPU reference. Bounds are unchanged
        # and every failing condition still fails the test, at the end, after publication.
        # Structural conditions stay as assertions: a plan that did not force its routing, or a
        # nonfinite gradient, makes what follows meaningless rather than merely unmeasured.
        deferred_failures = []
        plan = route_plan(cpu_observed.local)
        with model.candidate_step():
            planned_logits, planned_routes = model(model.embed_text(tokens), positions,
                                                   return_routes=True, route_plan=plan)
            # Equality here is consumption of the control, never a free-route result: the winners
            # came from the plan. The free comparison above is the only routing measurement.
            self.assertEqual(planned_routes, cpu_routes)
            planned_cpu = planned_logits.detach().cpu().float()
            expected_logits = reference_logits.float()
            logit_delta = (planned_cpu - expected_logits).abs()
            logit_max_absolute = float(logit_delta.max())
            # The same tolerance assert_close applies, evaluated elementwise so the COUNT of
            # exceeding elements is reported and not only the largest one's magnitude. Twenty-four
            # elements and three million elements are different findings about the same maximum.
            allowed = FIXED_PLAN_LOGIT_ATOL + FIXED_PLAN_LOGIT_RTOL * expected_logits.abs()
            exceeding = int((logit_delta > allowed).sum())
            compared = int(expected_logits.numel())
            if exceeding:
                deferred_failures.append(
                    'fixed-plan logits: %d of %d elements exceed atol %g + rtol %g; max absolute '
                    'delta %.10g' % (exceeding, compared, FIXED_PLAN_LOGIT_ATOL,
                                     FIXED_PLAN_LOGIT_RTOL, logit_max_absolute))
            del planned_cpu, expected_logits, logit_delta, allowed
            planned_logits[:, :64].float().square().mean().backward()
        gradient_rows = {}
        for name, expected in reference_gradients.items():
            actual = parameters[name].grad.cpu()
            self.assertTrue(torch.isfinite(actual).all(), name)
            self.assertGreater(float(actual.float().abs().sum()), 0, name)
            relative_error = float((actual.float() - expected.float()).norm() / expected.float().norm())
            gradient_rows[name] = relative_error
            if not relative_error < GRADIENT_RELATIVE_L2_MAX:
                deferred_failures.append(
                    'fixed-plan gradient %s: relative L2 %.10g exceeds %g'
                    % (name, relative_error, GRADIENT_RELATIVE_L2_MAX))
        self.assertLessEqual(model._cuda_execution.cache.peak_resident_bundles, 2)
        self.assertEqual(model._cuda_execution.cache.resident_count, 0)
        print('CIA_FIXED_PLAN', json.dumps({'plan_entries': len(plan),
              'logit_max_absolute_delta': logit_max_absolute,
              'logit_elements_exceeding_tolerance': exceeding,
              'logit_elements_compared': compared,
              'logit_atol': FIXED_PLAN_LOGIT_ATOL, 'logit_rtol': FIXED_PLAN_LOGIT_RTOL,
              'gradient_relative_l2': gradient_rows, 'bound': GRADIENT_RELATIVE_L2_MAX,
              'deferred_failures': list(deferred_failures),
              'elapsed_seconds': time.perf_counter() - started}), flush=True)
        del planned_logits, free_logits, reference_logits, reference_gradients

        # ---- 5. Excluded warmup, then one measured update ----------------------------------
        model.apply_update_support('core+expert-set', experts=experts)
        # Membership is the COMPLETE inventory; the update support is expressed by requires_grad,
        # not by membership. Building the group over apply_update_support's returned subset -- what
        # this line did through revision N61 -- produces a shape whose state cannot be captured:
        # cia_optimizer_identity refuses `seen != set(names_by_id)`, so the very shape this unit
        # drove the decoder in was uncheckpointable, and section 6 below is what now proves it is
        # not. AdamW skips a member whose .grad is None and allocates no moment for it, so the
        # excluded-warmup and no-reallocation conditions below are unchanged by this.
        optimizer = torch.optim.AdamW(list(parameters.values()), lr=WARMUP_LEARNING_RATE,
                                      foreach=False)
        selected_names = {name for name, value in parameters.items() if value.requires_grad}
        before_warmup = {name: digest_of(parameters[name]) for name in selected_names}
        optimizer.zero_grad(set_to_none=True)
        with model.candidate_step():
            model(model.embed_text(tokens), positions,
                  route_plan=plan)[:, :64].float().square().mean().backward()
        warmup_gradients_finite = all(
            parameters[name].grad is None or bool(torch.isfinite(parameters[name].grad).all())
            for name in selected_names)
        self.assertTrue(warmup_gradients_finite, 'warmup produced a nonfinite gradient')
        optimizer.step()
        torch.cuda.synchronize(device)
        after_warmup = {name: digest_of(parameters[name]) for name in selected_names}
        # A complete byte comparison over every selected parameter, not a sample: the warmup exists
        # to allocate moments and clocks, and any byte it moved would change the inputs that define
        # the plan the measured step is about to consume.
        moved = sorted(name for name in selected_names if before_warmup[name] != after_warmup[name])
        self.assertEqual(moved, [], 'the excluded warmup changed model inputs')
        warmed_state = optimizer_state_identity(optimizer, parameters)
        self.assertTrue(warmed_state, 'warmup allocated no optimizer state')

        for group in optimizer.param_groups:
            group['lr'] = MEASURED_LEARNING_RATE
        changed_name = 'layers.0.attention.q.weight'
        old = parameters[changed_name].detach().cpu().clone()
        inactive = next(expert for expert in range(25) if expert not in experts)
        inactive_name = f'experts.{inactive}.layers.1.up.weight'
        untouched = parameters[inactive_name].detach().clone()
        cache = model._cuda_execution.cache
        dispatch_before = (cache.transfer_seconds, cache.transfer_bytes, cache.lease_count,
                           cache.miss_count, cache.eviction_count)

        reset_started = time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        reset_seconds = time.perf_counter() - reset_started
        update_started = time.perf_counter()
        with model.candidate_step():
            data_started = time.perf_counter()
            embedded = model.embed_text(tokens)
            torch.cuda.synchronize(device)
            data_seconds = time.perf_counter() - data_started
            forward_started = time.perf_counter()
            measured_logits = model(embedded, positions, route_plan=plan)
            objective = measured_logits[:, :64].float().square().mean()
            torch.cuda.synchronize(device)
            forward_seconds = time.perf_counter() - forward_started
            backward_started = time.perf_counter()
            objective.backward()
            torch.cuda.synchronize(device)
            backward_seconds = time.perf_counter() - backward_started
        optimizer_started = time.perf_counter()
        optimizer.step()
        torch.cuda.synchronize(device)
        optimizer_seconds = time.perf_counter() - optimizer_started
        complete_step_seconds = time.perf_counter() - update_started

        accounting_started = time.perf_counter()
        self.assertFalse(torch.equal(parameters[changed_name].detach().cpu(), old))
        self.assertTrue(torch.equal(parameters[inactive_name], untouched))
        self.assertIsNone(parameters[inactive_name].grad)
        measured_state = optimizer_state_identity(optimizer, parameters)
        # Warmed support: the measured update reuses the warmup's moments. A new key, or the same
        # key at a new address, is a reallocation and fails the condition.
        self.assertEqual(measured_state, warmed_state, 'the measured update allocated optimizer state')
        accounting_seconds = time.perf_counter() - accounting_started

        dispatch_after = (cache.transfer_seconds, cache.transfer_bytes, cache.lease_count,
                          cache.miss_count, cache.eviction_count)
        routing_dispatch_seconds = dispatch_after[0] - dispatch_before[0]
        assigned = (data_seconds + forward_seconds + backward_seconds + optimizer_seconds)
        peak = torch.cuda.max_memory_allocated(device)
        # Judged below with the other deferred verdicts: asserting here would suppress the only
        # record of what the measured update cost, which is the reason the section exists.
        if peak > limit:
            deferred_failures.append('measured update peak %d bytes exceeds the %d byte limit'
                                     % (peak, limit))
        # ---- 6. The shape this unit drives must be a shape the checkpoint interface can capture --
        # Through revision N61 this unit reported 'checkpoint: omitted; this unit writes no
        # checkpoint and claims no recovery'. That sentence was true and it concealed a defect:
        # the optimizer was built over the update-support subset, and cia_optimizer_identity refuses
        # membership that does not cover the complete inventory -- so the live consumer's shape was
        # not capturable at all, and nothing here would ever have said so. The two admission gates
        # are called against the real optimizer at the real quiescent boundary, and the moments are
        # captured, so a regression to subset membership fails this unit instead of surfacing at a
        # checkpoint nobody writes here.
        binding_started = time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        quiescent = artifacts._cia_quiescent_parameters(model)
        self.assertEqual(sorted(quiescent), sorted(parameters))
        optimizer_identity = artifacts.cia_optimizer_identity(model, optimizer)
        moment_bytes = sum(value.numel() * value.element_size()
                           for fields in optimizer.state.values() for value in fields.values())
        placed = artifacts.capture_cia_placed_optimizer_state(
            model, optimizer, max_state_bytes=moment_bytes)
        captured_names = sorted(name for name, fields in placed['state'].items() if fields)
        supported_names = {name for name, value in parameters.items() if value.requires_grad}
        # Captured moments are a NON-EMPTY SUBSET of the update support, never an equality: a
        # supported parameter that this fixture never engages -- the modality adapters, for one --
        # receives no gradient, so AdamW allocates it no moment and there is nothing to capture.
        # Measured on this fixture: 425 supported, 375 with moments. What must hold is that nothing
        # OUTSIDE the support was captured, which is the containment below.
        self.assertTrue(captured_names, 'no moments were captured')
        self.assertEqual(sorted(set(captured_names) - supported_names), [],
                         'a parameter outside the update support carried optimizer state')
        binding_seconds = time.perf_counter() - binding_started
        checkpoint_binding = {
            'optimizer_membership': 'complete inventory',
            'inventory_parameters': len(parameters),
            'optimizer_identity_accepted': bool(optimizer_identity),
            'quiescent_cache_admitted': True,
            'placed_state_schema': placed['schema_version'],
            'captured_moment_parameters': len(captured_names),
            'supported_parameters': len(supported_names),
            'supported_without_moments': len(supported_names) - len(captured_names),
            'captured_moment_bytes': moment_bytes,
            'capture_seconds': binding_seconds,
            'boundary': 'this unit proves the driven shape is capturable; it publishes no '
                        'checkpoint artifact and claims no recovery or continuation'}
        del placed

        trainable = sum(value.numel() for value in parameters.values() if value.requires_grad)
        print('CIA_MEASURED_UPDATE', json.dumps({
            'revision': REVISION,
            'learning_rates': {'warmup': WARMUP_LEARNING_RATE, 'measured': MEASURED_LEARNING_RATE},
            'complete_step_seconds': complete_step_seconds,
            'data_seconds': data_seconds, 'exclusive_forward_seconds': forward_seconds,
            'backward_seconds': backward_seconds, 'optimizer_seconds': optimizer_seconds,
            'gradient_reset_seconds': reset_seconds, 'accounting_seconds': accounting_seconds,
            'routing_dispatch_seconds': routing_dispatch_seconds,
            'routing_dispatch_included_in': 'exclusive_forward_seconds',
            'unassigned_residual_seconds': complete_step_seconds - assigned,
            'host_to_device_bytes': dispatch_after[1] - dispatch_before[1],
            'expert_leases': dispatch_after[2] - dispatch_before[2],
            'expert_bundle_fetches': dispatch_after[3] - dispatch_before[3],
            'expert_evictions': dispatch_after[4] - dispatch_before[4],
            'synchronization_observer_cost': 'included in every phase above',
            'checkpoint_binding': checkpoint_binding,
            'sequence_length': len(token_values), 'microbatch': 1,
            'allocated_parameters': 3082539008, 'trainable_parameters': trainable,
            'active_experts': list(experts),
            'numerical_positions_per_second': len(token_values) / complete_step_seconds,
            'gpu_peak_allocated_bytes': peak,
            'gpu_peak_reserved_bytes': torch.cuda.max_memory_reserved(device),
            'gpu_limit_bytes': limit, 'memory_scope':
                'PyTorch allocator only; external total-device supervision required',
            'total_seconds': time.perf_counter() - started,
            'claim': 'fixed-data numerical control and update mechanics only; '
                     'zero admitted-training, throughput or qualification credit'}), flush=True)
        print('CIA_CUDA_CONFORMANCE', json.dumps({
            'revision': REVISION, 'unique_parameters': 3082539008,
            'local_routes_measured_per_backend': LOCAL_ROUTES,
            'differing_free_routes': report['differing_routes'],
            'max_shared_vector_relative_l2': report['max_shared_vector_relative_l2'],
            'max_absolute_selector_score_error': cross['max_absolute_selector_score_error'],
            'selector_parameter_sha256': cross['parameter_sha256'],
            'host_selector_projection_sha256': digest_of(host_selector_projection),
            'inadmissible_local_routes': report['inadmissible_routes'],
            'admissible': report['inadmissible_routes'] == 0,
            'claim': 'fixed-data correctness and update mechanics only'}), flush=True)

        # Deferred from sections 2, 4 and 5. A refused run is still a refused run; it has simply
        # reported every measurement it could reach first, and the tag above carries its own
        # verdict so a consumer cannot mistake a published measurement for a conforming one.
        # Both findings publish before either is raised, so a run never reports one nonconformance
        # while silently holding another.
        print('CIA_DEFERRED_VERDICTS', json.dumps({
            'revision': REVISION,
            'inadmissible_local_routes': report['inadmissible_routes'],
            'local_route_reasons': [row['reason'] for row in report['routes']
                                    if not row['admissible']],
            'fixed_plan_and_update_failures': list(deferred_failures)}), flush=True)
        refuse_if_inadmissible(comparisons)
        if deferred_failures:
            self.fail('; '.join(deferred_failures))


if __name__ == '__main__':
    unittest.main()
