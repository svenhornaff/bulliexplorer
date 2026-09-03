"""GitHub Contents-API sync service.

Fetches ``content/posts/`` and ``static/uploads/`` from the GitHub repo at
the current ``develop`` HEAD, then writes the files into the volume-mounted
local directories so the app sees them without a container restart.

Design rules (per AGENTS.md):
- **Framework-free**: no FastAPI, Jinja2, or sqladmin imports.
- All network calls use ``httpx.AsyncClient`` (already a dependency).
- Writes only to paths inside the two volume-mounted directories — never
  anywhere else.  Existing files that are no longer in GitHub are removed
  (source of truth is the repo).
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.utils.log_factory import get_logger

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"
_REPO = "svenhornaff/bulliexplorer"
_BRANCH = "develop"

# Directories to mirror from the repo into the local volume-mount.
# Tuple of (repo_path, local_path).
_SYNC_DIRS: tuple[tuple[str, ...], ...] = (
    ("content/posts", "content/posts"),
    ("static/uploads", "static/uploads"),
)


async def fetch_and_write(
    base_dir: Path,
    github_token: str,
) -> dict[str, int]:
    """Fetch repo content from GitHub and write it to the local filesystem.

    Fetches ``content/posts/`` and ``static/uploads/`` from the ``develop``
    branch using the GitHub Contents API, then writes each file into the
    corresponding volume-mounted directory under ``base_dir``.  Files present
    locally but deleted from the repo are removed.

    Parameters
    ----------
    base_dir:
        Project root — ``BASE_DIR`` from ``app/main.py``.  All writes are
        anchored under this directory.
    github_token:
        Fine-grained PAT with Contents: Read on the repo.

    Returns
    -------
    dict
        ``{"fetched": N, "deleted": N}`` — counts of files written/removed.
    """
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    counts = {"fetched": 0, "deleted": 0}

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        for repo_dir, local_subpath in _SYNC_DIRS:
            local_dir = base_dir / local_subpath
            counts = await _sync_dir(
                client=client,
                repo_dir=repo_dir,
                local_dir=local_dir,
                counts=counts,
            )

    logger.info(
        "GitHub sync complete — fetched=%d deleted=%d",
        counts["fetched"],
        counts["deleted"],
    )
    return counts


async def _sync_dir(
    client: httpx.AsyncClient,
    repo_dir: str,
    local_dir: Path,
    counts: dict[str, int],
) -> dict[str, int]:
    """Recursively mirror one GitHub directory into a local directory.

    Handles subdirectories (e.g. ``static/uploads/galleries/``) by recursing
    into them.  Skips ``.gitkeep`` sentinels.  Removes local files/dirs that
    are no longer present in the repo.

    Parameters
    ----------
    client:
        Authenticated ``httpx.AsyncClient``.
    repo_dir:
        Path inside the repo, e.g. ``"static/uploads"``.
    local_dir:
        Corresponding absolute local path to write into.
    counts:
        Running ``{"fetched": N, "deleted": N}`` counters — mutated in place.
    """
    local_dir.mkdir(parents=True, exist_ok=True)

    url = f"{_GITHUB_API}/repos/{_REPO}/contents/{repo_dir}?ref={_BRANCH}"
    resp = await client.get(url)

    if resp.status_code == 404:
        logger.info("GitHub: %s not found, skipping", repo_dir)
        return counts

    resp.raise_for_status()
    items = resp.json()

    if not isinstance(items, list):
        logger.warning("GitHub: unexpected response for %s — skipping", repo_dir)
        return counts

    # Partition items into files and subdirectories.
    repo_files: dict[str, str] = {}  # name → download_url
    repo_subdirs: set[str] = set()  # subdir names

    for item in items:
        if item.get("type") == "file":
            repo_files[item["name"]] = item.get("download_url", "")
        elif item.get("type") == "dir":
            repo_subdirs.add(item["name"])

    # Write / update files present in the repo.
    for filename, download_url in repo_files.items():
        if filename == ".gitkeep":
            continue
        dest = local_dir / filename
        file_resp = await client.get(download_url)
        file_resp.raise_for_status()
        dest.write_bytes(file_resp.content)
        counts["fetched"] += 1
        logger.debug("Fetched %s → %s", filename, dest)

    # Recurse into subdirectories present in the repo.
    for subdir_name in repo_subdirs:
        counts = await _sync_dir(
            client=client,
            repo_dir=f"{repo_dir}/{subdir_name}",
            local_dir=local_dir / subdir_name,
            counts=counts,
        )

    # Remove local files/dirs no longer present in the repo.
    known = repo_files.keys() | repo_subdirs | {".gitkeep"}
    for existing in local_dir.iterdir():
        if existing.name in known:
            continue
        if existing.is_dir():
            import shutil

            try:
                shutil.rmtree(existing)
            except OSError as exc:
                logger.warning("Could not remove orphaned dir %s: %s", existing, exc)
                continue
            logger.info("Removed orphaned dir: %s", existing)
        else:
            try:
                existing.unlink()
            except OSError as exc:
                logger.warning("Could not remove orphaned file %s: %s", existing, exc)
                continue
            logger.info("Removed orphaned file: %s", existing)
        counts["deleted"] += 1

    return counts

    logger.info(
        "GitHub sync complete — fetched=%d deleted=%d",
        counts["fetched"],
        counts["deleted"],
    )
    return counts
