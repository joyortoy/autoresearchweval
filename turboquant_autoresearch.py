#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import requests


ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = Path("/home/sam/memory/intentstack-memory-backfill")
DEFAULT_CASE_BUILDER = Path("/home/sam/qmd-src/scripts/build_intent_memory_cases.py")
DEFAULT_MODEL_URI = "ollama:qwen3-embedding:0.6b"
DEFAULT_OLLAMA_HOST = os.getenv("QMD_OLLAMA_HOST") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434"
FRONTMATTER_RE = re.compile(r"^---\s*\n[\s\S]*?\n---\s*\n*", re.MULTILINE)


@dataclass
class CorpusDoc:
    qmd_file: str
    text: str


def strip_frontmatter(text: str) -> str:
    stripped = FRONTMATTER_RE.sub("", text, count=1).strip()
    return stripped or text.strip()


def parse_model_name(model_uri: str) -> str:
    if not model_uri.startswith("ollama:"):
        raise ValueError(f"Only ollama:* models are supported for this harness, got {model_uri}")
    return model_uri.split(":", 1)[1]


def sanitize_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value)


def qmd_file_path(collection: str, path: Path) -> str:
    return f"qmd://{collection}/{path.name}"


def load_corpus(corpus_dir: Path, collection: str) -> list[CorpusDoc]:
    docs: list[CorpusDoc] = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = strip_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        if not text:
            continue
        docs.append(CorpusDoc(qmd_file=qmd_file_path(collection, path), text=text))
    if not docs:
        raise SystemExit(f"No markdown corpus files found in {corpus_dir}")
    return docs


def build_cases(cases_builder: Path, corpus_dir: Path, collection: str, output_path: Path) -> list[dict]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        [
            "python3",
            str(cases_builder),
            "--corpus",
            str(corpus_dir),
            "--collection",
            collection,
            "--output",
            str(output_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"Failed to build retrieval cases ({cp.returncode})\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}"
        )
    cases = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"Case builder produced no cases at {output_path}")
    return cases


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return matrix / norms


