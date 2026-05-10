import pytest
from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError


BASE = "https://api.github.com/repos/me/soroka-data"
UPLOAD_BASE = "https://uploads.github.com/repos/me/soroka-data"


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


@pytest.mark.asyncio
async def test_upload_release_creates_when_missing(tmp_path, httpx_mock):
    """Tag has no release: classic create + upload path."""
    asset = tmp_path / "x.zip"
    asset.write_bytes(b"abc")

    httpx_mock.add_response(
        method="GET", url=f"{BASE}/releases/tags/soroka-daily-latest",
        status_code=404, json={"message": "Not Found"},
    )
    httpx_mock.add_response(
        method="POST", url=f"{BASE}/releases", status_code=201,
        json={
            "id": 8,
            "upload_url": f"{UPLOAD_BASE}/releases/8/assets{{?name,label}}",
        },
    )
    httpx_mock.add_response(
        method="POST", url=f"{UPLOAD_BASE}/releases/8/assets?name=x.zip",
        status_code=201,
        json={"browser_download_url": "https://example.test/x.zip"},
    )

    m = GitHubMirror(token="t", repo="me/soroka-data")
    url = await m.upload_release(
        tag="soroka-daily-latest", title="t", body="b",
        asset=asset, replace=True,
    )
    assert url == "https://example.test/x.zip"


@pytest.mark.asyncio
async def test_upload_release_replace_updates_in_place(tmp_path, httpx_mock):
    """Tag already has a release with one asset: delete old asset, upload
    new asset, PATCH metadata. Release id and tag are preserved, so a
    mid-flight failure cannot destroy the previous backup."""
    asset = tmp_path / "x.zip"
    asset.write_bytes(b"abc")

    httpx_mock.add_response(
        method="GET", url=f"{BASE}/releases/tags/soroka-daily-latest",
        status_code=200,
        json={
            "id": 7,
            "upload_url": f"{UPLOAD_BASE}/releases/7/assets{{?name,label}}",
            "assets": [{"id": 999, "name": "old.zip"}],
        },
    )
    httpx_mock.add_response(
        method="DELETE", url=f"{BASE}/releases/assets/999", status_code=204,
    )
    httpx_mock.add_response(
        method="POST", url=f"{UPLOAD_BASE}/releases/7/assets?name=x.zip",
        status_code=201,
        json={"browser_download_url": "https://example.test/x.zip"},
    )
    httpx_mock.add_response(
        method="PATCH", url=f"{BASE}/releases/7", status_code=200,
        json={"id": 7},
    )

    m = GitHubMirror(token="t", repo="me/soroka-data")
    url = await m.upload_release(
        tag="soroka-daily-latest", title="t", body="b",
        asset=asset, replace=True,
    )
    assert url == "https://example.test/x.zip"


@pytest.mark.asyncio
async def test_upload_release_replace_false_refuses_existing(tmp_path, httpx_mock):
    """Without replace=True, an existing release is treated as a conflict.
    Prevents `/export` (unique tags) from silently clobbering history."""
    asset = tmp_path / "x.zip"
    asset.write_bytes(b"abc")

    httpx_mock.add_response(
        method="GET", url=f"{BASE}/releases/tags/dup",
        status_code=200, json={"id": 7, "upload_url": "x", "assets": []},
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    with pytest.raises(GitHubMirrorError, match="already exists"):
        await m.upload_release(tag="dup", title="t", body="b", asset=asset)


@pytest.mark.asyncio
async def test_upload_release_replace_upload_failure_preserves_release(tmp_path, httpx_mock):
    """Old asset deleted, new asset upload returns 502: function raises but
    release id and tag stay intact. The next run sees the same release with
    no assets and re-uploads cleanly — no permanent damage."""
    asset = tmp_path / "x.zip"
    asset.write_bytes(b"abc")

    httpx_mock.add_response(
        method="GET", url=f"{BASE}/releases/tags/soroka-daily-latest",
        status_code=200,
        json={
            "id": 7,
            "upload_url": f"{UPLOAD_BASE}/releases/7/assets{{?name,label}}",
            "assets": [{"id": 999, "name": "old.zip"}],
        },
    )
    httpx_mock.add_response(
        method="DELETE", url=f"{BASE}/releases/assets/999", status_code=204,
    )
    httpx_mock.add_response(
        method="POST", url=f"{UPLOAD_BASE}/releases/7/assets?name=x.zip",
        status_code=502, text="bad gateway",
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    with pytest.raises(GitHubMirrorError, match="upload asset"):
        await m.upload_release(
            tag="soroka-daily-latest", title="t", body="b",
            asset=asset, replace=True,
        )


@pytest.mark.asyncio
async def test_upload_release_replace_recovers_when_release_has_no_assets(tmp_path, httpx_mock):
    """Self-heal: previous run uploaded asset but failed before PATCH and
    later the asset got removed (or was never there). GET returns release
    with empty assets[] — no DELETE needed, upload + PATCH proceed."""
    asset = tmp_path / "x.zip"
    asset.write_bytes(b"abc")

    httpx_mock.add_response(
        method="GET", url=f"{BASE}/releases/tags/soroka-daily-latest",
        status_code=200,
        json={
            "id": 7,
            "upload_url": f"{UPLOAD_BASE}/releases/7/assets{{?name,label}}",
            "assets": [],
        },
    )
    httpx_mock.add_response(
        method="POST", url=f"{UPLOAD_BASE}/releases/7/assets?name=x.zip",
        status_code=201,
        json={"browser_download_url": "https://example.test/x.zip"},
    )
    httpx_mock.add_response(
        method="PATCH", url=f"{BASE}/releases/7", status_code=200, json={},
    )

    m = GitHubMirror(token="t", repo="me/soroka-data")
    url = await m.upload_release(
        tag="soroka-daily-latest", title="t", body="b",
        asset=asset, replace=True,
    )
    assert url == "https://example.test/x.zip"


@pytest.mark.asyncio
async def test_upload_release_lookup_failure_propagates(tmp_path, httpx_mock):
    """Anything other than 200/404 on the initial GET is a hard error — we
    must not silently fall through to the create path and risk duplicating
    a release the API just refused to describe."""
    asset = tmp_path / "x.zip"
    asset.write_bytes(b"abc")

    httpx_mock.add_response(
        method="GET", url=f"{BASE}/releases/tags/soroka-daily-latest",
        status_code=500, text="boom",
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    with pytest.raises(GitHubMirrorError, match="lookup release"):
        await m.upload_release(
            tag="soroka-daily-latest", title="t", body="b",
            asset=asset, replace=True,
        )
