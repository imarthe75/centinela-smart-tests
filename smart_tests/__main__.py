"""Entry point. All input (secrets included) comes as ONE JSON document on stdin; nothing secret is accepted in argv or env.

  {"command": "explore" | "run" | "inspect" | "ci-report",
   "secrets": {"vault_addr": ..., "vault_token": ..., "vault_namespace": ..., "ingest_url": ..., "ingest_token": ...},
   "args": {...}}

The LAST line of stdout is the JSON result; logs go to stderr.
"""
import json
import logging
import sys
from pathlib import Path

from centinela_core import test_credentials as tc


def _vault(secrets):
    import hvac
    client = hvac.Client(url=secrets.get("vault_addr", ""), token=secrets.get("vault_token", ""), timeout=15)
    if not client.is_authenticated():
        raise SystemExit("Vault no disponible o token inválido")
    tc.configure(namespace=secrets.get("vault_namespace") or None, client_factory=lambda: client)
    return client


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    doc = json.load(sys.stdin)
    cmd, secrets, args = doc.get("command"), doc.get("secrets") or {}, doc.get("args") or {}
    out_dir = Path(args.get("out_dir", "/out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    if cmd == "inspect":
        from smart_tests import package
        pkg = package.load(args["package"], args.get("cycle", "c1"))
        kinds = {}
        for c in pkg.cases:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        result = {"cases": len(pkg.cases), "by_kind": kinds, "sheets": sorted(pkg.data), "uat_docx": bool(pkg.uat_docx),
                  "requirements": sorted({c.rq for c in pkg.cases if c.rq})}
    elif cmd == "explore":
        _vault(secrets)
        from smart_tests.explore import run_explore
        profile = tc.get_profile(args["asset"], args["profile"])
        result = run_explore(profile, args.get("steps", []), out_dir)
    elif cmd == "run":
        _vault(secrets)
        from smart_tests.runner import run
        result = run(args, secrets, out_dir)
    elif cmd == "ci-report":
        # {"asset": ..., "project": ..., "ref": "<rama o tag>", "commit": "<sha>", "pipeline": "<id o URL>", "path": "/ci"}
        from smart_tests import ci_report, ingest
        summary = ci_report.summarize_dir(args.get("path", "/ci"))
        run_meta = {k: str(args.get(k) or "")[:200] for k in ("project", "ref", "commit", "pipeline")}
        (out_dir / "ci_report.json").write_text(json.dumps({"run": run_meta, "summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {"summary": summary, "ingest": ingest.send_ci(summary, args["asset"], secrets, run_meta)}
    else:
        raise SystemExit(f"comando desconocido: {cmd}")
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
