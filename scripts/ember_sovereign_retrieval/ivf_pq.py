"""
Owned IVF-PQ content-addressable KV-memory module.
torch-native, GPU-capable, NO FAISS, NO HNSW.

Design:
  - Coarse k-means quantizer: nlist = ceil(sqrt(t)), 2-level above t=1e5
  - PQ subquantizers: m=8, LUT scan
  - Lazy recluster on geometric t-doubling
  - insert() and query(top_k) are separate timed entry points
  - d must be divisible by m (d=64, m=8 => subvec_dim=8)
"""

import math
import torch
import torch.nn.functional as F
from typing import Optional, Tuple


class IVFPQ:
    """
    IVF-PQ index for sovereign KV memory.
    Stores (key, value) pairs; retrieves top-k by approximate cosine/dot similarity.
    """

    def __init__(
        self,
        d: int,
        m: int = 8,
        nbits: int = 8,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
    ):
        """
        Args:
            d: key dimension (must be divisible by m)
            m: number of PQ subquantizers
            nbits: bits per subquantizer code (8 => 256 centroids each)
            device: torch device
            dtype: storage dtype (fp16 on GPU, fp32 on CPU)
        """
        assert d % m == 0, f"d={d} must be divisible by m={m}"
        self.d = d
        self.m = m
        self.nbits = nbits
        self.ksub = 2 ** nbits          # 256 for nbits=8
        self.subvec_dim = d // m
        self.device = device or torch.device("cpu")
        self.dtype = dtype

        # Coarse centroids: (nlist, d)
        self.nlist: int = 0
        self.coarse_centroids: Optional[torch.Tensor] = None  # (nlist, d)

        # PQ codebooks: (m, ksub, subvec_dim)
        self.pq_codebooks: Optional[torch.Tensor] = None

        # Index storage
        # keys_raw: full-precision keys, appended (t, d)
        self.keys_raw: Optional[torch.Tensor] = None
        # values_raw: (t, d)
        self.values_raw: Optional[torch.Tensor] = None
        # coarse_assign: (t,) int32 -- which coarse cell each key is in
        self.coarse_assign: Optional[torch.Tensor] = None
        # pq_codes: (t, m) uint8 -- PQ codes per key
        self.pq_codes: Optional[torch.Tensor] = None

        # Invert list: list of tensors per coarse cell -> idx into global arrays
        self.invlists: list = []

        # State
        self.t: int = 0                  # current number of keys
        self._last_recluster_t: int = 0  # last t at which we reclustered

        # Lazy recluster schedule: geometric doubling starting at 1024
        self._recluster_threshold: int = 1024

        # Flag: is the index valid (clustered)?
        self._index_valid: bool = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _to(self, x: torch.Tensor) -> torch.Tensor:
        return x.to(device=self.device, dtype=self.dtype)

    def _nlist_for(self, t: int) -> int:
        """nlist = ceil(sqrt(t)), with 2-level above t=1e5."""
        if t < 64:
            return max(1, t)
        base = math.ceil(math.sqrt(t))
        if t > 1e5:
            # 2-level: use sqrt(sqrt(t)) coarse cells for level-1
            # Practical choice: nlist = ceil(t^0.25) * 8 to keep probe count low
            return max(64, math.ceil(t ** 0.25) * 8)
        return max(4, base)

    def _kmeans(self, data: torch.Tensor, k: int, n_iter: int = 20) -> torch.Tensor:
        """
        Mini k-means on CPU/GPU data tensor (N, dim).
        Returns centroids (k, dim).
        """
        N, dim = data.shape
        k = min(k, N)
        if k <= 0:
            return data[:1].clone()

        # Init: random subset
        perm = torch.randperm(N, device=data.device)[:k]
        centroids = data[perm].clone().float()

        for _ in range(n_iter):
            # Assign
            # (N, k) distances via broadcast
            diff = data.float().unsqueeze(1) - centroids.unsqueeze(0)  # (N,k,dim)
            dists = (diff * diff).sum(dim=-1)  # (N,k)
            assign = dists.argmin(dim=-1)  # (N,)

            # Update
            new_centroids = torch.zeros_like(centroids)
            counts = torch.zeros(k, device=data.device, dtype=torch.float32)
            new_centroids.scatter_add_(0, assign.unsqueeze(1).expand(-1, dim).long(), data.float())
            counts.scatter_add_(0, assign.long(), torch.ones(N, device=data.device))
            mask = counts > 0
            new_centroids[mask] /= counts[mask].unsqueeze(1)
            # Re-seed empty clusters
            empty = (~mask).nonzero(as_tuple=True)[0]
            if len(empty) > 0:
                random_idx = torch.randperm(N, device=data.device)[:len(empty)]
                new_centroids[empty] = data[random_idx].float()
            centroids = new_centroids

        return centroids.to(self.dtype)

    def _build_pq_codebooks(self, keys: torch.Tensor):
        """Build PQ codebooks from a sample of keys."""
        N = keys.shape[0]
        codebooks = []
        for sub in range(self.m):
            start = sub * self.subvec_dim
            end = start + self.subvec_dim
            sub_data = keys[:, start:end]  # (N, subvec_dim)
            k = min(self.ksub, N)
            cb = self._kmeans(sub_data, k, n_iter=15)  # (ksub, subvec_dim)
            # Pad if N < ksub
            if k < self.ksub:
                pad = cb[0:1].expand(self.ksub - k, -1)
                cb = torch.cat([cb, pad], dim=0)
            codebooks.append(cb)
        # (m, ksub, subvec_dim)
        self.pq_codebooks = torch.stack(codebooks, dim=0)

    def _pq_encode(self, keys: torch.Tensor) -> torch.Tensor:
        """Encode keys (N, d) -> codes (N, m) uint8."""
        N = keys.shape[0]
        codes = torch.empty(N, self.m, dtype=torch.uint8, device=self.device)
        for sub in range(self.m):
            start = sub * self.subvec_dim
            end = start + self.subvec_dim
            sub_keys = keys[:, start:end].float()  # (N, subvec_dim)
            cb = self.pq_codebooks[sub].float()    # (ksub, subvec_dim)
            # Distances (N, ksub)
            diff = sub_keys.unsqueeze(1) - cb.unsqueeze(0)
            dists = (diff * diff).sum(dim=-1)
            codes[:, sub] = dists.argmin(dim=-1).to(torch.uint8)
        return codes

    def _pq_lut_score(self, query: torch.Tensor, nprobe_idx: torch.Tensor) -> torch.Tensor:
        """
        Compute approximate dot-product scores for a batch of keys using PQ LUT.

        Args:
            query: (d,)
            nprobe_idx: (M,) indices into keys_raw (the candidates from coarse search)

        Returns:
            scores: (M,) approximate dot products
        """
        M = nprobe_idx.shape[0]
        if M == 0:
            return torch.empty(0, device=self.device, dtype=torch.float32)

        # Build LUT: for each subquantizer, dot product of query subvec with each centroid
        # LUT: (m, ksub)
        lut = torch.empty(self.m, self.ksub, device=self.device, dtype=torch.float32)
        for sub in range(self.m):
            start = sub * self.subvec_dim
            end = start + self.subvec_dim
            qsub = query[start:end].float()  # (subvec_dim,)
            cb = self.pq_codebooks[sub].float()  # (ksub, subvec_dim)
            lut[sub] = (cb * qsub.unsqueeze(0)).sum(dim=-1)

        # Gather codes for candidates
        codes = self.pq_codes[nprobe_idx]  # (M, m)
        # Accumulate scores
        scores = torch.zeros(M, device=self.device, dtype=torch.float32)
        for sub in range(self.m):
            row = codes[:, sub].long()  # (M,)
            scores += lut[sub][row]

        return scores

    def _recluster(self):
        """Full recluster: rebuild coarse centroids + PQ codebooks + all assignments."""
        if self.t == 0:
            return
        keys = self.keys_raw[:self.t]  # (t, d)
        new_nlist = self._nlist_for(self.t)
        self.nlist = new_nlist

        # Coarse k-means
        self.coarse_centroids = self._kmeans(keys, new_nlist, n_iter=20)

        # PQ codebooks
        self._build_pq_codebooks(keys)

        # Allocate pq_codes and coarse_assign to full keys_raw capacity (not just t),
        # so incremental inserts after recluster can write without out-of-bounds.
        cap = self.keys_raw.shape[0]

        # Encode only the live t keys
        pq_codes_live = self._pq_encode(keys)  # (t, m)
        pq_codes_full = torch.zeros(cap, self.m, dtype=torch.uint8, device=self.device)
        pq_codes_full[:self.t] = pq_codes_live
        self.pq_codes = pq_codes_full

        # Coarse assignment for live keys
        diff = keys.float().unsqueeze(1) - self.coarse_centroids.float().unsqueeze(0)
        dists = (diff * diff).sum(dim=-1)
        assign_live = dists.argmin(dim=-1).to(torch.int32)
        coarse_assign_full = torch.zeros(cap, dtype=torch.int32, device=self.device)
        coarse_assign_full[:self.t] = assign_live
        self.coarse_assign = coarse_assign_full

        # Build inverted lists
        self.invlists = [[] for _ in range(self.nlist)]
        for idx in range(self.t):
            cell = int(self.coarse_assign[idx])
            self.invlists[cell].append(idx)

        self._index_valid = True
        self._last_recluster_t = self.t
        # Next recluster when t doubles from current threshold
        while self._recluster_threshold <= self.t:
            self._recluster_threshold *= 2

    def _maybe_recluster_lazy(self):
        """Lazy recluster: only when t crosses geometric doubling threshold."""
        if self.t >= self._recluster_threshold:
            self._recluster()

    def _append_raw(self, key: torch.Tensor, value: torch.Tensor):
        """Append a key/value pair to raw storage (amortized doubling)."""
        key = key.to(device=self.device, dtype=self.dtype)
        value = value.to(device=self.device, dtype=self.dtype)

        if self.keys_raw is None:
            cap = max(64, self._recluster_threshold)
            self.keys_raw = torch.empty(cap, self.d, device=self.device, dtype=self.dtype)
            self.values_raw = torch.empty(cap, self.d, device=self.device, dtype=self.dtype)

        if self.t >= self.keys_raw.shape[0]:
            # Double capacity
            old_cap = self.keys_raw.shape[0]
            new_cap = old_cap * 2
            new_keys = torch.empty(new_cap, self.d, device=self.device, dtype=self.dtype)
            new_vals = torch.empty(new_cap, self.d, device=self.device, dtype=self.dtype)
            new_keys[:old_cap] = self.keys_raw
            new_vals[:old_cap] = self.values_raw
            self.keys_raw = new_keys
            self.values_raw = new_vals
            # Extend pq_codes and coarse_assign to new_cap
            if self.pq_codes is not None:
                new_pc = torch.zeros(new_cap, self.m, dtype=torch.uint8, device=self.device)
                new_pc[:min(old_cap, self.pq_codes.shape[0])] = self.pq_codes[:min(old_cap, self.pq_codes.shape[0])]
                self.pq_codes = new_pc
            if self.coarse_assign is not None:
                new_ca = torch.zeros(new_cap, dtype=torch.int32, device=self.device)
                new_ca[:min(old_cap, self.coarse_assign.shape[0])] = self.coarse_assign[:min(old_cap, self.coarse_assign.shape[0])]
                self.coarse_assign = new_ca

        self.keys_raw[self.t] = key
        self.values_raw[self.t] = value
        self.t += 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert(self, key: torch.Tensor, value: torch.Tensor):
        """
        Insert one key/value pair. O(1) amortized (recluster on geometric doubling).
        key: (d,)
        value: (d,)
        """
        self._append_raw(key, value)

        # If index valid, do incremental append: encode + assign to nearest coarse cell
        if self._index_valid and self.coarse_centroids is not None and self.pq_codebooks is not None:
            idx = self.t - 1
            k = key.to(device=self.device, dtype=self.dtype)

            # Coarse assign
            diff = k.float().unsqueeze(0) - self.coarse_centroids.float()
            dists = (diff * diff).sum(dim=-1)
            cell = int(dists.argmin())
            self.coarse_assign[idx] = cell

            # PQ encode
            code = self._pq_encode(k.unsqueeze(0))  # (1, m)
            self.pq_codes[idx] = code[0]

            # Append to invlist
            if cell < len(self.invlists):
                self.invlists[cell].append(idx)
            else:
                # Cell index out of range (shouldn't happen); rebuild
                self._index_valid = False

        # Lazy recluster
        self._maybe_recluster_lazy()

        if not self._index_valid and self.t >= 64:
            self._recluster()

    def query(self, query: torch.Tensor, top_k: int = 256, nprobe: int = 8) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Retrieve top_k (key, value) pairs by approximate dot product.
        Returns (scores, values) sorted descending by score.

        query: (d,)
        Returns:
            retrieved_values: (min(top_k, t), d)
            retrieved_scores: (min(top_k, t),)
        """
        if self.t == 0:
            return torch.empty(0, self.d, device=self.device, dtype=self.dtype), \
                   torch.empty(0, device=self.device, dtype=torch.float32)

        if not self._index_valid or self.coarse_centroids is None:
            # Fallback: exact scan (only at small t before first cluster)
            return self._exact_query(query, top_k)

        q = query.to(device=self.device, dtype=self.dtype)

        # Coarse search: find nprobe nearest coarse cells
        diff = q.float().unsqueeze(0) - self.coarse_centroids.float()
        coarse_dists = (diff * diff).sum(dim=-1)
        actual_nprobe = min(nprobe, self.nlist)
        _, top_cells = torch.topk(-coarse_dists, actual_nprobe)

        # Gather candidates from invlists
        candidates = []
        for c in top_cells.tolist():
            if c < len(self.invlists):
                candidates.extend(self.invlists[c])

        if len(candidates) == 0:
            return self._exact_query(query, top_k)

        cand_idx = torch.tensor(candidates, device=self.device, dtype=torch.long)
        # Deduplicate
        cand_idx = torch.unique(cand_idx)

        # PQ LUT scoring
        scores = self._pq_lut_score(q, cand_idx)

        # Top-k selection
        actual_k = min(top_k, len(cand_idx))
        if actual_k < len(cand_idx):
            _, sel = torch.topk(scores, actual_k)
            cand_idx = cand_idx[sel]
            scores = scores[sel]
        else:
            order = torch.argsort(scores, descending=True)
            cand_idx = cand_idx[order]
            scores = scores[order]

        retrieved_values = self.values_raw[cand_idx]
        return retrieved_values, scores

    def _exact_query(self, query: torch.Tensor, top_k: int) -> Tuple[torch.Tensor, torch.Tensor]:
        """Exact dot-product scan over all stored keys."""
        q = query.to(device=self.device, dtype=self.dtype)
        keys = self.keys_raw[:self.t]  # (t, d)
        scores = (keys.float() @ q.float().unsqueeze(-1)).squeeze(-1)  # (t,)
        actual_k = min(top_k, self.t)
        top_scores, top_idx = torch.topk(scores, actual_k)
        return self.values_raw[top_idx], top_scores

    def reset(self):
        """Clear the index."""
        self.keys_raw = None
        self.values_raw = None
        self.coarse_assign = None
        self.pq_codes = None
        self.coarse_centroids = None
        self.pq_codebooks = None
        self.invlists = []
        self.t = 0
        self._last_recluster_t = 0
        self._recluster_threshold = 1024
        self._index_valid = False

    def freeze(self):
        """Mark index as frozen: subsequent insert() calls still append raw but skip encode+invlist."""
        # Freeze is enforced by the harness by not calling insert() during D-config steps.
        # This method is a no-op sentinel for clarity.
        pass
