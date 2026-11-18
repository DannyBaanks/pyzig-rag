#!/usr/bin/env python3
"""Oracle for pyzig-fuzz: executes Python reference implementations."""

import sys
import binascii
import subprocess
import json
import tempfile
import os

def decode_fields(data):
    """Decode packed fields: [u32 len][data]..."""
    fields = []
    pos = 0
    while pos + 4 <= len(data):
        length = int.from_bytes(data[pos:pos+4], 'little')
        pos += 4
        if pos + length > len(data):
            break
        fields.append(data[pos:pos+length])
        pos += length
    return fields

def encode_observation(status, payload):
    """Encode observation as packed fields: status + payload"""
    out = len(status).to_bytes(4, 'little') + status.encode()
    out += len(payload).to_bytes(4, 'little') + payload
    return out

def run_argv(fields):
    """Execute argv case: fields are [program, arg1, arg2, ...]"""
    if not fields:
        return b"", b"", 1
    args = [f.decode('utf-8', errors='replace') for f in fields]
    try:
        result = subprocess.run(args, capture_output=True, timeout=5)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return b"", str(e).encode(), 1

def run_kv(fields):
    """Execute kv parsing case - join all fields with newline"""
    text = b'\n'.join(fields).decode('utf-8', errors='replace')
    result = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            result.append(f"{k.strip()}={v.strip()}")
    return '\n'.join(result).encode(), b"", 0

def run_read(fields):
    """Execute read case: fields are [path, content, limit]"""
    if len(fields) < 3:
        return b"", b"", 1
    path = fields[0].decode('utf-8', errors='replace')
    content = fields[1]
    limit = int(fields[2].decode('utf-8', errors='replace'))
    
    with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
        f.write(content)
        temp_path = f.name
    try:
        with open(temp_path, 'rb') as f:
            data = f.read(limit)
        return data, b"", 0
    except FileNotFoundError:
        return b"", b"", 1
    except Exception as e:
        return b"", str(e).encode(), 1
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def run_write(fields):
    """Execute write case: fields are [mode, pre_content, data]"""
    import tempfile
    if len(fields) < 3:
        return b"", b"", 1
    mode = fields[0].decode('utf-8', errors='replace')
    pre_content = fields[1]
    data = fields[2]
    
    with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
        f.write(pre_content)
        temp_path = f.name
    try:
        if mode == '1':
            with open(temp_path, 'wb') as f:
                f.write(data)
        else:
            with open(temp_path, 'ab') as f:
                f.write(data)
        with open(temp_path, 'rb') as f:
            result = f.read()
        return result, b"", 0
    except Exception as e:
        return b"", str(e).encode(), 1
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def run_exists(fields):
    """Execute exists case"""
    import os
    if not fields:
        return b"", b"", 1
    kind = fields[0].decode('utf-8', errors='replace')
    path = fields[1].decode('utf-8', errors='replace') if len(fields) > 1 else "x"
    
    if kind == '0':
        with open(path, 'w') as f:
            f.write('')
        result = b"yes"
    elif kind == '1':
        result = b"missing"
    else:
        os.makedirs(path, exist_ok=True)
        result = b"dir"
    return result, b"", 0

def run_splitfmt(fields):
    """Execute split/format case"""
    if len(fields) < 5:
        return b"", b"", 1
    sep = fields[0].decode('utf-8', errors='replace')
    text = fields[1].decode('utf-8', errors='replace')
    mac = fields[2].decode('utf-8', errors='replace')
    ip = fields[3].decode('utf-8', errors='replace')
    width = int(fields[4].decode('utf-8', errors='replace'))
    
    parts = [p.strip() for p in text.split(sep) if p.strip()]
    result = f"{mac:<{width}}|{ip}"
    return result.encode(), b"", 0

def run_sleep(fields):
    """Execute sleep case"""
    import time
    if not fields:
        return b"", b"", 1
    ms = int(fields[0].decode('utf-8', errors='replace'))
    time.sleep(ms / 1000.0)
    return b"ok", b"", 0

def run_env(fields):
    """Execute env case"""
    import os
    if not fields:
        return b"", b"", 1
    key = fields[0].decode('utf-8', errors='replace')
    val = os.environ.get(key)
    if val is None:
        return b"null", b"", 0
    return val.encode(), b"", 0

def run_spawn(fields):
    """Execute spawn case"""
    if not fields:
        return b"", b"", 1
    args = [f.decode('utf-8', errors='replace') for f in fields[1:]]
    try:
        result = subprocess.run(args, capture_output=True, timeout=5)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return b"", str(e).encode(), 1

def run_stdout(fields):
    """Execute stdout case"""
    if len(fields) < 2:
        return b"", b"", 1
    mode = fields[0].decode('utf-8', errors='replace')
    msg = fields[1]
    if mode == '1':
        sys.stdout.buffer.write(msg)
        sys.stdout.buffer.flush()
    else:
        sys.stderr.buffer.write(msg)
        sys.stderr.buffer.flush()
    return b"ok", b"", 0

def run_pipe(fields):
    """Execute pipe case"""
    if not fields:
        return b"", b"", 1
    data = fields[0]
    return data, b"", 0

SCHEMA_HANDLERS = {
    'argv': run_argv,
    'kv': run_kv,
    'read': run_read,
    'write': run_write,
    'exists': run_exists,
    'splitfmt': run_splitfmt,
    'sleep': run_sleep,
    'env': run_env,
    'spawn': run_spawn,
    'stdout': run_stdout,
    'pipe': run_pipe,
}

def main():
    if len(sys.argv) < 7:
        print("Usage: oracle.py --schema <schema> --cases <cases.hexl> --obs <obs.zigl>")
        sys.exit(1)
    
    schema = None
    cases_file = None
    obs_file = None
    for i, arg in enumerate(sys.argv):
        if arg == '--schema' and i + 1 < len(sys.argv):
            schema = sys.argv[i + 1]
        elif arg == '--cases' and i + 1 < len(sys.argv):
            cases_file = sys.argv[i + 1]
        elif arg == '--obs' and i + 1 < len(sys.argv):
            obs_file = sys.argv[i + 1]
    
    if not schema or not cases_file or not obs_file:
        print("Missing required arguments")
        sys.exit(1)
    
    handler = SCHEMA_HANDLERS.get(schema)
    if not handler:
        print(f"Unknown schema: {schema}")
        sys.exit(1)
    
    with open(cases_file, 'r') as f:
        lines = [line.strip() for line in f if line.strip()]
    
    with open(obs_file, 'w') as out_f:
        for line in lines:
            data = binascii.unhexlify(line)
            fields = decode_fields(data)
            stdout, stderr, code = handler(fields)
            payload = stdout + stderr
            status = "ok" if code == 0 else "err"
            obs = encode_observation(status, payload)
            out_f.write(f"{status}\t{binascii.hexlify(obs).decode()}\n")

if __name__ == '__main__':
    main()
