"""Preflight check for local setup.

Tests every configured credential and reports pass or fail. It prints **no
secret values** — only whether each one works — so its output is safe to share.

    python check_setup.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

OK = "  [ OK ]"
FAIL = "  [FAIL]"
SKIP = "  [ -- ]"
WARN = "  [WARN]"


def heading(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def _database_hints(error: str, dsn: str) -> list[str]:
    """Turn Supabase's terser connection errors into something actionable."""
    lowered = error.lower()
    hints: list[str] = []

    if "tenant or user not found" in lowered:
        hints += [
            "This means the pooler does not recognise the project. Two causes:",
            "  1. The username must be  postgres.<project-ref>  (not plain 'postgres').",
            "  2. The pooler hostname prefix may be wrong. Regions have both",
            "     aws-0-<region>.pooler.supabase.com and aws-1-<region>...",
            "     Copy the exact string from the dashboard's Connect dialog.",
        ]
    elif "password authentication failed" in lowered:
        hints.append(
            "The password is wrong. Reset it under Settings -> Database -> "
            "Database password, then update DATABASE_URL."
        )
    elif "network is unreachable" in lowered or "connect call failed" in lowered:
        hints += [
            "Host unreachable. If DATABASE_URL points at db.<ref>.supabase.co,",
            "that host is IPv6-only and needs IPv6 connectivity. Use the",
            "transaction pooler (port 6543) instead, which is IPv4.",
        ]
    elif "timeout" in lowered:
        hints.append("Connection timed out. Check firewall rules for outbound 6543.")

    if ":5432" in dsn and "pooler" not in dsn:
        hints.append(
            "NOTE: you are using the direct connection (port 5432). It is "
            "IPv6-only on new projects. Prefer the pooler on port 6543."
        )
    if "pooler" in dsn and ":6543" not in dsn and ":5432" not in dsn:
        hints.append("NOTE: pooler host without an explicit port. Append :6543.")

    return hints


async def main() -> int:
    print("=" * 62)
    print("Pharma R&D Copilot — setup check")
    print("=" * 62)

    failures: list[str] = []
    warnings: list[str] = []

    # ---------------------------------------------------------- config ---
    heading("Configuration")
    try:
        from app.config import get_settings

        settings = get_settings()
        print(f"{OK} backend/.env loaded; all required variables present")
    except Exception as exc:
        print(f"{FAIL} configuration invalid")
        for line in str(exc).splitlines()[:6]:
            print(f"       {line}")
        print("\n  Fix backend/.env, then re-run. Nothing else can be checked yet.")
        return 1

    # -------------------------------------------------------- database ---
    heading("Database")
    try:
        from app import db

        pool = await db.create_pool(settings)
        async with pool.acquire() as conn:
            version = await conn.fetchval("show server_version")
            tables = await conn.fetchval(
                "select count(*) from pg_tables where schemaname = 'public'"
            )
            policies = await conn.fetchval(
                "select count(*) from pg_policies where schemaname = 'public'"
            )
            has_vector = await conn.fetchval(
                "select count(*) from pg_extension where extname = 'vector'"
            )
        print(f"{OK} connected (Postgres {version})")

        if tables >= 17:
            print(f"{OK} schema present ({tables} tables, {policies} RLS policies)")
        else:
            print(f"{FAIL} only {tables} tables found, expected 17")
            print("       Apply supabase/migrations/*.sql in filename order.")
            failures.append("schema incomplete")

        if has_vector:
            print(f"{OK} pgvector installed")
        else:
            print(f"{WARN} pgvector missing (only affects future document RAG)")
            warnings.append("pgvector")
    except Exception as exc:
        print(f"{FAIL} cannot connect: {type(exc).__name__}")
        print(f"       {str(exc)[:200]}")
        for hint in _database_hints(str(exc), str(settings.database_url)):
            print(f"       {hint}")
        failures.append("database")

    # ------------------------------------------------------------ auth ---
    heading("Authentication")
    try:
        from app.auth import describe_jwt_verification

        auth_ok, detail = await describe_jwt_verification(settings)
        print(f"{OK if auth_ok else FAIL} {detail}")
        if not auth_ok:
            failures.append("jwt verification")
    except Exception as exc:
        print(f"{FAIL} auth check failed: {type(exc).__name__}: {exc}")
        failures.append("jwt verification")

    # ---------------------------------------------------------- openai ---
    heading("OpenAI")
    try:
        from app.llm.provider import ModelProvider

        models = ModelProvider(settings)
        model_ok, detail = await models.health_check()
        print(f"{OK if model_ok else FAIL} {detail}")
        if not model_ok:
            print("       Set OPENAI_MODEL_* in backend/.env to models your key can use.")
            failures.append("openai")
        await models.aclose()
    except Exception as exc:
        print(f"{FAIL} {type(exc).__name__}: {str(exc)[:160]}")
        failures.append("openai")

    # ------------------------------------------------------- providers ---
    heading("Literature providers")
    from app.models.records import SearchFilters
    from app.providers.europepmc import EuropePMCProvider
    from app.providers.pubmed import PubMedProvider

    probe = SearchFilters(max_results=1)

    pubmed = PubMedProvider(
        api_key=settings.ncbi_api_key.get_secret_value() if settings.ncbi_api_key else None,
        email=settings.ncbi_email,
    )
    result = await pubmed.search("peptide depot", probe)
    await pubmed.aclose()
    if result.ok:
        rate = "10 req/s" if settings.ncbi_api_key else "3 req/s (no NCBI_API_KEY)"
        print(f"{OK} PubMed reachable — {result.total_available} hits, {rate}")
    else:
        print(f"{FAIL} PubMed: {result.error}")
        failures.append("pubmed")

    epmc = EuropePMCProvider(email=settings.crossref_mailto)
    result = await epmc.search("peptide depot", probe)
    await epmc.aclose()
    if result.ok:
        print(f"{OK} Europe PMC reachable — {result.total_available} hits")
    else:
        print(f"{FAIL} Europe PMC: {result.error}")
        failures.append("europepmc")

    heading("Patent provider")
    from app.providers.epo_ops import EPOOPSProvider

    epo = EPOOPSProvider(
        settings.epo_ops_consumer_key.get_secret_value()
        if settings.epo_ops_consumer_key
        else None,
        settings.epo_ops_consumer_secret.get_secret_value()
        if settings.epo_ops_consumer_secret
        else None,
    )
    if epo.is_configured:
        epo_ok, detail = await epo.health_check()
        if epo_ok:
            result = await epo.search("peptide depot", probe)
            if result.ok:
                print(f"{OK} EPO OPS authenticated — {result.count} document(s) parsed")
            else:
                print(f"{FAIL} EPO OPS authenticated but search failed: {result.error}")
                failures.append("epo_ops search")
        else:
            print(f"{FAIL} EPO OPS: {detail}")
            failures.append("epo_ops")
    else:
        print(f"{SKIP} EPO OPS not configured")
        print("       Runs will proceed on literature alone and the report will")
        print("       state that patents were not searched. Free key at")
        print("       https://developers.epo.org")
        warnings.append("epo_ops")
    await epo.aclose()

    await db.close_pool()

    # --------------------------------------------------------- summary ---
    print("\n" + "=" * 62)
    if failures:
        print(f"NOT READY — {len(failures)} problem(s): {', '.join(failures)}")
        print("=" * 62)
        return 1

    print("READY — start the API and worker:")
    print("  python -m uvicorn app.main:app --reload --port 8000")
    print("  python -m app.worker")
    if warnings:
        print(f"\nDegraded but functional: {', '.join(warnings)}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
