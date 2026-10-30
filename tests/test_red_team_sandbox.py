import pytest
from kintsugi.sandbox import verify_code_safety, SecurityViolationError


@pytest.mark.parametrize(
    "attack_code,func_name,expected_violation",
    [
        (
            "def exploit():\n    import pathlib\n    return pathlib.Path('/etc/passwd').read_text()\n",
            "exploit",
            "Forbidden module import: 'pathlib'",
        ),
        (
            "def exploit():\n    import io\n    return io.FileIO('test.txt')\n",
            "exploit",
            "Forbidden module import: 'io'",
        ),
        (
            "def exploit():\n    import gc\n    return gc.get_objects()\n",
            "exploit",
            "Forbidden module import: 'gc'",
        ),
        (
            "def exploit():\n    import inspect\n    return inspect.currentframe()\n",
            "exploit",
            "Forbidden module import: 'inspect'",
        ),
        (
            "def exploit():\n    import socket\n    return socket.socket()\n",
            "exploit",
            "Forbidden module import: 'socket'",
        ),
        (
            "def exploit():\n    import urllib.request\n    return urllib.request.urlopen('http://evil.com')\n",
            "exploit",
            "Forbidden module import: 'urllib.request'",
        ),
        (
            "def exploit():\n    import smtplib\n    return smtplib.SMTP()\n",
            "exploit",
            "Forbidden module import: 'smtplib'",
        ),
        (
            "def exploit():\n    import types\n    return types.FunctionType\n",
            "exploit",
            "Forbidden module import: 'types'",
        ),
        (
            "def exploit():\n    import multiprocessing\n    return multiprocessing.Process()\n",
            "exploit",
            "Forbidden module import: 'multiprocessing'",
        ),
        (
            "def exploit():\n    return ().__class__.__bases__[0].__subclasses__()\n",
            "exploit",
            "Forbidden access to sensitive dunder attribute: '__class__'",
        ),
        (
            "def exploit(tb):\n    return tb.tb_frame.f_globals\n",
            "exploit",
            "Forbidden access to reflection attribute: 'tb_frame'",
        ),
        (
            "def exploit(frame):\n    return frame.f_globals['__builtins__']\n",
            "exploit",
            "Forbidden access to reflection attribute: 'f_globals'",
        ),
        (
            "def exploit(coro):\n    return coro.cr_frame\n",
            "exploit",
            "Forbidden access to reflection attribute: 'cr_frame'",
        ),
        (
            "def exploit(gen):\n    return gen.gi_frame\n",
            "exploit",
            "Forbidden access to reflection attribute: 'gi_frame'",
        ),
        (
            "def exploit():\n    import unknown_external_lib\n    return 42\n",
            "exploit",
            "Module 'unknown_external_lib' is not in allowed imports list",
        ),
    ],
)
def test_red_team_attack_payloads_rejected(attack_code, func_name, expected_violation):
    with pytest.raises(SecurityViolationError) as exc_info:
        verify_code_safety(attack_code, func_name)
    assert expected_violation in str(exc_info.value)


def test_benign_allowed_modules_pass():
    safe_code = """
def safe_calculator(text: str) -> dict:
    import re
    import json
    import math
    import datetime
    from collections import Counter
    import itertools

    nums = [int(n) for n in re.findall(r'\\d+', text)]
    return {
        "count": len(nums),
        "sum": math.fsum(nums),
        "freq": dict(Counter(nums)),
    }
"""
    # Safe imports must pass verification without error
    tree = verify_code_safety(safe_code, "safe_calculator")
    assert tree is not None
