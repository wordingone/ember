#!/usr/bin/env python3
"""redact_receipt_paths.py -- transform pristine receipts by replacing local paths with tokens."""

import json
import hashlib
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

REDACTIONS = [
    (r"B:/M/avir/eli/state/ember-eng/shards-v0", "<LOCAL_SHARD_STORE>/shards-v0"),
    (r"B:/M/ember/scripts", "<REPO_ROOT>/scripts"),
]

def sha256_bytes(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def redact_value(value):
    if not isinstance(value, str):
        return value
    result = value
    for original, token in REDACTIONS:
        if original in result:
            result = result.replace(original, token)
    return result

def redact_receipt(data):
    """Recursively redact paths in receipt structure."""
    if isinstance(data, dict):
        return {k: redact_receipt(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_receipt(item) for item in data]
    elif isinstance(data, str):
        return redact_value(data)
    else:
        return data

def main():
    if len(sys.argv) != 3:
        sys.stderr.write(f"Usage: {sys.argv[0]} <input-pristine.json> <output-redacted.json>\n")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    
    # Read pristine bytes
    with open(input_path, 'rb') as f:
        pristine_bytes = f.read()
    
    pristine_sha = sha256_bytes(pristine_bytes)
    
    # Parse and redact
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    redacted_data = redact_receipt(data)
    
    # Track which fields were redacted
    redacted_fields = []
    for path_original, path_token in REDACTIONS:
        if path_original in pristine_bytes.decode('utf-8', errors='replace'):
            redacted_fields.append(path_original)
    
    # Add redaction block
    redacted_data['redaction'] = {
        'redacted_fields': redacted_fields,
        'original_sha256': pristine_sha,
        'reason': 'public-repo name policy (founder-local paths)',
        'redaction_ts': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'transformation': 'scripts/redact_receipt_paths.py',
    }
    
    # Write redacted JSON with atomic write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix('.tmp')
    with open(temp_path, 'w', encoding='utf-8', newline='') as f:
        json.dump(redacted_data, f, indent=2, sort_keys=False)
        f.write('\n')
    temp_path.replace(output_path)
    
    sys.stdout.write(f"Redacted: {input_path} -> {output_path}\n")
    sys.stdout.write(f"  Original SHA256: {pristine_sha}\n")
    sys.stdout.write(f"  Redacted SHA256: {sha256_bytes(open(output_path, 'rb').read())}\n")

if __name__ == "__main__":
    main()
