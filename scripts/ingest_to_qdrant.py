"""
CLI entrypoint for Qdrant ingestion.

Usage:
    python scripts/ingest_to_qdrant.py [options]


Examples:
    python scripts/ingest_to_qdrant.py --source kb --strategy parent_child --recreate
    python scripts/ingest_to_qdrant.py --source markdown --strategy semantic
    PYTHONPATH=src python scripts/ingest_to_qdrant.py --source kb --recreate
"""

import argparse
from dotenv import load_dotenv

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(project_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

load_dotenv()

from services.ingest_service.pipeline import STRATEGY_MAP, LOADER_MAP, run_ingest

def main():
    parser = argparse.ArgumentParser(description="Qdrant ingestion CLI")
    parser.add_argument("--source", choices=LOADER_MAP.keys(), default="kb", help="Source of documents")
    parser.add_argument("--strategy", choices=STRATEGY_MAP.keys(), default="parent_child", help="Chunking strategy")
    parser.add_argument("--recreate", action="store_true", help="Recreate collection")
    args = parser.parse_args()

    run_ingest(source=args.source, strategy=args.strategy, recreate=args.recreate)

if __name__ == "__main__":
    main()