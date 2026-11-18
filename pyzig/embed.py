"""Backend de embeddings local (ONNX CPU). Degradacion explicita a lexical."""
from __future__ import annotations
import hashlib, pathlib
import numpy as np
from .paths import MODELS

MODEL_NAME = "all-MiniLM-L6-v2"
DIM = 384
MAX_TOKENS = 256

class Unavailable(RuntimeError):
    pass

class Embedder:
    def __init__(self, models_dir: pathlib.Path | None = None, max_tokens: int = MAX_TOKENS):
        self.models_dir = pathlib.Path(models_dir or MODELS) / MODEL_NAME
        self.max_tokens = max_tokens
        self.degraded = False
        self._mode = "unavailable"
        self._sess = None
        self._tok = None
        self._load()

    def _load(self) -> None:
        onnx = self.models_dir / "onnx" / "model.onnx"
        tokj = self.models_dir / "tokenizer.json"
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            if not onnx.exists() or not tokj.exists():
                raise Unavailable(f"modelo ausente en {self.models_dir}")
            self._sess = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"])
            tok = Tokenizer.from_file(str(tokj))
            tok.no_truncation()
            tok.enable_truncation(self.max_tokens)
            tok.enable_padding(length=None)
            self._tok = tok
            self._mode = "onnx"
        except Exception as e:  # noqa: BLE001
            self.degraded = True
            self._mode = f"unavailable: {type(e).__name__}"

    @property
    def mode(self) -> str:
        return self._mode

    def model_meta(self) -> dict:
        onnx = self.models_dir / "onnx" / "model.onnx"
        tokj = self.models_dir / "tokenizer.json"
        def sha(p: pathlib.Path) -> str | None:
            return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        return {"model": MODEL_NAME, "dim": DIM, "max_tokens": self.max_tokens,
                "mode": self._mode, "model_sha256": sha(onnx), "tokenizer_sha256": sha(tokj)}

    def encode(self, texts: list[str]) -> np.ndarray:
        if self._sess is None:
            raise Unavailable(self._mode)
        encs = self._tok.encode_batch(texts)
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        att = np.array([e.attention_mask for e in encs], dtype=np.int64)
        tt = np.array([e.type_ids for e in encs], dtype=np.int64)
        out = self._sess.run(None, {"input_ids": ids, "attention_mask": att, "token_type_ids": tt})
        tok_emb = np.asarray(out[0])                      # (B, T, 384)
        mask = att[..., None].astype(np.float32)
        summed = (tok_emb * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        vec = summed / counts                             # mean pooling
        vec /= np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-9, None)
        return vec.astype(np.float32)
