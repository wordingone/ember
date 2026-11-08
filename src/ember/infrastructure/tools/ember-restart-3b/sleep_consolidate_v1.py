# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""SLEEP-1: one NREM consolidation pass of a wake child against its own parent (#2119; "Language Models Need Sleep",
arXiv 2606.03979, Knowledge Seeding with gamma = 0).

Teacher = the parent checkpoint (self, frozen). Student = the wake child plus K rank-r experts. Each expert is a low-rank
delta on one computed MLP weight, W = W0 + B @ A, with B zero-initialised, so the student is bit-identical to the child
before the first update. Only A and B train: after each backward the dense gradient G = dL/dW of a target weight gives
dA = B^T G and dB = G A^T (the exact LoRA chain rule), AdamW steps A and B, and W is rewritten as W0 + B @ A. Every other
tensor is frozen. The decoder's parameter inventory never changes, so the consolidated child is an ordinary checkpoint
that the existing scorer reads unchanged.

Objective per prefix x (alpha = 0.5, lambda = 0.5):
  L = alpha * KL(student || teacher) on student rollouts  +  (1 - alpha) * (-(r - baseline) * log p_student(y | x'))
where the second term is Learning-to-Imitate: x' = x + a random prefix of a teacher continuation, y the student's
continuation, r = 1 - Levenshtein(y, teacher remainder) / max_len when that distance <= z0 * max_len, else 0
(gamma = 0: no reward model). baseline = the batch mean reward. Sampling is never differentiated.
Every teacher and student sample is ledgered as self-generated (provenance ember-self-dream).

The mechanics (experts, projection, objective, ledger) take a plain logits function so they are tested on a tiny random
model (tests/ember_restart_model/test_sleep_consolidate_v1.py); main() binds them to CIADecoder checkpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
import contextlib
from dataclasses import dataclass, field
from pathlib import Path

import torch

ALPHA, LAMBDA, GAMMA, Z0 = 0.5, 0.5, 0.0, 0.5
PROVENANCE = 'ember-self-dream'


@dataclass
class LowRankExpert:
    """W = W0 + B @ A for one target weight W of shape (out, in). B starts at zero."""
    name: str
    weight: torch.Tensor
    rank: int
    seed: int
    w0: torch.Tensor = field(init=False)
    a: torch.Tensor = field(init=False)
    b: torch.Tensor = field(init=False)

    def __post_init__(self):
        out_dim, in_dim = self.weight.shape
        gen = torch.Generator().manual_seed(self.seed)
        self.w0 = self.weight.detach().clone()
        self.a = (torch.randn(self.rank, in_dim, generator=gen, dtype=torch.float32) / math.sqrt(in_dim)).to(self.weight.device)
        self.b = torch.zeros(out_dim, self.rank, dtype=torch.float32, device=self.weight.device)
        self.a.requires_grad_(True)
        self.b.requires_grad_(True)

    def project_grad(self):
        """Move the dense gradient of W onto A and B (LoRA chain rule); W's own gradient is cleared."""
        g = self.weight.grad
        if g is None:
            raise ValueError(f'{self.name}: no gradient reached the target weight')
        g = g.float()
        self.a.grad = self.b.detach().t() @ g
        self.b.grad = g @ self.a.detach().t()
        self.weight.grad = None

    @torch.no_grad()
    def write(self):
        self.weight.copy_((self.w0.float() + self.b @ self.a).to(self.weight.dtype))


def freeze_except(parameters: dict, targets) -> None:
    """Every parameter frozen except the target weights (which carry the dense gradient that is projected)."""
    for name, p in parameters.items():
        p.requires_grad_(name in targets)
        p.grad = None


def levenshtein(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def imitation_reward(student, teacher, z0=Z0) -> float:
    n = max(len(student), len(teacher), 1)
    d = levenshtein(student, teacher)
    return 1.0 - d / n if d <= z0 * n else 0.0


@torch.no_grad()
def sample(logits_fn, prefix, steps, generator, temperature=1.0):
    seq = list(prefix)
    for _ in range(steps):
        logits = logits_fn(seq)[-1].float() / temperature
        seq.append(int(torch.multinomial(torch.softmax(logits, -1).cpu(), 1, generator=generator)))
    return seq[len(prefix):]


def continuation_logprobs(logits_fn, prefix, cont):
    """Log-probabilities of every vocabulary entry at the positions that predict cont (grad flows if logits_fn allows)."""
    logits = logits_fn(list(prefix) + list(cont))
    return torch.log_softmax(logits[len(prefix) - 1:len(prefix) - 1 + len(cont)].float(), -1)


class Ledger:
    """Every generated sample is a training token with provenance; nothing generated is untracked."""

    def __init__(self, path: Path, generator_sha256: dict):
        self.path, self.generator_sha256, self.rows, self.tokens = path, generator_sha256, 0, 0

    def add(self, role, seed, prefix, tokens):
        row = dict(provenance=PROVENANCE, role=role, generator_checkpoint_sha256=self.generator_sha256[role], seed=seed,
                   prefix_sha256=hashlib.sha256(json.dumps(list(prefix)).encode()).hexdigest(), tokens=list(tokens))
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row) + '\n')
        self.rows += 1
        self.tokens += len(tokens)


def consolidation_step(student_fn, teacher_fn, experts, optimizer, prefixes, *, cont_len, seed, ledger, alpha=ALPHA):
    """One update over a batch of prefixes. Returns the loss terms."""
    gen = torch.Generator().manual_seed(seed)
    kl_terms, lti = [], []
    for i, x in enumerate(prefixes):
        # reverse KL on an on-policy student rollout (lambda share) or a teacher sample (1 - lambda share), GKD-style
        on_policy = random.Random(seed * 1000 + i).random() < LAMBDA
        y = sample(student_fn if on_policy else teacher_fn, x, cont_len, gen)
        ledger.add('student' if on_policy else 'teacher', seed, x, y)
        log_s = continuation_logprobs(student_fn, x, y)
        with torch.no_grad():
            log_t = continuation_logprobs(teacher_fn, x, y)
        kl_terms.append((log_s.exp() * (log_s - log_t)).sum(-1).mean())
        # learning to imitate: random cut of a teacher continuation, student continues, Levenshtein reward
        t = sample(teacher_fn, x, cont_len, gen)
        ledger.add('teacher', seed, x, t)
        cut = random.Random(seed * 7919 + i).randrange(1, cont_len)
        xp = list(x) + t[:cut]
        ys = sample(student_fn, xp, cont_len - cut, gen)
        ledger.add('student', seed, xp, ys)
        lp = continuation_logprobs(student_fn, xp, ys)
        lti.append((imitation_reward(ys, t[cut:]), lp.gather(-1, torch.tensor(ys, device=lp.device)[:, None]).sum()))
    baseline = sum(r for r, _ in lti) / len(lti)
    kl = torch.stack(kl_terms).mean()
    pg = torch.stack([-(r - baseline) * lp for r, lp in lti]).mean()
    loss = alpha * kl + (1 - alpha) * pg
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    for e in experts:
        e.project_grad()
    optimizer.step()
    for e in experts:
        e.write()
    return dict(loss=float(loss.detach()), kl=float(kl.detach()), lti=float(pg.detach()), reward_mean=baseline)


def step_context(model, device):
    """CUDA forwards need a candidate_step; the CPU reference runs without one."""
    return contextlib.nullcontext() if str(device) == 'cpu' else model.candidate_step()


def torch_globals() -> dict:
    """The process-wide torch state a forward depends on (logged before forwards; SLEEP-1 probe-2 rule)."""
    return dict(default_dtype=str(torch.get_default_dtype()), grad=torch.is_grad_enabled(),
                autocast_cuda=torch.is_autocast_enabled('cuda'), autocast_cpu=torch.is_autocast_enabled('cpu'))


class GlobalScope:
    """Restores the default dtype captured at construction around every forward and records each distinct global
    state seen per caller, so a restore or optimizer path that flips process state cannot reach the teacher silently."""

    def __init__(self, record):
        self.dtype = torch.get_default_dtype()
        self.record = record
        self.seen = set()

    @contextlib.contextmanager
    def __call__(self, who):
        state = torch_globals()
        key = (who, tuple(sorted(state.items())))
        if key not in self.seen:
            self.seen.add(key)
            self.record(dict(who=who, captured_default_dtype=str(self.dtype), **state))
        previous = torch.get_default_dtype()
        torch.set_default_dtype(self.dtype)
        try:
            yield
        finally:
            torch.set_default_dtype(previous)


def count_routes(model, prefixes, device):  # pragma: no cover - GPU binding
    """Chosen-expert counts per layer on the teacher's own prefixes, once, before training (places the 2 expert deltas).
    Each decoder route is (document, layer, start, candidates, chosen)."""
    counts = {}
    with torch.no_grad():
        for tokens in prefixes:
            t = torch.tensor(tokens, dtype=torch.long, device=device)
            pos = torch.tensor([[i, 0, 0] for i in range(len(tokens))], dtype=torch.long, device=device)
            with step_context(model, device):
                _logits, routes = model(model.embed_text(t), pos, document_starts=(0,), return_routes=True)
            for _doc, layer, _start, _candidates, chosen in routes:
                key = f'{int(layer)}:{int(chosen)}'
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def make_optimizer(experts, lr):
    return torch.optim.AdamW([t for e in experts for t in (e.a, e.b)], lr=lr, betas=(0.9, 0.999), weight_decay=0.0)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--worktree', required=True)
    ap.add_argument('--teacher-root', required=True)
    ap.add_argument('--teacher-manifest-sha256', required=True)
    ap.add_argument('--student-root', required=True)
    ap.add_argument('--student-manifest-sha256', required=True)
    ap.add_argument('--prefixes', required=True, help='jsonl of {"tokens": [...]} drawn from the parent training mixture')
    ap.add_argument('--targets', required=True, help='comma list of inventory weight names (each gets one expert)')
    ap.add_argument('--rank', type=int, default=64)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--steps', type=int, required=True)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--cont-len', type=int, default=32)
    ap.add_argument('--wall-seconds', type=int, default=3600)
    ap.add_argument('--device', default='cuda:0')
    ap.add_argument('--out', required=True)
    return ap.parse_args(argv)


