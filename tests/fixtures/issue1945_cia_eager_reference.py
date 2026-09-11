# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Frozen pre-segmentation resident forward; dense/expert fixtures exercise boundary and gradient preservation."""
import torch

def resident_eager_reference(self, documents, *, collector=None, plan=None):
    from ember.model.ember_v0_residency import resident_global_routes, resident_local_routes, ResidentRouteTrace
    execution = self._cuda_execution
    execution.check()
    execution.check_route_plan(plan)
    lengths = tuple(len(embedded) for embedded, _, _ in documents)
    embedded = torch.cat([item[0] for item in documents])
    positions = torch.cat([item[1] for item in documents])
    keys = torch.stack([self._weight(f'router.layers.{layer}.keys') for layer in range(1, 24, 2)])
    geometry, priors, ranked, candidates, valid = resident_global_routes(
        embedded, lengths, self._weight('router.global_query.weight'), keys)
    execution.require_valid(valid, 'routing')
    if collector is not None:
        collector('global', dict(geometry=geometry, priors=priors.detach().clone(),
                                ranked=ranked.detach().clone(), candidates=candidates.detach().clone()))
    sizes = tuple(row[3] for row in geometry.chunks)
    equal = len(set(sizes)) == 1
    # Ragged geometry is fixed for a capture. Prepare its row mapping once outside
    # the captured forward through ResidentExecution.bind_geometry.
    repeats = execution.geometry_repeats(lengths, sizes)
    values, winners_by_layer = embedded, []
    for layer in range(24):
        prefix = f'layers.{layer}'
        values = values + self._batched_attention(
            self._norm(values, prefix + '.attention_norm.weight'), positions, lengths, prefix + '.attention')
        shared = values + self._swiglu(self._norm(values, prefix + '.shared_norm.weight'), prefix + '.shared')
        if layer % 2 == 0:
            values = shared
            continue
        winners, logits, gates, valid = resident_local_routes(
            shared, self._weight('router.local_query.weight'), keys, layer // 2,
            geometry, priors, candidates)
        execution.require_valid(valid, 'routing')
        native_winners = winners
        winners, gates = execution.planned_routes(layer//2, geometry, candidates, winners, logits, gates)
        if equal:
            row_experts = winners.repeat_interleave(sizes[0])
            row_gates = gates.repeat_interleave(sizes[0])
        else:
            row_experts = torch.repeat_interleave(winners, repeats, output_size=len(embedded))
            row_gates = torch.repeat_interleave(gates, repeats, output_size=len(embedded))
        residual = execution.grouped_block(self._norm(shared, prefix + '.expert_norm.weight'), row_experts, layer)
        values = shared + residual * row_gates[:, None].to(residual.dtype)
        winners_by_layer.append(winners.detach())
        if collector is not None:
            collector('local', dict(layer=layer, winners=winners.detach().clone(), logits=logits.detach().clone(),
                                   gates=gates.detach().clone(), valid=valid.detach().clone(), native_winners=native_winners.detach().clone()))
    outputs = self._linear(self._norm(values, 'final_norm.weight'), 'embedding.weight').split(lengths)
    trace = ResidentRouteTrace(execution, execution.step_id, geometry, ranked.detach(), tuple(winners_by_layer))
    return outputs, trace

