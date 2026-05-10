from pathlib import Path
import httpx


class GitHubMirrorError(Exception):
    pass


class GitHubMirror:
    BASE = "https://api.github.com"

    def __init__(self, token: str, repo: str, timeout: float = 60.0):
        self._token = token
        self._repo = repo
        self._timeout = timeout

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def validate(self) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self.BASE}/repos/{self._repo}", headers=self._headers)
        if r.status_code == 401:
            raise GitHubMirrorError("token unauthorized")
        if r.status_code == 404:
            raise GitHubMirrorError("repo not found or token has no access")
        if r.status_code != 200:
            raise GitHubMirrorError(f"{r.status_code}: {r.text[:200]}")
        if not r.json().get("private", False):
            raise GitHubMirrorError("repo must be private")
        return True

    async def upload_release(self, tag: str, title: str, body: str,
                              asset: Path, replace: bool = False) -> str:
        """Create a release and upload an asset. With replace=True, an
        existing release for the tag is updated in place — old assets are
        removed, the new asset is uploaded, and only then is the release
        metadata patched. The release id and tag survive the operation, so a
        mid-flight upload failure leaves the previous state intact (or, in
        the worst case, an asset-less release that the next run heals)."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            existing = await client.get(
                f"{self.BASE}/repos/{self._repo}/releases/tags/{tag}",
                headers=self._headers,
            )
            if existing.status_code == 200:
                if not replace:
                    raise GitHubMirrorError(
                        f"release with tag {tag!r} already exists"
                    )
                release = existing.json()
                release_id = release["id"]
                upload_url = release["upload_url"].split("{")[0]
                # Delete previous assets first so a same-named new asset
                # doesn't 422 on a name collision. Each delete is independent
                # — if one fails we abort, but the release id and tag are
                # still intact, so the next run can retry from scratch.
                for asset_obj in release.get("assets", []) or []:
                    rd = await client.delete(
                        f"{self.BASE}/repos/{self._repo}/releases/assets/{asset_obj['id']}",
                        headers=self._headers,
                    )
                    if rd.status_code not in (204, 404):
                        raise GitHubMirrorError(
                            f"delete asset: {rd.status_code} {rd.text[:200]}"
                        )
                with asset.open("rb") as f:
                    ru = await client.post(
                        f"{upload_url}?name={asset.name}",
                        headers={**self._headers, "Content-Type": "application/octet-stream"},
                        content=f.read(),
                    )
                if ru.status_code not in (200, 201):
                    raise GitHubMirrorError(
                        f"upload asset: {ru.status_code} {ru.text[:200]}"
                    )
                # Asset is up — patch the release body/title last so a metadata
                # failure cannot strand us with no asset.
                rp = await client.patch(
                    f"{self.BASE}/repos/{self._repo}/releases/{release_id}",
                    headers=self._headers,
                    json={"name": title, "body": body},
                )
                if rp.status_code not in (200, 201):
                    raise GitHubMirrorError(
                        f"patch release: {rp.status_code} {rp.text[:200]}"
                    )
                return ru.json()["browser_download_url"]

            if existing.status_code != 404:
                raise GitHubMirrorError(
                    f"lookup release: {existing.status_code} {existing.text[:200]}"
                )

            rc = await client.post(
                f"{self.BASE}/repos/{self._repo}/releases",
                headers=self._headers,
                json={"tag_name": tag, "name": title, "body": body},
            )
            if rc.status_code not in (200, 201):
                raise GitHubMirrorError(f"create release: {rc.status_code} {rc.text[:200]}")
            upload_url = rc.json()["upload_url"].split("{")[0]
            with asset.open("rb") as f:
                ru = await client.post(
                    f"{upload_url}?name={asset.name}",
                    headers={**self._headers, "Content-Type": "application/octet-stream"},
                    content=f.read(),
                )
            if ru.status_code not in (200, 201):
                raise GitHubMirrorError(f"upload asset: {ru.status_code} {ru.text[:200]}")
            return ru.json()["browser_download_url"]
