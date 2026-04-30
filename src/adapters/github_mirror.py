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

    async def upload_release(self, tag: str, title: str, body: str, asset: Path) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/repos/{self._repo}/releases",
                headers=self._headers,
                json={"tag_name": tag, "name": title, "body": body},
            )
            if r.status_code not in (200, 201):
                raise GitHubMirrorError(f"create release: {r.status_code} {r.text[:200]}")
            release = r.json()
            upload_url = release["upload_url"].split("{")[0]

            with asset.open("rb") as f:
                r2 = await client.post(
                    f"{upload_url}?name={asset.name}",
                    headers={**self._headers, "Content-Type": "application/octet-stream"},
                    content=f.read(),
                )
            if r2.status_code not in (200, 201):
                raise GitHubMirrorError(f"upload asset: {r2.status_code} {r2.text[:200]}")
            return r2.json()["browser_download_url"]
