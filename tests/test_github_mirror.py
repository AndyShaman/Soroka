import pytest
from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError

@pytest.mark.asyncio
async def test_validate_repo_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/me/soroka-data",
        json={"name": "soroka-data", "private": True},
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    assert await m.validate() is True

@pytest.mark.asyncio
async def test_validate_repo_public_fails(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/me/soroka-data",
        json={"name": "soroka-data", "private": False},
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    with pytest.raises(GitHubMirrorError, match="private"):
        await m.validate()
