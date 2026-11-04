# Portable Python runtime (Windows x64)

This folder contains an **official CPython 3.12 embeddable** build for **Windows 64-bit (amd64)** plus the app dependencies from `requirements.txt`.

- Used automatically by `run.bat` — no system Python install required
- Target: Windows 10/11, 64-bit only
- Do not commit personal machine paths, scan logs, or local `__pycache__` here

Rebuild (maintainers):

```bat
REM from repo root, after deleting runtime\python
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_portable_python.ps1
```
