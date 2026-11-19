"""Backend de embeddings local (ONNX CPU). Degradacion explicita a lexical.

Modelo seleccionable por `PYZIG_EMBED_MODEL` (o argumento `model=`). El defecto
sigue siendo all-MiniLM-L6-v2. Cada modelo declara su dimension, prefijos de
consulta/pasaje y pooling; los artefactos se verifican con SHA256SUMS.txt.
"""
from __future__ import annotations
import hashlib, os, pathlib
import numpy as np
from .paths import MODELS

DEFAULT_MODEL = "all-MiniLM-L6-v2"
MODEL_NAME = DEFAULT_MODEL      # compat: nombre del defecto
DIM = 384                       # compat: todos los modelos soportados son 384-d
MAX_TOKENS = 256

#: spec por modelo. pooling "mean" = media enmascarada (los tres lo piden).
MODEL_SPECS: dict[str, dict] = {
    "all-MiniLM-L6-v2": {"dim": 384, "pooling": "mean", "query_prefix": "", "passage_prefix": ""},
    "multilingual-e5-small": {"dim": 384, "pooling": "mean",
                              "query_prefix": "query: ", "passage_prefix": "passage: "},
    "paraphrase-multilingual-MiniLM-L12-v2": {"dim": 384, "pooling": "mean",
                                              "query_prefix": "", "passage_prefix": ""},
}

class Unavailable(RuntimeError):
    pass

def selected_model(model: str | None = None) -> str:
    return model or os.environ.get("PYZIG_EMBED_MODEL") or DEFAULT_MODEL

def _sha(p: pathlib.Path) -> str | None:
    h = hashlib.sha256()
    if not p.is_file():
        return None
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def verify_sums(model_dir: pathlib.Path) -> None:
    """Comprueba SHA256SUMS.txt; lanza Unavailable si falta o no coincide."""
    sums = model_dir / "SHA256SUMS.txt"
    if not sums.is_file():
        raise Unavailable(f"SHA256SUMS.txt ausente en {model_dir}")
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        want, rel = line.split(None, 1)
        rel = rel.strip().lstrip("*")
        if _sha(model_dir / rel) != want:
            raise Unavailable(f"SHA-256 no coincide: {rel}")

class Embedder:
    def __init__(self, models_dir: pathlib.Path | None = None, max_tokens: int = MAX_TOKENS,
                 model: str | None = None):
        self.model_name = selected_model(model)
        self.spec = MODEL_SPECS.get(self.model_name)
        self.models_dir = pathlib.Path(models_dir or MODELS) / self.model_name
        self.max_tokens = max_tokens
        self.degraded = False
        self._mode = "unavailable"
        self._sess = None
        self._tok = None
        self._inputs: set[str] = set()
        self._load()

    @property
    def dim(self) -> int:
        return self.spec["dim"] if self.spec else DIM

    def _load(self) -> None:
        onnx = self.models_dir / "onnx" / "model.onnx"
        tokj = self.models_dir / "tokenizer.json"
        try:
            if self.spec is None:
                raise Unavailable(f"modelo desconocido: {self.model_name} "
                                  f"(validos: {', '.join(MODEL_SPECS)})")
            import onnxruntime as ort
            from tokenizers import Tokenizer
            if not onnx.exists() or not tokj.exists():
                raise Unavailable(f"modelo ausente en {self.models_dir}")
            verify_sums(self.models_dir)
            self._sess = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"])
            self._inputs = {i.name for i in self._sess.get_inputs()}
            tok = Tokenizer.from_file(str(tokj))
            tok.no_truncation()
            tok.enable_truncation(self.max_tokens)
            tok.enable_padding(length=None)
            self._tok = tok
            self._mode = "onnx"
        except Exception as e:  # noqa: BLE001
            self.degraded = True
            self._sess = None
            self._mode = f"unavailable: {type(e).__name__}"

    @property
    def mode(self) -> str:
        return self._mode

    def model_meta(self) -> dict:
        onnx = self.models_dir / "onnx" / "model.onnx"
        tokj = self.models_dir / "tokenizer.json"
        return {"model": self.model_name, "dim": self.dim, "max_tokens": self.max_tokens,
                "mode": self._mode, "model_sha256": _sha(onnx), "tokenizer_sha256": _sha(tokj),
                "pooling": (self.spec or {}).get("pooling"),
                "query_prefix": (self.spec or {}).get("query_prefix"),
                "passage_prefix": (self.spec or {}).get("passage_prefix")}

    def encode(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        """kind: 'passage' (documentos, defecto) o 'query'. Aplica el prefijo del modelo."""
        if self._sess is None:
            raise Unavailable(self._mode)
        pre = self.spec["query_prefix" if kind == "query" else "passage_prefix"]
        encs = self._tok.encode_batch([pre + t for t in texts])
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        att = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": att}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)
        out = self._sess.run(None, feed)
        tok_emb = np.asarray(out[0])                      # (B, T, dim)
        mask = att[..., None].astype(np.float32)
        summed = (tok_emb * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        vec = summed / counts                             # mean pooling
        vec /= np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-9, None)
        return vec.astype(np.float32)

    def encode_query(self, texts: list[str]) -> np.ndarray:
        return self.encode(texts, kind="query")
