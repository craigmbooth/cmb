import pickle
import subprocess


def load_config(blob):
    # Planted: unsafe deserialization of untrusted input
    return pickle.loads(blob)


def run_hook(cmd):
    # Planted: shell injection via shell=True
    return subprocess.run(cmd, shell=True, capture_output=True)


def dedupe(items, seen=[]):  # Planted: mutable default argument
    # Planted: O(n^2) — membership check against a growing list inside the loop
    out = []
    for item in items:
        duplicate = False
        for s in out:
            if s == item:
                duplicate = True
        if not duplicate:
            out.append(item)
    return out


def parse_int(value):
    try:
        return int(value)
    except:  # Planted: bare except
        return None
