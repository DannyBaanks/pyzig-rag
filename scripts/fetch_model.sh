#!/usr/bin/env sh
# Descarga un modelo de embeddings local (una sola vez) y verifica SHA-256.
# Uso: fetch_model.sh [all-MiniLM-L6-v2 | multilingual-e5-small | paraphrase-multilingual-MiniLM-L12-v2]
# (defecto: $PYZIG_EMBED_MODEL o all-MiniLM-L6-v2). Sin red: el corpus y el
# indice siguen funcionando en modo lexical declarado.
# Si el modelo no tiene SHA256SUMS.txt (primera descarga) se genera: revisalo y
# fijalo en el repo; las descargas posteriores se verifican contra el.
set -eu
NAME="${1:-${PYZIG_EMBED_MODEL:-all-MiniLM-L6-v2}}"
case "$NAME" in
  all-MiniLM-L6-v2) REPO=sentence-transformers/all-MiniLM-L6-v2 ;;
  multilingual-e5-small) REPO=intfloat/multilingual-e5-small ;;
  paraphrase-multilingual-MiniLM-L12-v2) REPO=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 ;;
  *) echo "modelo desconocido: $NAME" >&2; exit 2 ;;
esac
DIR="$(cd "$(dirname "$0")/.." && pwd)/var/models/$NAME"
BASE="https://huggingface.co/$REPO/resolve/main"
mkdir -p "$DIR/onnx"
for f in tokenizer.json onnx/model.onnx; do
  [ -s "$DIR/$f" ] || curl -sSL --retry 3 -o "$DIR/$f" "$BASE/$f"
done
cd "$DIR"
if [ ! -s SHA256SUMS.txt ]; then
  sha256sum tokenizer.json onnx/model.onnx > SHA256SUMS.txt
  echo "AVISO: SHA256SUMS.txt generado (primera descarga); verifica contra el origen"
fi
sha256sum -c SHA256SUMS.txt
echo "modelo listo en $DIR"
