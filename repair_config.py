"""Offline, fail-closed compatibility repair. Never reads session data."""
import copy
import ctypes
import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
from urllib.parse import urlsplit


def proposal(raw):
    text = raw.decode('utf-8-sig')
    config = tomllib.loads(text)
    providers = config.get('model_providers', {})
    if 'custom' in providers:
        return None, 'alias_present'
    selected = config.get('model_provider', '')
    if not isinstance(selected, str) or not re.fullmatch(r'cc-switch[-\w]*', selected):
        return None, 'blocked_provider'
    provider = providers.get(selected)
    if not isinstance(provider, dict):
        return None, 'blocked_provider'
    url = urlsplit(provider.get('base_url', ''))
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or
            url.port != 15721 or url.path.rstrip('/') != '/v1' or
            url.username or url.password or url.query or url.fragment or
            provider.get('wire_api') != 'responses'):
        return None, 'blocked_route'
    # Only accept a simple standalone table; semantic comparison below catches
    # nested tables, multiline strings, and unexpected TOML constructs.
    pattern = r'(?m)^\[model_providers\.' + re.escape(selected) + r'\][ \t]*(?:#[^\r\n]*)?\r?$'
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        return None, 'blocked_table_shape'
    rest = text[matches[0].end():]
    next_header = re.search(r'(?m)^\s*\[', rest)
    body = rest[:next_header.start()] if next_header else rest
    candidate = raw + ('\n[model_providers.custom]' + body + '\n').encode('utf-8')
    expected = copy.deepcopy(config)
    expected['model_providers']['custom'] = copy.deepcopy(provider)
    if tomllib.loads(candidate.decode('utf-8-sig')) != expected:
        return None, 'blocked_table_shape'
    return candidate, 'repaired'


def repair(path):
    path = Path(path)
    # Deny concurrent in-place writers while allowing atomic replacement.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1 | 4, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return 'blocked_file_busy'
    temp = None
    try:
        raw = path.read_bytes()
        candidate, status = proposal(raw)
        if candidate is None:
            return status
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = path.with_name(path.name + '.startup-repair-' + stamp + '.bak')
        with backup.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.startup-repair-', delete=False) as stream:
            temp = Path(stream.name)
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != raw:
            return 'blocked_config_changed'
        # Windows replacement requires releasing the read handle first.
        kernel.CloseHandle(handle)
        handle = None
        if path.read_bytes() != raw:
            return 'blocked_config_changed'
        os.replace(temp, path)
        return status
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
        if temp is not None and temp.exists():
            temp.unlink()


if __name__ == '__main__':
    import sys
    try:
        result = repair(sys.argv[1])
    except Exception:
        # Never log configuration contents, URLs, credentials or exception text.
        result = 'blocked_check_error'
    print(json.dumps({'status': result}))
    sys.exit(0 if result in ('alias_present', 'repaired') else 2)
