"""Loaders for the chosen SWE-bench Lite instance slice (see eval/instances.txt).

WHY THIS FILE EXISTS
--------------------
The pipeline starts from a SWE-bench instance ID (e.g. "pallets__flask-5063"). Two
things have to happen before any node can work:

  1. Look up the bug record — the problem statement, which repo it lives in, and the
     exact commit (``base_commit``) that reproduces the bug. That comes from the
     SWE-bench Lite dataset (cached locally by Hugging Face ``datasets``).
  2. Put the *actual source code* on disk at that commit, so the Localizer can run
     ``git grep`` over real files. We do this by cloning the GitHub repo once into a
     shared cache, then making a cheap per-instance working copy checked out at the
     bug's ``base_commit``.

This module owns both steps; the Intake node calls into it.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from datasets import load_dataset

# The official SWE-bench Lite dataset on the Hugging Face Hub, and the split we use.
DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DATASET_SPLIT = "test"

# Where checked-out repos live. ``_cache/`` holds one full clone per GitHub repo
# (downloaded once); the per-instance working copies sit directly under this dir.
# This whole tree is gitignored (see .gitignore: eval/repos/).
REPOS_DIR = Path("eval/repos")


# --------------------------------------------------------------------------------
# 1. Loading the dataset record
# --------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    """Load the dataset once and return an {instance_id: record} lookup table.

    ``lru_cache`` means the (slow) dataset load happens only on the first call; every
    later call reuses the in-memory index.
    """
    dataset = load_dataset(DATASET_NAME, split=DATASET_SPLIT)
    return {record["instance_id"]: dict(record) for record in dataset}


def load_instance(instance_id: str) -> dict:
    """Return the SWE-bench Lite record for ``instance_id``.

    The record includes ``problem_statement``, ``repo`` (the GitHub "owner/name"),
    ``base_commit``, ``version``, the gold ``patch``/``test_patch``, and the
    ``FAIL_TO_PASS`` / ``PASS_TO_PASS`` test lists.

    Args:
        instance_id: e.g. "pallets__flask-5063".

    Returns:
        The instance record as a plain dict.

    Raises:
        KeyError: if no instance with that ID exists in the dataset.
    """
    index = _index()
    if instance_id not in index:
        raise KeyError(
            f"Unknown instance_id {instance_id!r}. "
            f"It is not in {DATASET_NAME} [{DATASET_SPLIT}]."
        )
    return index[instance_id]


# --------------------------------------------------------------------------------
# 2. Checking out the repo at the bug's base_commit
# --------------------------------------------------------------------------------

def _git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command, raise on failure, and return its stdout (stripped)."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,            # raise CalledProcessError on a non-zero exit code
        capture_output=True,   # capture stdout/stderr instead of printing them
        text=True,             # decode bytes to str
    )
    return result.stdout.strip()


def _ensure_cache_clone(repo: str) -> Path:
    """Ensure a full clone of ``repo`` exists in the cache, and return its path.

    Cloning the whole history (not a shallow clone) guarantees the historical
    ``base_commit`` is present without extra fetches. The clone happens once; later
    instances of the same repo reuse it.

    Args:
        repo: GitHub "owner/name", e.g. "pallets/flask".
    """
    cache = REPOS_DIR / "_cache" / repo.replace("/", "__")
    if not (cache / ".git").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", f"https://github.com/{repo}.git", str(cache)])
    return cache


def _has_commit(repo_dir: Path, commit: str) -> bool:
    """Return True if ``commit`` already exists in ``repo_dir``'s object store."""
    try:
        # "<commit>^{commit}" forces git to verify it really is a commit object.
        _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=repo_dir)
        return True
    except subprocess.CalledProcessError:
        return False


def checkout_repo(instance: dict, dest: Path | None = None, force: bool = False) -> Path:
    """Check out ``instance``'s repo at its ``base_commit`` and return the path.

    Strategy: keep one cached clone per repo, then make a per-instance working copy
    from that cache and check out the bug's commit. Cloning from the local cache is
    fast (git hardlinks objects) and needs no network once the cache exists.

    Args:
        instance: a record from :func:`load_instance`.
        dest: where to put the working copy (defaults to ``eval/repos/<instance_id>``).
        force: if True, delete and recreate ``dest`` even if it already exists.

    Returns:
        Path to the working copy, checked out at ``base_commit``.
    """
    repo = instance["repo"]
    commit = instance["base_commit"]
    instance_id = instance["instance_id"]
    dest = dest or (REPOS_DIR / instance_id)

    # Fast path: a working copy already sitting at the right commit — reuse it.
    if dest.exists() and not force:
        try:
            if _git(["rev-parse", "HEAD"], cwd=dest) == commit:
                return dest
        except subprocess.CalledProcessError:
            pass  # corrupt/partial checkout — fall through and rebuild it

    # Otherwise (re)build the working copy from scratch.
    if dest.exists():
        shutil.rmtree(dest)

    cache = _ensure_cache_clone(repo)
    # The cache might predate this commit (repo updated since); fetch if missing.
    if not _has_commit(cache, commit):
        _git(["fetch", "origin"], cwd=cache)

    # Clone from the local cache without checking out a branch, then check out the
    # exact bug commit. "-f" discards anything in the way to land cleanly on it.
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "--no-checkout", str(cache), str(dest)])
    _git(["checkout", "-f", commit], cwd=dest)
    return dest

#Command to validate this file (run from the repo root, where src/defect_triage/instances.py lives):
# ./bin/python -c "
# from src.defect_triage.instances import load_instance, checkout_repo
# import subprocess
# inst = load_instance('pallets__flask-5063')
# path = checkout_repo(inst)
# head = subprocess.run(['git','-C',str(path),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
# assert head == inst['base_commit'], 'HEAD != base_commit'
# assert (path/'src'/'flask').is_dir(), 'flask source missing'
# print('instances.py OK — repo at', path, 'commit', head[:10])
# "