def main(argv=None):  # pragma: no cover - GPU binding, exercised by the governed run, not by the CPU reds
    args = parse_args(argv)
    import sys
    wt = Path(args.worktree).resolve(strict=True)
    sys.path.insert(0, str(wt / 'src'))
    sys.path.insert(0, str(wt / 'src/ember/infrastructure/tools/ember-restart-3b'))
    import checkpoint_artifacts as artifacts
    from ember.model.ember_v0_decoder import CIADecoder
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    device = torch.device(args.device)

    def load(root, want):
        receipt = artifacts.published_checkpoint_receipt(Path(root))
        verified, tensors, _o, _r = artifacts._cia_validated_checkpoint(Path(root), receipt, retain_model=True,
                                                                      max_restore_payload_bytes=40 * 2 ** 30)
        if verified['checkpoint_manifest_sha256'] != want:
            raise ValueError(f'{root}: manifest {verified["checkpoint_manifest_sha256"]} is not {want}')
        model = CIADecoder(architecture_config=verified['architecture_config']).materialize_cpu(seed=0)
        inv = model.parameter_inventory()
        with torch.no_grad():
            for name, value in tensors.items():
                inv[name].copy_(value)
        return model, verified

    teacher, _tv = load(args.teacher_root, args.teacher_manifest_sha256)
    student, sv = load(args.student_root, args.student_manifest_sha256)
    targets = [t for t in args.targets.split(',') if t]
    prefixes = [json.loads(l)['tokens'] for l in Path(args.prefixes).read_text(encoding='utf-8').splitlines() if l.strip()]
    routing_counts = count_routes(teacher, prefixes, device)
    (out / 'routing-counts.json').write_text(json.dumps(routing_counts, indent=1) + '\n', encoding='utf-8')
    freeze_except(teacher.parameter_inventory(), ())
    freeze_except(student.parameter_inventory(), set(targets))
    teacher.eval(); student.train()
    teacher.activate_cuda(device); student.activate_cuda(device)
    inv = student.parameter_inventory()
    experts = [LowRankExpert(name, inv[name], args.rank, seed=1000 + i) for i, name in enumerate(targets)]
    opt = make_optimizer(experts, args.lr)

    def fn(model):
        def logits(tokens):
            t = torch.tensor(tokens, dtype=torch.long, device=device)
            pos = torch.tensor([[i, 0, 0] for i in range(len(tokens))], dtype=torch.long, device=device)
            with step_context(model, device):
                return model(model.embed_text(t), pos, document_starts=(0,))
        return logits

    ledger = Ledger(out / 'self-dream-ledger.jsonl', dict(teacher=args.teacher_manifest_sha256, student=args.student_manifest_sha256))
    started, rows = time.perf_counter(), []
    for step in range(args.steps):
        if time.perf_counter() - started > args.wall_seconds:
            break
        batch = [prefixes[(step * args.batch + j) % len(prefixes)] for j in range(args.batch)]
        terms = consolidation_step(fn(student), fn(teacher), experts, opt, batch, cont_len=args.cont_len, seed=step, ledger=ledger)
        if not all(math.isfinite(v) for v in terms.values()):
            raise ValueError(f'non-finite loss at step {step}')
        rows.append(dict(step=step, **terms))
        with (out / 'steps.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(rows[-1]) + '\n')
    torch.save({e.name: dict(a=e.a.detach().cpu(), b=e.b.detach().cpu(), w0_sha256=hashlib.sha256(
        e.w0.detach().float().cpu().numpy().tobytes()).hexdigest()) for e in experts}, out / 'sleep-deltas.pt')
    receipt = dict(kind='sleep-1-consolidation', routing_counts=routing_counts, deltas='sleep-deltas.pt',
                   fidelity='merged low-rank delta (W = W0 + B@A); expert masking and pruning reach paper fidelity only in SLEEP-2', teacher=args.teacher_manifest_sha256, student_in=args.student_manifest_sha256,
                   targets=targets, rank=args.rank, lr=args.lr, alpha=ALPHA, lambda_=LAMBDA, gamma=GAMMA, z0=Z0,
                   steps_done=len(rows), ledger_rows=ledger.rows, seconds=time.perf_counter() - started,
                   claim='The consolidated child is the student with every expert merged into its target weight.')
    (out / 'sleep-receipt.json').write_text(json.dumps(receipt, indent=1) + '\n', encoding='utf-8')
    return student, sv, receipt


if __name__ == '__main__':  # pragma: no cover
    main()
