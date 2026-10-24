"""使い方: python tools/set_version.py 1.2.3  -> core/version.py の __version__ を書き換える"""
import re
import sys
from pathlib import Path

if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
    sys.exit("version must look like 1.2.3")
p = Path(__file__).resolve().parent.parent / "core" / "version.py"
s = p.read_text(encoding="utf-8")
s2, n = re.subn(r'__version__ = "[^"]*"', f'__version__ = "{sys.argv[1]}"', s)
if n != 1:
    sys.exit("version line not found")
p.write_text(s2, encoding="utf-8")
print("version ->", sys.argv[1])
