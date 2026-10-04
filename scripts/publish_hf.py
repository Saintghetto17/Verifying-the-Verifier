#!/usr/bin/env python3
"""Upload a built release (``scripts/build_dataset.py --out <dir>``) to Hugging Face.

When the remaining B75 images become available, place them in the
``bench_final/<topic>/<id>/`` folders, rebuild, and publish again: unchanged
files are deduplicated by the Hub, so only the new images are transferred.

    HF_TOKEN=... python scripts/publish_hf.py --release data --message "Add B75 images"
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi

DEFAULT_REPO = "Saintghetto17/verifying-the-verifier"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, required=True, help="directory produced by build_dataset.py")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--message", default="Update benchmark release")
    args = parser.parse_args()

    if not (args.release / "metadata" / "pairs.jsonl").is_file():
        raise SystemExit(f"{args.release} is not a built release (metadata/pairs.jsonl missing)")
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(args.repo, repo_type="dataset", exist_ok=True)
    api.upload_folder(repo_id=args.repo, repo_type="dataset", folder_path=str(args.release),
                      commit_message=args.message, ignore_patterns=[".cache/**", "**/.DS_Store"])
    print(f"Published {args.release} to https://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
