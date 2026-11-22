"""Megvárja, amíg a háttérben futó letöltés (download_full.log) végez, majd elindítja a Fázis 2
mintán belüli számolást. Közben a gép nem alszik el (lásd btcpaper/awake.py)."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from btcpaper.awake import keep_awake  # noqa: E402

print("ébren tartás:", keep_awake(), flush=True)
log = ROOT / "download_full.log"
while True:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    if "exit=" in text:
        break
    time.sleep(30)
if "exit=0" not in text or "KÉSZ" not in text:
    print("A letöltés hibával állt le:\n" + text[-2000:], flush=True)
    sys.exit(1)
print("Letöltés kész, indul a számolás:", time.strftime("%H:%M:%S"), flush=True)
workers = sys.argv[1] if len(sys.argv) > 1 else "6"
r = subprocess.run([sys.executable, str(ROOT / "scripts" / "phase2.py"), "insample", "--workers", workers], cwd=ROOT)
print("Számolás vége:", time.strftime("%H:%M:%S"), "kilépési kód", r.returncode, flush=True)
sys.exit(r.returncode)
