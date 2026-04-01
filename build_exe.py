"""
Build standalone exe using PyInstaller.

Usage:
    pip install pyinstaller
    python build_exe.py
"""

import subprocess
import sys

def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "sts2-progress-rebuild",
        "rebuild_progress.py",
    ]
    print("Building exe...")
    print(f"  Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("\nDone! Exe is at: dist/sts2-progress-rebuild.exe")

if __name__ == "__main__":
    main()