def corpus_cache_key(model_name: str, corpus_dir: Path, cases: list[dict], docs: list[CorpusDoc]) -> str:
    payload = {
        "model_name": model_name,
        "corpus_dir": str(corpus_dir),
        "docs": [doc.qmd_file for doc in docs],
        "cases": [{"id": c["id"], "query": c["query"], "expected_file": c.get("expected_file")} for c in cases],
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def embed_texts(
    texts: list[str],
    *,
    model_name: str,
    ollama_host: str,
    batch_size: int,
) -> tuple[np.ndarray, float]:
    vectors: list[list[float]] = []
    session = requests.Session()
    started = time.perf_counter()
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = session.post(
            f"{ollama_host.rstrip('/')}/api/embed",
            json={
                "model": model_name,
                "input": batch,
                "truncate": True,
                "keep_alive": "10m",
            },
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
        embeddings = payload.get("embeddings") or []
        if not embeddings:
            single = payload.get("embedding")
            if single:
                embeddings = [single]
        if len(embeddings) != len(batch):
            raise ValueError(f"Ollama returned {len(embeddings)} embeddings for batch size {len(batch)}")
        vectors.extend(embeddings)
    elapsed = time.perf_counter() - started
    return np.asarray(vectors, dtype=np.float32), elapsed


def load_or_embed_cache(
    *,
    cache_path: Path,
    docs: list[CorpusDoc],
    cases: list[dict],
    model_name: str,
    ollama_host: str,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, float, bool]:
    if cache_path.exists():
        payload = np.load(cache_path, allow_pickle=False)
        corpus = payload["corpus"].astype(np.float32)
        queries = payload["queries"].astype(np.float32)
        return corpus, queries, 0.0, True

    corpus_vectors, corpus_seconds = embed_texts(
        [doc.text for doc in docs],
        model_name=model_name,
        ollama_host=ollama_host,
        batch_size=batch_size,
    )
    query_vectors, query_seconds = embed_texts(
        [str(case["query"]) for case in cases],
        model_name=model_name,
        ollama_host=ollama_host,
        batch_size=batch_size,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, corpus=corpus_vectors, queries=query_vectors)
    return corpus_vectors, query_vectors, corpus_seconds + query_seconds, False


def select_high_precision_dims(vectors: np.ndarray, fraction: float) -> np.ndarray:
    dim = vectors.shape[1]
    high_count = max(1, min(dim - 1, int(round(dim * fraction))))
    # Favor dimensions with larger corpus variance when spending extra bits.
    importance = np.std(vectors, axis=0)
    chosen = np.argsort(importance)[-high_count:]
    return np.sort(chosen.astype(np.int32))


def quantize_block(block: np.ndarray, bits: int) -> tuple[np.ndarray, np.ndarray]:
    qmax = (1 << (bits - 1)) - 1
    max_abs = np.max(np.abs(block), axis=1)
    scale = np.maximum(max_abs / max(qmax, 1), 1e-12).astype(np.float32)
    codes = np.clip(np.rint(block / scale[:, None]), -qmax, qmax).astype(np.int8)
    return codes, scale


def quantize_dim_block(block: np.ndarray, bits: int, clip_percentile: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    levels = (1 << bits) - 1
    lower = np.percentile(block, clip_percentile, axis=0).astype(np.float32)
    upper = np.percentile(block, 100.0 - clip_percentile, axis=0).astype(np.float32)
    upper = np.maximum(upper, lower + 1e-6)
    scale = ((upper - lower) / max(levels, 1)).astype(np.float32)
    clipped = np.clip(block, lower, upper)
    codes = np.clip(np.rint((clipped - lower) / scale), 0, levels).astype(np.uint8)
    return codes, lower, scale


class QuantizedCorpus:
    def __init__(
        self,
        *,
        bits: float,
        scheme: str,
        inv_norms: np.ndarray,
        codes: np.ndarray | None = None,
        scales: np.ndarray | None = None,
        offsets: np.ndarray | None = None,
        low_codes: np.ndarray | None = None,
        low_scales: np.ndarray | None = None,
        low_offsets: np.ndarray | None = None,
        high_codes: np.ndarray | None = None,
        high_scales: np.ndarray | None = None,
        high_offsets: np.ndarray | None = None,
        low_idx: np.ndarray | None = None,
        high_idx: np.ndarray | None = None,
        packed_bytes: float,
    ) -> None:
        self.bits = bits
        self.scheme = scheme
        self.inv_norms = inv_norms.astype(np.float32)
        self.codes = codes
        self.scales = scales
        self.offsets = offsets
        self.low_codes = low_codes
        self.low_scales = low_scales
        self.low_offsets = low_offsets
        self.high_codes = high_codes
        self.high_scales = high_scales
        self.high_offsets = high_offsets
        self.low_idx = low_idx
        self.high_idx = high_idx
        self.packed_bytes = packed_bytes

    @property
    def mixed(self) -> bool:
        return self.codes is None

    def score(self, query: np.ndarray) -> np.ndarray:
        if self.scheme == "vector" and not self.mixed:
            base = self.codes.astype(np.float32) @ query.astype(np.float32)
            return (base * self.scales) * self.inv_norms
        if self.scheme == "vector":
            low = (self.low_codes.astype(np.float32) @ query[self.low_idx].astype(np.float32)) * self.low_scales
            high = (self.high_codes.astype(np.float32) @ query[self.high_idx].astype(np.float32)) * self.high_scales
            return (low + high) * self.inv_norms

        if not self.mixed:
            weighted_query = query.astype(np.float32) * self.scales
            bias = float(self.offsets.astype(np.float32) @ query.astype(np.float32))
            numer = self.codes.astype(np.float32) @ weighted_query
            return (numer + bias) * self.inv_norms
        bias = (
            float(self.low_offsets.astype(np.float32) @ query[self.low_idx].astype(np.float32))
            + float(self.high_offsets.astype(np.float32) @ query[self.high_idx].astype(np.float32))
        )
        low = self.low_codes.astype(np.float32) @ (
            query[self.low_idx].astype(np.float32) * self.low_scales.astype(np.float32)
        )
        high = self.high_codes.astype(np.float32) @ (
            query[self.high_idx].astype(np.float32) * self.high_scales.astype(np.float32)
        )
        return (low + high + bias) * self.inv_norms


def build_quantized_corpus(
    corpus: np.ndarray,
    bits: float,
    *,
    scheme: str,
    clip_percentile: float,
) -> QuantizedCorpus:
    rows, dim = corpus.shape
    if scheme not in {"vector", "dim"}:
        raise ValueError(f"Unsupported quantizer scheme: {scheme}")

    if scheme == "dim":
        if float(bits).is_integer():
            bit_count = int(bits)
            codes, offsets, scales = quantize_dim_block(corpus, bit_count, clip_percentile)
            approx = offsets[None, :] + codes.astype(np.float32) * scales[None, :]
            inv_norms = 1.0 / np.maximum(np.linalg.norm(approx, axis=1), 1e-12)
            packed = rows * dim * bit_count / 8.0 + dim * 8.0 + rows * 4.0
            return QuantizedCorpus(
                bits=bits,
                scheme=scheme,
                inv_norms=inv_norms,
                codes=codes,
                scales=scales,
                offsets=offsets,
                packed_bytes=packed,
            )

        lower = math.floor(bits)
        upper = math.ceil(bits)
        high_fraction = bits - lower
        high_idx = select_high_precision_dims(corpus, high_fraction)
        mask = np.ones(dim, dtype=bool)
        mask[high_idx] = False
        low_idx = np.nonzero(mask)[0].astype(np.int32)
        low_codes, low_offsets, low_scales = quantize_dim_block(corpus[:, low_idx], lower, clip_percentile)
        high_codes, high_offsets, high_scales = quantize_dim_block(corpus[:, high_idx], upper, clip_percentile)
        low_approx = low_offsets[None, :] + low_codes.astype(np.float32) * low_scales[None, :]
        high_approx = high_offsets[None, :] + high_codes.astype(np.float32) * high_scales[None, :]
        inv_norms = 1.0 / np.maximum(
            np.sqrt(np.sum(low_approx * low_approx, axis=1) + np.sum(high_approx * high_approx, axis=1)),
            1e-12,
        )
        packed = rows * (len(low_idx) * lower + len(high_idx) * upper) / 8.0 + dim * 16.0 + dim / 8.0 + rows * 4.0
        return QuantizedCorpus(
            bits=bits,
            scheme=scheme,
            inv_norms=inv_norms,
            low_codes=low_codes,
            low_scales=low_scales,
            low_offsets=low_offsets,
            high_codes=high_codes,
            high_scales=high_scales,
            high_offsets=high_offsets,
            low_idx=low_idx,
            high_idx=high_idx,
            packed_bytes=packed,
        )

    if float(bits).is_integer():
        bit_count = int(bits)
        codes, scales = quantize_block(corpus, bit_count)
        inv_norms = 1.0 / np.maximum(np.linalg.norm(codes.astype(np.float32) * scales[:, None], axis=1), 1e-12)
        packed = rows * dim * bit_count / 8.0 + rows * 8.0
        return QuantizedCorpus(
            bits=bits,
            scheme=scheme,
            inv_norms=inv_norms,
            codes=codes,
            scales=scales,
            packed_bytes=packed,
        )

    lower = math.floor(bits)
    upper = math.ceil(bits)
    high_fraction = bits - lower
    high_idx = select_high_precision_dims(corpus, high_fraction)
    mask = np.ones(dim, dtype=bool)
    mask[high_idx] = False
    low_idx = np.nonzero(mask)[0].astype(np.int32)
    low_codes, low_scales = quantize_block(corpus[:, low_idx], lower)
    high_codes, high_scales = quantize_block(corpus[:, high_idx], upper)
    inv_norms = 1.0 / np.maximum(
        np.sqrt(
            np.sum((low_codes.astype(np.float32) * low_scales[:, None]) ** 2, axis=1)
            + np.sum((high_codes.astype(np.float32) * high_scales[:, None]) ** 2, axis=1)
        ),
        1e-12,
    )
    packed = rows * (len(low_idx) * lower + len(high_idx) * upper) / 8.0 + rows * 12.0 + dim / 8.0
    return QuantizedCorpus(
        bits=bits,
        scheme=scheme,
        inv_norms=inv_norms,
        low_codes=low_codes,
        low_scales=low_scales,
        high_codes=high_codes,
        high_scales=high_scales,
        low_idx=low_idx,
        high_idx=high_idx,
        packed_bytes=packed,
    )


def quantize_query(query: np.ndarray, bits: float, corpus_quantized: QuantizedCorpus | None) -> np.ndarray:
    if corpus_quantized is not None and corpus_quantized.scheme == "dim":
        if float(bits).is_integer():
            if corpus_quantized.offsets is None or corpus_quantized.scales is None:
                raise ValueError("Dimwise query compression requires corpus calibration parameters")
            levels = (1 << int(bits)) - 1
            clipped = np.clip(query, corpus_quantized.offsets, corpus_quantized.offsets + corpus_quantized.scales * levels)
            codes = np.clip(
                np.rint((clipped - corpus_quantized.offsets) / corpus_quantized.scales),
                0,
                levels,
            ).astype(np.float32)
            approx = corpus_quantized.offsets + codes * corpus_quantized.scales
            norm = max(float(np.linalg.norm(approx)), 1e-12)
            return (approx / norm).astype(np.float32)

        if corpus_quantized.low_idx is None or corpus_quantized.high_idx is None:
            raise ValueError("Mixed dimwise query compression requires split indices")
        if (
            corpus_quantized.low_offsets is None
            or corpus_quantized.low_scales is None
            or corpus_quantized.high_offsets is None
            or corpus_quantized.high_scales is None
        ):
            raise ValueError("Mixed dimwise query compression requires corpus calibration parameters")
        approx = np.zeros_like(query, dtype=np.float32)
        low_bits = math.floor(bits)
        high_bits = math.ceil(bits)
        low_levels = (1 << low_bits) - 1
        high_levels = (1 << high_bits) - 1
        low_query = query[corpus_quantized.low_idx]
        high_query = query[corpus_quantized.high_idx]
        low_clip = np.clip(
            low_query,
            corpus_quantized.low_offsets,
            corpus_quantized.low_offsets + corpus_quantized.low_scales * low_levels,
        )
        high_clip = np.clip(
            high_query,
            corpus_quantized.high_offsets,
            corpus_quantized.high_offsets + corpus_quantized.high_scales * high_levels,
        )
        low_codes = np.clip(
            np.rint((low_clip - corpus_quantized.low_offsets) / corpus_quantized.low_scales),
            0,
            low_levels,
        ).astype(np.float32)
        high_codes = np.clip(
            np.rint((high_clip - corpus_quantized.high_offsets) / corpus_quantized.high_scales),
            0,
            high_levels,
        ).astype(np.float32)
        approx[corpus_quantized.low_idx] = corpus_quantized.low_offsets + low_codes * corpus_quantized.low_scales
        approx[corpus_quantized.high_idx] = corpus_quantized.high_offsets + high_codes * corpus_quantized.high_scales
        norm = max(float(np.linalg.norm(approx)), 1e-12)
        return (approx / norm).astype(np.float32)

    if float(bits).is_integer():
        codes, scales = quantize_block(query[None, :], int(bits))
        approx = codes.astype(np.float32)[0] * scales[0]
        norm = max(float(np.linalg.norm(approx)), 1e-12)
        return (approx / norm).astype(np.float32)

    if corpus_quantized is None or not corpus_quantized.mixed:
        raise ValueError("Mixed-bit query compression requires a mixed-bit corpus mask")
    low_codes, low_scales = quantize_block(query[None, corpus_quantized.low_idx], math.floor(bits))
    high_codes, high_scales = quantize_block(query[None, corpus_quantized.high_idx], math.ceil(bits))
    approx = np.zeros_like(query, dtype=np.float32)
    approx[corpus_quantized.low_idx] = low_codes.astype(np.float32)[0] * low_scales[0]
    approx[corpus_quantized.high_idx] = high_codes.astype(np.float32)[0] * high_scales[0]
    norm = max(float(np.linalg.norm(approx)), 1e-12)
    return (approx / norm).astype(np.float32)


def compute_ndcg(rank: int | None) -> float:
    if rank is None or rank > 10:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def percentile_ms(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float32), q))


def search_topk(scores: np.ndarray, top_k: int) -> np.ndarray:
    if len(scores) <= top_k:
        return np.argsort(scores)[::-1]
    idx = np.argpartition(scores, -top_k)[-top_k:]
    return idx[np.argsort(scores[idx])[::-1]]


def evaluate_config(
    *,
    name: str,
    corpus_repr: QuantizedCorpus | np.ndarray,
    queries: np.ndarray,
    cases: list[dict],
    expected_index: dict[str, int],
    top_k: int,
    query_bits: float | None,
    base_corpus_quant: QuantizedCorpus | None,
    baseline_index_bytes: float,
) -> dict:
    latencies_ms: list[float] = []
    query_bytes = 0.0
    hits = 0
    ndcgs: list[float] = []
    categories: dict[str, dict[str, float]] = {}

    category_hits: dict[str, int] = {}
    category_total: dict[str, int] = {}
    category_ndcg: dict[str, float] = {}

    for idx, case in enumerate(cases):
        expected_file = str(case["expected_file"])
        target = expected_index.get(expected_file)
        if target is None:
            continue

        started = time.perf_counter()
        query = queries[idx]
        if query_bits is not None:
            query = quantize_query(query, query_bits, base_corpus_quant)
            query_bytes += len(query) * query_bits / 8.0 + 4.0

        if isinstance(corpus_repr, QuantizedCorpus):
            scores = corpus_repr.score(query)
            index_bytes = corpus_repr.packed_bytes
        else:
            scores = corpus_repr @ query
            index_bytes = baseline_index_bytes

        ranked = search_topk(scores, top_k)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies_ms.append(elapsed_ms)

        rank = None
        for rank_idx, doc_idx in enumerate(ranked, start=1):
            if int(doc_idx) == int(target):
                rank = rank_idx
                break

        hit = 1 if rank is not None else 0
        hits += hit
        ndcg = compute_ndcg(rank)
        ndcgs.append(ndcg)

        category = str(case.get("category") or "uncategorized")
        category_total[category] = category_total.get(category, 0) + 1
        category_hits[category] = category_hits.get(category, 0) + hit
        category_ndcg[category] = category_ndcg.get(category, 0.0) + ndcg

    for category in sorted(category_total):
        total = category_total[category]
        categories[category] = {
            "recall_at_10": category_hits[category] / total,
            "ndcg_at_10": category_ndcg[category] / total,
            "queries": float(total),
        }

    query_count = max(len(cases), 1)
    recall_at_10 = hits / query_count
    ndcg_at_10 = sum(ndcgs) / query_count
    memory_ratio = baseline_index_bytes / index_bytes if index_bytes else 0.0
    return {
        "name": name,
        "recall_at_10": recall_at_10,
        "ndcg_at_10": ndcg_at_10,
        "p95_latency_ms": percentile_ms(latencies_ms, 95),
        "mean_latency_ms": float(np.mean(latencies_ms)) if latencies_ms else 0.0,
        "index_bytes": index_bytes,
        "index_mb": index_bytes / (1024.0 * 1024.0),
        "memory_ratio": memory_ratio,
        "avg_query_bytes": query_bytes / query_count,
        "categories": categories,
    }


def decide_result(result: dict, baseline: dict) -> tuple[str, str]:
    if result["name"] == "baseline":
        return "baseline", "baseline fixed"

    recall_drop_pp = (baseline["recall_at_10"] - result["recall_at_10"]) * 100.0
    ndcg_drop_pp = (baseline["ndcg_at_10"] - result["ndcg_at_10"]) * 100.0
    latency_ratio = (
        result["p95_latency_ms"] / baseline["p95_latency_ms"] if baseline["p95_latency_ms"] > 0 else 1.0
    )
    latency_delta_ms = result["p95_latency_ms"] - baseline["p95_latency_ms"]
    memory_ratio = result["memory_ratio"]
    if baseline["p95_latency_ms"] < 1.0:
        latency_ok = latency_delta_ms <= 0.25
    else:
        latency_ok = latency_ratio <= 1.10

    if memory_ratio >= 4.0 and recall_drop_pp <= 1.0 and ndcg_drop_pp <= 1.0 and latency_ok:
        return "adopt", "meets memory, quality, and latency gates"
    if recall_drop_pp > 1.5 or ndcg_drop_pp > 1.5:
        return "reject", "quality drop exceeds guardrail"
    return "adjust", "promising but misses at least one guardrail"


def ensure_results_header(path: Path) -> None:
    if path.exists():
        return
    path.write_text(
        "\t".join(
            [
                "timestamp",
                "model",
                "config",
                "bits",
                "corpus_compressed",
                "query_compressed",
                "recall_at_10",
                "ndcg_at_10",
                "p95_latency_ms",
                "mean_latency_ms",
                "index_mb",
                "memory_ratio",
                "avg_query_bytes",
                "decision",
                "note",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def append_result_row(path: Path, *, timestamp: str, model_name: str, config: dict, result: dict, decision: str, note: str) -> None:
    line = "\t".join(
        [
            timestamp,
            model_name,
            result["name"],
            str(config["bits"]),
            "1" if config["corpus_compressed"] else "0",
            "1" if config["query_compressed"] else "0",
            f"{result['recall_at_10']:.4f}",
            f"{result['ndcg_at_10']:.4f}",
            f"{result['p95_latency_ms']:.3f}",
            f"{result['mean_latency_ms']:.3f}",
            f"{result['index_mb']:.6f}",
            f"{result['memory_ratio']:.4f}",
            f"{result['avg_query_bytes']:.2f}",
            decision,
            note,
        ]
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def print_result(result: dict, decision: str, note: str) -> None:
    print(
        "[turboquant] {name}: recall@10={recall:.4f} ndcg@10={ndcg:.4f} "
        "p95={p95:.3f}ms mem={mem:.3f}MB x{ratio:.2f} decision={decision} note={note}".format(
            name=result["name"],
            recall=result["recall_at_10"],
            ndcg=result["ndcg_at_10"],
            p95=result["p95_latency_ms"],
            mem=result["index_mb"],
            ratio=result["memory_ratio"],
            decision=decision,
            note=note,
        )
    )


def run_experiment(args: argparse.Namespace) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = parse_model_name(args.model)
    docs = load_corpus(Path(args.corpus), args.collection)
    cases_path = Path(args.cases) if args.cases else ROOT / "logs" / f"turboquant_cases_{timestamp}.json"
    cases = build_cases(Path(args.cases_builder), Path(args.corpus), args.collection, cases_path)

    expected_index = {doc.qmd_file: idx for idx, doc in enumerate(docs)}
    cache_key = corpus_cache_key(model_name, Path(args.corpus), cases, docs)
    cache_path = ROOT / "logs" / f"turboquant_cache_{sanitize_name(model_name)}_{cache_key}.npz"

    print(
        f"[turboquant] corpus_docs={len(docs)} cases={len(cases)} model={model_name} "
        f"quantizer={args.quantizer} clip={args.clip_percentile:.2f}"
    )
    corpus_raw, query_raw, embed_seconds, cache_hit = load_or_embed_cache(
        cache_path=cache_path,
        docs=docs,
        cases=cases,
        model_name=model_name,
        ollama_host=args.ollama_host,
        batch_size=args.batch_size,
    )
    corpus = normalize_rows(corpus_raw)
    queries = normalize_rows(query_raw)
    print(
        f"[turboquant] embedding_cache={'hit' if cache_hit else 'miss'} "
        f"embed_seconds={embed_seconds:.2f} cache={cache_path}"
    )

    baseline_index_bytes = corpus.shape[0] * corpus.shape[1] * 4.0
    baseline = evaluate_config(
        name="baseline",
        corpus_repr=corpus,
        queries=queries,
        cases=cases,
        expected_index=expected_index,
        top_k=args.top_k,
        query_bits=None,
        base_corpus_quant=None,
        baseline_index_bytes=baseline_index_bytes,
    )
    print_result(baseline, "baseline", "baseline fixed")

    name_prefix = f"{args.quantizer}_"
    configs = [
        {"name": f"{name_prefix}corpus_4bit", "bits": 4.0, "corpus_compressed": True, "query_compressed": False},
        {"name": f"{name_prefix}corpus_3.5bit", "bits": 3.5, "corpus_compressed": True, "query_compressed": False},
        {"name": f"{name_prefix}corpus_3bit", "bits": 3.0, "corpus_compressed": True, "query_compressed": False},
    ]
    fallback_configs = [
        {"name": f"{name_prefix}corpus_7bit", "bits": 7.0, "corpus_compressed": True, "query_compressed": False},
        {"name": f"{name_prefix}corpus_6bit", "bits": 6.0, "corpus_compressed": True, "query_compressed": False},
        {"name": f"{name_prefix}corpus_5bit", "bits": 5.0, "corpus_compressed": True, "query_compressed": False},
    ]

    results: list[dict] = []
    ensure_results_header(Path(args.results_tsv))
    append_result_row(
        Path(args.results_tsv),
        timestamp=timestamp,
        model_name=model_name,
        config={"bits": 32.0, "corpus_compressed": False, "query_compressed": False},
        result=baseline,
        decision="baseline",
        note="baseline fixed",
    )

    best_corpus_result: dict | None = None
    best_corpus_quant: QuantizedCorpus | None = None

    def run_corpus_config(config: dict) -> None:
        nonlocal best_corpus_result, best_corpus_quant
        quantized = build_quantized_corpus(
            corpus,
            config["bits"],
            scheme=args.quantizer,
            clip_percentile=args.clip_percentile,
        )
        result = evaluate_config(
            name=config["name"],
            corpus_repr=quantized,
            queries=queries,
            cases=cases,
            expected_index=expected_index,
            top_k=args.top_k,
            query_bits=None,
            base_corpus_quant=quantized,
            baseline_index_bytes=baseline_index_bytes,
        )
        decision, note = decide_result(result, baseline)
        result["decision"] = decision
        result["note"] = note
        results.append(result)
        append_result_row(
            Path(args.results_tsv),
            timestamp=timestamp,
            model_name=model_name,
            config=config,
            result=result,
            decision=decision,
            note=note,
        )
        print_result(result, decision, note)
        if decision == "adopt" and (
            best_corpus_result is None or result["ndcg_at_10"] > best_corpus_result["ndcg_at_10"]
        ):
            best_corpus_result = result
            best_corpus_quant = quantized

    for config in configs:
        run_corpus_config(config)

    if best_corpus_result is None:
        print("[turboquant] no corpus-only config passed; expanding sweep to safer rescue bits")
        for config in fallback_configs:
            run_corpus_config(config)

    if best_corpus_result is not None and best_corpus_quant is not None:
        query_config = {
            "name": f"{best_corpus_result['name']}_query",
            "bits": best_corpus_quant.bits,
            "corpus_compressed": True,
            "query_compressed": True,
        }
        query_result = evaluate_config(
            name=query_config["name"],
            corpus_repr=best_corpus_quant,
            queries=queries,
            cases=cases,
            expected_index=expected_index,
            top_k=args.top_k,
            query_bits=best_corpus_quant.bits,
            base_corpus_quant=best_corpus_quant,
            baseline_index_bytes=baseline_index_bytes,
        )
        decision, note = decide_result(query_result, baseline)
        query_result["decision"] = decision
        query_result["note"] = note
        results.append(query_result)
        append_result_row(
            Path(args.results_tsv),
            timestamp=timestamp,
            model_name=model_name,
            config=query_config,
            result=query_result,
            decision=decision,
            note=note,
        )
        print_result(query_result, decision, note)

    report = {
        "timestamp": timestamp,
        "model_uri": args.model,
        "model_name": model_name,
        "quantizer": args.quantizer,
        "clip_percentile": args.clip_percentile,
        "ollama_host": args.ollama_host,
        "corpus": str(Path(args.corpus).resolve()),
        "collection": args.collection,
        "cases_path": str(cases_path.resolve()),
        "corpus_docs": len(docs),
        "query_count": len(cases),
        "embed_seconds": round(embed_seconds, 3),
        "cache_hit": cache_hit,
        "baseline": baseline,
        "results": results,
    }
    output_path = Path(args.output_json) if args.output_json else ROOT / "logs" / f"turboquant_report_{timestamp}.json"
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[turboquant] report={output_path}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compact TurboQuant-style autoresearch benchmark for local embeddings.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--collection", default="intent-memory")
    parser.add_argument("--cases-builder", default=str(DEFAULT_CASE_BUILDER))
    parser.add_argument("--cases", default="")
    parser.add_argument("--model", default=DEFAULT_MODEL_URI)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--quantizer", choices=["dim", "vector"], default="dim")
    parser.add_argument("--clip-percentile", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--results-tsv", default=str(ROOT / "logs" / "turboquant_results.tsv"))
    parser.add_argument("--output-json", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_experiment(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
