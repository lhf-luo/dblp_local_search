"""Server, manual update and dedicated scheduler entry points."""

import argparse
import logging
from pathlib import Path

import uvicorn

from dblp_local_search.config import Settings
from dblp_local_search.ingestion.update import update


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    importer = commands.add_parser("update")
    importer.add_argument("--force", action="store_true")
    importer.add_argument(
        "--full", action="store_true", help="Ignore the active database and rebuild"
    )
    importer.add_argument("--xml", type=Path)
    importer.add_argument("--dtd", type=Path)
    commands.add_parser("schedule")
    commands.add_parser("healthcheck")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "serve":
        if not settings.api_token:
            parser.error("DBLP_API_TOKEN must be configured")
        uvicorn.run(
            "dblp_local_search.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
        )
    elif args.command == "update":
        try:
            print(
                update(
                    settings,
                    force=args.force,
                    full=args.full,
                    xml=args.xml,
                    dtd=args.dtd,
                )
            )
        except Exception as error:
            logging.error("Update failed: %s", error)
            raise SystemExit(1) from None
    elif args.command == "schedule":
        from dblp_local_search.scheduler import run

        run(settings)
    else:
        import httpx

        try:
            response = httpx.get("http://127.0.0.1:8000/health/ready", timeout=10)
            response.raise_for_status()
        except httpx.HTTPError:
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
