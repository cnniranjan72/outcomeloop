"""One command to reproduce the evaluation from a clean checkout, with an honest status for every step.

    python scripts/evaluate.py                 # prerequisites, tests, public_01 + public_02 (fresh runs), verify, evidence
    python scripts/evaluate.py --slow --load   # also the slow tests and the public_03 load test (~15 min more)

Every step is PASSED, FAILED, SKIPPED (opt-in step not requested), INCOMPLETE (ran but its output is missing or
partial) or NOT APPLICABLE. Nothing is read from earlier runs: the scenarios run fresh, then the grader and the
verifier read what this run produced. Writes reports/EVALUATION.md; exits 1 if any step FAILED, 2 if INCOMPLETE.
No environment values are recorded beyond versions, OS and the commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSED, FAILED, SKIPPED, INCOMPLETE, NA = "PASSED", "FAILED", "SKIPPED", "INCOMPLETE", "NOT APPLICABLE"


def sh(cmd: list[str], env=None, timeout=7200) -> tuple[int, str, float]:
    t = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONUTF8": "1", **(env or {})}, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t
    except (OSError, subprocess.TimeoutExpired) as e:
        return 99, str(e), time.time() - t


def bash() -> str | None:
    """A real bash: Git Bash on Windows (the System32 `bash.exe` is the WSL launcher, which may have no distro)."""
    cands = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"] if os.name == "nt" else []
    cands.append(shutil.which("bash") or "")
    for b in cands:
        if b and Path(b).exists() and "system32" not in b.lower():
            return b
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slow", action="store_true")
    ap.add_argument("--load", action="store_true")
    a = ap.parse_args()
    py = sys.executable
    steps: list[tuple[str, str, str, float]] = []
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "src", "run.sh"], cwd=ROOT, capture_output=True,
                                text=True).stdout.strip())
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    # 1. prerequisites
    rc, out, d = sh([py, "-c", "import httpx, numpy, yaml; print(httpx.__version__, numpy.__version__)"])
    b = bash()
    ok = rc == 0 and b is not None and sys.version_info >= (3, 11)
    steps.append(("prerequisites", PASSED if ok else FAILED,
                  f"python {platform.python_version()}, httpx/numpy {out.strip()}, bash {'found' if b else 'MISSING'}", d))
    if not ok:
        return finish(steps, head, dirty, started)

    # 2. tests
    rc, out, d = sh([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    env={"OUTCOMELOOP_SLOW": "1"} if a.slow else None)
    last = (out.strip().splitlines() or [""])[-1]
    steps.append(("tests" + (" (incl. slow)" if a.slow else ""), PASSED if rc == 0 else FAILED, last, d))

    # 3. public scenarios, fresh runs, then the simulator's own grader
    for name, port in (("public_01_dev", 8751), ("public_02_incidents", 8752)):
        rc, out, d = sh([b, "scripts/run_scenario.sh", name, str(port)])
        rep = ROOT / "reports" / f"{name}.md"
        if rc != 0:
            steps.append((f"scenario {name}", FAILED, f"run_scenario.sh exit {rc}: {out.strip()[-200:]}", d))
            continue
        txt = rep.read_text(encoding="utf-8") if rep.exists() and rep.stat().st_mtime > time.time() - d - 5 else ""
        row = next((l for l in txt.splitlines() if l.startswith("| ALL |")), None)
        if not row:
            steps.append((f"scenario {name}", INCOMPLETE, "run finished but no fresh grade report", d))
            continue
        c = [x.strip() for x in row.strip("|").split("|")]
        ap_ = re.search(r"(\d+ applied — [^\n]*)", txt)
        steps.append((f"scenario {name}", PASSED,
                      f"conclusion rate {c[2]} vs no-op baseline; {ap_.group(1) if ap_ else ''}", d))
        # 4. verify the audit store this run produced
        rc, out, dv = sh([py, "-m", "outcomeloop", "--db", f"state/{name}.db", "verify"], env={"PYTHONPATH": "src"})
        overall = next((l for l in out.splitlines() if l.startswith("overall:")), "no verdict")
        steps.append((f"verify {name} store", {0: PASSED, 2: INCOMPLETE}.get(rc, FAILED), overall, dv))

    # 5. load test (opt-in)
    if a.load:
        rc, out, d = sh([b, "scripts/load_test.sh", "8753"])
        rep = ROOT / "reports" / "public_03.md"
        txt = rep.read_text(encoding="utf-8") if rep.exists() else ""
        mem = re.search(r"peak controller memory[^|]*\| ([^|]+)\|", txt)
        live = re.search(r"live events ingested[^|]*\| ([^|]+)\|", txt)
        steps.append(("load test public_03", PASSED if rc == 0 and mem else FAILED,
                      f"{live.group(1).strip() if live else '?'}; peak memory {mem.group(1).strip() if mem else '?'}", d))
    else:
        steps.append(("load test public_03", SKIPPED, "opt-in: --load (about 10 minutes)", 0.0))

    # 6. evidence files a reviewer is pointed to
    need = ["SUBMISSION.md", "reports/crash_recovery.md", "reports/robustness.md", "reports/scaling.md",
            "reports/memory.md", "evidence/README.md", "evidence/RESULTS.md", "docs/ADVERSARIAL_TESTING.md"]
    missing = [p for p in need if not (ROOT / p).exists()]
    steps.append(("evidence files present", FAILED if missing else PASSED,
                  f"missing {missing}" if missing else f"{len(need)} files", 0.0))
    steps.append(("crash recovery, robustness suite", NA,
                  "not re-run here (each takes 20-40 min): scripts/crash_recovery.sh, scripts/robustness.sh", 0.0))
    return finish(steps, head, dirty, started)


def finish(steps, head, dirty, started):
    worst = FAILED if any(s[1] == FAILED for s in steps) else INCOMPLETE if any(s[1] == INCOMPLETE for s in steps) \
        else PASSED
    lines = ["# Evaluation run", "",
             f"Started {started}; commit `{head}`{' (uncommitted changes in src/ or run.sh)' if dirty else ''};"
             f" {platform.system()} {platform.release()}, Python {platform.python_version()}. Generated by"
             " `scripts/evaluate.py`; every value below comes from this run.", "",
             "| step | status | result | seconds |", "|---|---|---|---|"]
    lines += [f"| {n} | {st} | {r.replace('|', '/')} | {d:.0f} |" for n, st, r, d in steps]
    lines += ["", f"**Overall: {worst}**"]
    (ROOT / "reports" / "EVALUATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return {PASSED: 0, INCOMPLETE: 2, FAILED: 1}[worst]


if __name__ == "__main__":
    raise SystemExit(main())
