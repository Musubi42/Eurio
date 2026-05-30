"""Driver one-shot passe prix Numista — séquentiel par pays, garde quota.

Ordre = gros catalogues d'abord (DE…BG). Avant chaque pays : check quota
KeyManager ; si épuisé → stop propre. Refetch SANS --skip-prices (méta en
cache = 0 call, seuls les /prices consomment). Idempotent/reprenable.
Log append dans state/_price_pass.log.
"""
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path
from referential.numista_keys import KeyManager

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "state" / "_price_pass.log"

# Ordre descendant par nb d'issues (= coût price calls), batches de 7.
ORDER = [
    ["DE", "LU", "IT", "FR", "FI", "ES", "BE"],          # batch 1
    ["PT", "GR", "NL", "SM", "MT", "VA", "SI"],          # batch 2
    ["SK", "AT", "IE", "CY", "LT", "LV", "AD"],          # batch 3
    ["MC", "EE", "HR", "BG"],                             # batch 4
]

def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")

def remaining() -> int:
    return sum(s["remaining"] for s in KeyManager().status())

def main() -> int:
    log(f"=== START price pass — quota {remaining()} ===")
    stopped = False
    for bi, batch in enumerate(ORDER, 1):
        if stopped:
            break
        log(f"--- BATCH {bi}: {' '.join(batch)} ---")
        for c in batch:
            rem = remaining()
            if rem <= 2:
                log(f"STOP: quota épuisé ({rem}) avant {c}")
                stopped = True
                break
            nids = ROOT / "state" / f"{c.lower()}_nids.txt"
            if not nids.exists():
                log(f"{c}: SKIP (pas de {nids.name})")
                continue
            log(f"{c}: start (quota {rem})")
            proc = subprocess.run(
                [sys.executable, "-m", "scripts.refetch_numista_2eur",
                 "--nids-file", str(nids), "--apply"],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            out = proc.stdout + proc.stderr
            # extraire lignes utiles
            calls = prices = errors = "?"
            for ln in out.splitlines():
                s = ln.strip()
                if s.startswith("API calls"):
                    calls = s.split(":")[-1].strip()
                elif "mint_release_prices" in s:
                    prices = s.split()[-1]
                elif s.startswith("Bundles written"):
                    errors = s.split(":")[-1].strip()
            log(f"{c}: done — calls={calls} | prices_rows={prices} | bundles={errors} | quota_now={remaining()}")
    log(f"=== END price pass — quota {remaining()} — stopped={stopped} ===")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
