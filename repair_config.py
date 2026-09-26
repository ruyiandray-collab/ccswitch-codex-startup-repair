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
    """Mirror the selected route under both historical thread provider IDs.

    Never infer the route from an unselected table or an old backup.
    """
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    text = raw[len(bom):].decode('utf-8')
    config = tomllib.loads(text)
    providers = config.get('model_providers', {})
    selected = config.get('model_provider', '')
    known = ('custom', 'cc-switch-official')
    if selected not in known or not isinstance(providers, dict):
        return None, 'blocked_provider'
    source = providers.get(selected)
    if not isinstance(source, dict):
        return None, 'blocked_provider'
    url = urlsplit(source.get('base_url', ''))
    if (url.scheme not in ('http', 'https') or not url.hostname or
            url.username or url.password or source.get('wire_api') != 'responses'):
        return None, 'blocked_route'
    target = next(key for key in known if key != selected)
    if providers.get(target) == source:
        return None, 'alias_present'

    def span(name):
        key = re.escape(name)
        pattern = r'(?m)^[ \t]*\[model_providers\.(?:' + key + r'|"' + key + r'"|\x27' + key + r'\x27)\][ \t]*(?:#[^\r\n]*)?\r?$'
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            return None
        match = matches[0]
        following = re.search(r'(?m)^[ \t]*\[', text[match.end():])
        end = match.end() + following.start() if following else len(text)
        return match.start(), match.end(), end

    source_span = span(selected)
    if source_span is None:
        return None, 'blocked_table_shape'
    body = text[source_span[1]:source_span[2]]
    replacement = '[model_providers.' + target + ']' + body + '\n'
    exists = target in providers
    if exists:
        target_span = span(target)
        if target_span is None:
            return None, 'blocked_table_shape'
        candidate_text = text[:target_span[0]] + replacement + text[target_span[2]:]
    else:
        candidate_text = text + '\n' + replacement
    expected = copy.deepcopy(config)
    expected['model_providers'][target] = copy.deepcopy(source)
    try:
        parsed = tomllib.loads(candidate_text)
    except tomllib.TOMLDecodeError:
        return None, 'blocked_table_shape'
    if parsed != expected:
        return None, 'blocked_table_shape'
    return bom + candidate_text.encode('utf-8'), ('alias_synchronized' if exists else 'repaired')



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
    sys.exit(0 if result in ('alias_present', 'repaired', 'alias_synchronized') else 2)
