#!/usr/bin/env python3
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pyzig.gates import run_gates

if __name__ == "__main__":
    for r in run_gates():
        print(json.dumps(r, ensure_ascii=False))
