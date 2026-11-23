"""Check tracked release files without showing any matched secret."""

import re
import subprocess
from pathlib import Path


PRIVATE_MATERIAL = re.compile(
    rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"
    rb"|(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"
    rb"|(?:AKIA|ASIA)[A-Z0-9]{16}"
)
ARTIFACT_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12", ".crt",
    ".env", ".sha256",
}


def main():
    root = Path(__file__).resolve().parents[1]
    listed = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    suspicious = []
    for entry in listed.decode().split("\0"):
        if not entry:
            continue
        path = root / entry
        if path.resolve() != path or not path.is_file():
            suspicious.append(entry)
            continue
        name = path.name.lower()
        if (path.suffix.lower() in ARTIFACT_SUFFIXES or
                name.endswith(("-wal", "-shm", "-journal")) or
                (name.startswith(".env.") and name != ".env.example")):
            suspicious.append(entry)
            continue
        if path.suffix.lower() in {".png", ".pdf"}:
            continue
        if PRIVATE_MATERIAL.search(path.read_bytes()):
            suspicious.append(entry)
    if suspicious:
        raise SystemExit("Review potentially private tracked files:\n" + "\n".join(suspicious))
    print("Tracked release files passed private-artifact and credential-pattern checks.")


if __name__ == "__main__":
    main()
