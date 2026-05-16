"""Hardware detection utilities."""

import subprocess
import sys


def detect_gpu() -> tuple[str, float]:
    """Detect GPU using nvidia-smi.

    Returns:
        (gpu_name, vram_gb) — e.g. ("NVIDIA GeForce RTX 4090", 24.0)

    Raises:
        SystemExit: if no GPU is found or nvidia-smi is unavailable.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        print("Error: nvidia-smi not found. Is the NVIDIA driver installed?", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.TimeoutExpired:
        print("Error: nvidia-smi timed out.", file=sys.stderr)
        raise SystemExit(1)

    if result.returncode != 0:
        print("Error: nvidia-smi failed.", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(1)

    output = result.stdout.strip()
    if not output:
        print("Error: No NVIDIA GPU detected.", file=sys.stderr)
        raise SystemExit(1)

    # Parse first line (primary GPU)
    line = output.splitlines()[0].strip()
    parts = [p.strip() for p in line.rsplit(",", 1)]
    if len(parts) != 2:
        print(f"Error: Could not parse nvidia-smi output: {line}", file=sys.stderr)
        raise SystemExit(1)

    gpu_name = parts[0]
    vram_str = parts[1]

    # Parse VRAM: "4096 MiB" —> MB —> GB
    vram_mb = float(vram_str.split()[0])
    vram_gb = vram_mb / 1024.0

    return gpu_name, vram_gb
