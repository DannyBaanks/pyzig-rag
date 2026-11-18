#!/usr/bin/env sh
# Descarga el modelo de embeddings local (una sola vez) y verifica SHA-256.
# Sin red: el corpus y el indice siguen funcionando en modo lexical declarado.
set -eu
DIR="$(cd "$(dirname "$0")/.." && pwd)/var/models/all-MiniLM-L6-v2"
BASE="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"
mkdir -p "$DIR/onnx"
for f in tokenizer.json onnx/model.onnx; do
  [ -s "$DIR/$f" ] || curl -sSL --retry 3 -o "$DIR/$f" "$BASE/$f"
done
cd "$DIR"
sha256sum -c SHA256SUMS.txt
echo "modelo listo en $DIR"
