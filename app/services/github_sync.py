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
            local_dir.mkdir(parents=True, exist_ok=True)

            # Fetch the directory listing from GitHub.
            url = f"{_GITHUB_API}/repos/{_REPO}/contents/{repo_dir}?ref={_BRANCH}"
            resp = await client.get(url)

            if resp.status_code == 404:
                # Directory doesn't exist in the repo yet — skip silently.
                logger.info("GitHub: %s not found, skipping", repo_dir)
                continue

            resp.raise_for_status()
            items = resp.json()

            if not isinstance(items, list):
                logger.warning("GitHub: unexpected response for %s — skipping", repo_dir)
                continue

            # Map of filename → sha for what's in the repo.
            repo_files: dict[str, tuple[str, str]] = {}  # name → (sha, download_url)
            for item in items:
                if item.get("type") == "file":
                    repo_files[item["name"]] = (item["sha"], item.get("download_url", ""))

            # Write / update files that are in the repo.
            for filename, (_sha, download_url) in repo_files.items():
                if filename == ".gitkeep":
                    continue
                dest = local_dir / filename
                file_resp = await client.get(download_url)
                file_resp.raise_for_status()
                dest.write_bytes(file_resp.content)
                counts["fetched"] += 1
                logger.debug("Fetched %s → %s", filename, dest)

            # Remove local files that are no longer in the repo.
            for existing in local_dir.iterdir():
                if existing.name not in repo_files and existing.name != ".gitkeep":
                    existing.unlink()
                    counts["deleted"] += 1
                    logger.info("Removed orphaned file: %s", existing)

    logger.info(
        "GitHub sync complete — fetched=%d deleted=%d",
        counts["fetched"],
        counts["deleted"],
    )
    return counts
