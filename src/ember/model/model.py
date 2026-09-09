# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Temporary import compatibility until the EMBER-02B callers migrate (#2213)."""
# Remove after the #2213 EMBER-02B caller carrier merges, through the third EMBER-02A carrier.
import sys as _ember_v0_compat_sys
from pathlib import Path as _EmberV0CompatPath

if __package__:
    from . import ember_v0_model as _ember_v0_compat_impl
else:
    _ember_v0_compat_dir = str(_EmberV0CompatPath(__file__).resolve().parent)
    _ember_v0_compat_sys.path.insert(0, _ember_v0_compat_dir)
    try:
        import ember_v0_model as _ember_v0_compat_impl
    finally:
        _ember_v0_compat_sys.path.remove(_ember_v0_compat_dir)

if _EmberV0CompatPath(_ember_v0_compat_impl.__file__).resolve() != _EmberV0CompatPath(__file__).resolve().with_name("ember_v0_model.py"):
    raise ImportError("VERSIONED_MODEL_COMPATIBILITY_SOURCE_MISMATCH")

# Preserve private exports while retaining the exact compatibility source path.
globals().update({name: value for name, value in vars(_ember_v0_compat_impl).items() if not name.startswith("__")})

# The existing EMBER-02B source reader opens this path until its caller carrier.
# Keep its two inspected class definitions identical to the versioned source.
class RotaryCoordinates(nn.Module):
    """Parameter-free 1D text/audio and 2D image rotary coordinates."""

    def __init__(self, head_dim: int, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        if head_dim % 4 != 0:
            raise ValueError("head_dim must be divisible by 4")
        self.head_dim = head_dim
        self.axis_dim = head_dim // 2
        base = torch.arange(0, self.axis_dim, 2, device=device, dtype=torch.float32)
        self.register_buffer(
            "frequencies",
            torch.pow(10000.0, -base / self.axis_dim),
            persistent=False,
        )

    def _apply(self, fn):
        result = super()._apply(fn)
        # Rotary frequency arithmetic is part of the frozen float32 contract;
        # dtype-wide module transforms must not quantize this nonpersistent cache.
        base = torch.arange(
            0, self.axis_dim, 2, device=self.frequencies.device, dtype=torch.float32
        )
        self.frequencies = torch.pow(10000.0, -base / self.axis_dim)
        return result

    def apply(self, values: torch.Tensor, coordinates: torch.Tensor) -> torch.Tensor:
        if values.shape[-1] != self.head_dim:
            raise ValueError("rotary values width must match head_dim")
        if coordinates.shape[-1] != 2:
            raise ValueError("rotary coordinates must have exactly two axes")
        output = torch.empty_like(values)
        for axis in range(2):
            start = axis * self.axis_dim
            chunk = values[..., start : start + self.axis_dim]
            destination = output[..., start : start + self.axis_dim]
            angle = (
                coordinates[..., axis].to(torch.float32).unsqueeze(-1)
                * self.frequencies
            )
            cos = angle.cos().to(chunk.dtype).unsqueeze(1)
            sin = angle.sin().to(chunk.dtype).unsqueeze(1)
            even = chunk[..., 0::2]
            odd = chunk[..., 1::2]
            destination[..., 0::2].copy_(even * cos - odd * sin)
            destination[..., 1::2].copy_(even * sin + odd * cos)
        return output

    def apply_qk_sdpa(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        value: torch.Tensor,
        coordinates: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Rotate q/k together in SDPA-ready B,H,S,D layout; leave value unchanged."""

        if query.ndim != 4 or key.shape != query.shape or value.shape != query.shape:
            raise ValueError("QK_ROPE_SDPA_REFUSED:QKV_SHAPE")
        if query.dtype != key.dtype or query.dtype != value.dtype:
            raise ValueError("QK_ROPE_SDPA_REFUSED:QKV_DTYPE")
        if query.device != key.device or query.device != value.device:
            raise ValueError("QK_ROPE_SDPA_REFUSED:QKV_DEVICE")
        batch, _heads, sequence, head_dim = query.shape
        if head_dim != self.head_dim:
            raise ValueError("QK_ROPE_SDPA_REFUSED:HEAD_DIM")
        if coordinates.shape != (batch, sequence, 2):
            raise ValueError("QK_ROPE_SDPA_REFUSED:COORDINATE_SHAPE")
        if coordinates.device != query.device or self.frequencies.device != query.device:
            raise ValueError("QK_ROPE_SDPA_REFUSED:COORDINATE_DEVICE")

        pairs_per_axis = head_dim // 4
        angle = coordinates.to(torch.float32).unsqueeze(-1) * self.frequencies
        cos = angle.cos().to(query.dtype).unsqueeze(0).unsqueeze(2)
        sin = angle.sin().to(query.dtype).unsqueeze(0).unsqueeze(2)
        qk = torch.stack((query, key), dim=0)
        paired = qk.reshape(2, batch, _heads, sequence, 2, pairs_per_axis, 2)
        even = paired[..., 0]
        odd = paired[..., 1]
        rotated = torch.stack(
            (even * cos - odd * sin, even * sin + odd * cos), dim=-1
        ).reshape(2, batch, _heads, sequence, head_dim)
        return rotated[0], rotated[1], value


class SharedAttention(nn.Module):
    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.heads = config.attention_heads
        self.head_dim = config.hidden_size // config.attention_heads
        self.qkv = nn.Linear(config.hidden_size, 3 * config.hidden_size, bias=False, device=device)
        self.q_norm = RMSNorm(self.head_dim, device=device)
        self.k_norm = RMSNorm(self.head_dim, device=device)
        self.output = nn.Linear(config.hidden_size, config.hidden_size, bias=False, device=device)
        self.rope = RotaryCoordinates(self.head_dim, device=device)

    def forward(self, hidden_states: torch.Tensor, coordinates: torch.Tensor, allowed: torch.Tensor | None) -> torch.Tensor:
        batch, sequence, width = hidden_states.shape
        qkv = fp8_linear.linear(hidden_states, self.qkv.weight).view(
            batch, sequence, 3, self.heads, self.head_dim
        )
        query, key, value = qkv.permute(2, 0, 3, 1, 4).unbind(dim=0)
        query = self.q_norm(query)
        key = self.k_norm(key)
        query, key, value = self.rope.apply_qk_sdpa(query, key, value, coordinates)
        # ``allowed`` is None exactly when the built mask would be the plain causal mask.
        # Expressing that case as is_causal is the same computation and admits the fused
        # attention kernels, which an explicit attn_mask disqualifies (issue #1945).
        if allowed is None:
            attended = F.scaled_dot_product_attention(query, key, value, attn_mask=None, is_causal=True)
        else:
            attended = F.scaled_dot_product_attention(query, key, value, attn_mask=allowed.unsqueeze(1), is_causal=False)
        return fp8_linear.linear(
            attended.transpose(1, 2).reshape(batch, sequence, width), self.output.weight
        )


# Runtime callers retain the canonical class objects; the fragment serves source compatibility.
RotaryCoordinates = _ember_v0_compat_impl.RotaryCoordinates
SharedAttention = _ember_v0_compat_impl.SharedAttention
