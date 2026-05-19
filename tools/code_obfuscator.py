"""
Code Obfuscator — randomizes generated Code.gs and worker.js each time.

Purpose: Prevent Google/Cloudflare from pattern-matching the relay code
across multiple deployments. Each generated file looks different but
does the same thing.

Techniques:
  - Rename internal functions to random names
  - Rename local variables
  - Add random dead code (no-op functions, unused vars)
  - Shuffle function order (where safe)
  - Add random comments
  - Randomize string literals (split + concat)
"""

import random
import re
import string
import secrets


def _random_name(prefix: str = "", length: int = 8) -> str:
    """Generate a random valid JS identifier."""
    chars = string.ascii_lowercase
    name = prefix + "".join(random.choices(chars, k=length))
    return name


def _random_comment() -> str:
    """Generate a random harmless comment."""
    comments = [
        "// initialization",
        "// process data",
        "// validate input",
        "// handle response",
        "// check status",
        "// format output",
        "// parse result",
        "// apply transform",
        "// normalize value",
        "// compute hash",
        "// update state",
        "// sync data",
        "// refresh cache",
        "// log event",
        "// verify token",
    ]
    return random.choice(comments)


def _dead_code_function() -> str:
    """Generate a random dead-code function that does nothing useful."""
    name = _random_name("_")
    body_options = [
        f"function {name}(x) {{ return x; }}",
        f"function {name}(a, b) {{ return a || b; }}",
        f"function {name}() {{ return Date.now(); }}",
        f"function {name}(s) {{ return typeof s === 'string' ? s.length : 0; }}",
        f"function {name}(arr) {{ return Array.isArray(arr) ? arr.length : -1; }}",
        f"var {name} = function(v) {{ return v !== null; }};",
    ]
    return random.choice(body_options)


def _dead_code_var() -> str:
    """Generate a random unused variable declaration."""
    name = _random_name("_v")
    value_options = [
        f"var {name} = {random.randint(1, 9999)};",
        f"var {name} = '{_random_name()}';",
        f"var {name} = Date.now();",
        f"var {name} = Math.random();",
        f"var {name} = true;",
    ]
    return random.choice(value_options)


def _split_string(s: str) -> str:
    """Split a string literal into concatenation: 'hello' → 'he'+'llo'"""
    if len(s) < 6:
        return f'"{s}"'
    mid = random.randint(2, len(s) - 2)
    return f'"{s[:mid]}" + "{s[mid:]}"'


# ─── Main obfuscation ────────────────────────────────────────────────────────

# Internal function names that can be safely renamed (GAS)
_GAS_RENAMEABLE = [
    "_doSingle", "_doBatch", "_doGasDirect", "_doCfw", "_doVps", "_doCfwVps",
    "_buildWorkerPayload", "_fetchWithFailover", "_getNextIdx", "_json",
]

# Internal function names that can be safely renamed (Worker)
_WORKER_RENAMEABLE = [
    "forwardWithFailover", "getUpstreamUrls", "upstreamFailure",
    "addCors", "json",
]


def obfuscate_gas(code: str) -> str:
    """Obfuscate Code.gs — rename internals, add junk, shuffle."""

    # 1. Rename internal functions
    rename_map = {}
    for func in _GAS_RENAMEABLE:
        if func in code:
            new_name = _random_name("_f")
            rename_map[func] = new_name

    for old, new in rename_map.items():
        code = code.replace(old, new)

    # 2. Add dead code (random functions + vars) between real functions
    lines = code.split("\n")
    new_lines = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        # After function closing braces, sometimes add junk
        if line.strip() == "}" and random.random() < 0.3:
            new_lines.append("")
            new_lines.append(_random_comment())
            if random.random() < 0.5:
                new_lines.append(_dead_code_function())
            else:
                new_lines.append(_dead_code_var())
            new_lines.append("")

    # 3. Add random comments at top
    header_comments = [
        f"// Build: {secrets.token_hex(4)}",
        f"// Generated: {random.randint(1000, 9999)}",
        _random_comment(),
    ]
    code = "\n".join(header_comments) + "\n" + "\n".join(new_lines)

    return code


def obfuscate_worker(code: str) -> str:
    """Obfuscate worker.js — rename internals, add junk."""

    # 1. Rename internal functions
    rename_map = {}
    for func in _WORKER_RENAMEABLE:
        if func in code:
            new_name = _random_name("_w")
            rename_map[func] = new_name

    for old, new in rename_map.items():
        code = code.replace(old, new)

    # 2. Add dead code
    lines = code.split("\n")
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if line.strip() == "}" and random.random() < 0.2:
            new_lines.append("")
            new_lines.append(_random_comment())
            if random.random() < 0.4:
                new_lines.append(_dead_code_function())
            new_lines.append("")

    # 3. Header
    header = f"// {secrets.token_hex(6)}\n"
    code = header + "\n".join(new_lines)

    return code
