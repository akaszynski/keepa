"""Exercise compression through real HTTP sockets and the clients' decoders."""

import base64
import gzip
import json
import sys
import threading
import zlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import aiohttp
import pytest
import requests

import keepa

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd


PRODUCT = {"asin": "B000000000", "domainId": 1, "csv": None, "title": "Café ☕"}
PAYLOAD = {
    "products": [PRODUCT],
    "tokensLeft": 42,
    "refillIn": 0,
    "refillRate": 5,
    "timestamp": 0,
}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII="
)


@dataclass
class LocalAPI:
    body: bytes = json.dumps(PAYLOAD, ensure_ascii=False).encode()
    encoding: str = "zstd"
    status: int = 200
    chunked: bool = False
    content_type: str = "application/json; charset=utf-8"
    encoded_body: bytes | None = None
    headers: list[dict[str, str]] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)

    def encode(self) -> bytes:
        if self.encoded_body is not None:
            return self.encoded_body
        if self.encoding == "zstd":
            return zstd.compress(self.body)
        if self.encoding == "gzip":
            return gzip.compress(self.body)
        if self.encoding == "deflate":
            return zlib.compress(self.body)
        return self.body


@pytest.fixture
def local_api(monkeypatch):
    """Redirect only the destination; HTTP and decompression remain real."""
    api = LocalAPI()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            api.headers.append(dict(self.headers))
            body = api.encode()
            self.send_response(api.statuses.pop(0) if api.statuses else api.status)
            self.send_header("Content-Type", api.content_type)
            self.send_header("Connection", "close")
            if api.encoding:
                self.send_header("Content-Encoding", api.encoding)
            if api.chunked:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if api.chunked:
                # Split frame headers and compressed blocks across HTTP chunks.
                for start in range(0, len(body), 7):
                    chunk = body[start : start + 7]
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            else:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base_url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    real_sync_get = requests.get
    real_async_get = aiohttp.ClientSession.get

    def sync_get(url, *args, **kwargs):
        assert url.startswith("https://api.keepa.com/")
        return real_sync_get(base_url + urlsplit(url).path, *args, **kwargs)

    def async_get(session, url, *args, **kwargs):
        assert url.startswith("https://api.keepa.com/")
        return real_async_get(session, base_url + urlsplit(url).path, *args, **kwargs)

    monkeypatch.setattr(requests, "get", sync_get)
    monkeypatch.setattr(aiohttp.ClientSession, "get", async_get)
    try:
        yield api
        assert api.headers
        for headers in api.headers:
            encodings = {value.strip() for value in headers["Accept-Encoding"].split(",")}
            assert {"zstd", "gzip", "deflate"} <= encodings
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        assert not thread.is_alive()


@pytest.mark.parametrize("encoding", ["zstd", "gzip", "deflate", ""])
@pytest.mark.parametrize("chunked", [False, True])
def test_sync_compressed_json(local_api, encoding, chunked):
    local_api.encoding = encoding
    local_api.chunked = chunked
    api = keepa.Keepa("x" * 64)
    assert api.query(PRODUCT["asin"], history=False, progress_bar=False) == [PRODUCT]
    assert api.tokens_left == 42
    assert api.status.refillRate == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["zstd", "gzip", "deflate", ""])
@pytest.mark.parametrize("chunked", [False, True])
async def test_async_compressed_json(local_api, encoding, chunked):
    local_api.encoding = encoding
    local_api.chunked = chunked
    api = await keepa.AsyncKeepa.create("x" * 64)
    response = await api.query(PRODUCT["asin"], history=False, progress_bar=False)
    assert response == [PRODUCT]
    assert api.tokens_left == 42
    assert api.status.refillRate == 5


@pytest.mark.parametrize("frame_mode", ["unknown_size", "concatenated"])
def test_sync_zstd_frames(local_api, frame_mode):
    _configure_frames(local_api, frame_mode)
    api = keepa.Keepa("x" * 64)
    assert api.query(PRODUCT["asin"], history=False, progress_bar=False) == [PRODUCT]


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_mode", ["unknown_size", "concatenated"])
async def test_async_zstd_frames(local_api, frame_mode):
    _configure_frames(local_api, frame_mode)
    api = await keepa.AsyncKeepa.create("x" * 64)
    response = await api.query(PRODUCT["asin"], history=False, progress_bar=False)
    assert response == [PRODUCT]


def _configure_frames(local_api, frame_mode):
    local_api.chunked = True
    if frame_mode == "unknown_size":
        compressor = zstd.ZstdCompressor()
        local_api.encoded_body = compressor.compress(local_api.body) + compressor.flush()
    else:
        midpoint = len(local_api.body) // 2
        local_api.encoded_body = zstd.compress(local_api.body[:midpoint]) + zstd.compress(
            local_api.body[midpoint:]
        )


def test_sync_zstd_raw_response(local_api):
    api = keepa.Keepa("x" * 64)
    response = api.query(PRODUCT["asin"], history=False, progress_bar=False, raw=True)[0]
    assert isinstance(response, requests.Response)
    assert response.headers["Content-Encoding"] == "zstd"
    assert response.content == local_api.body
    assert response.json() == PAYLOAD


@pytest.mark.parametrize("chunked", [False, True])
def test_sync_zstd_graph_image(local_api, tmp_path, chunked):
    local_api.body = PNG
    local_api.content_type = "image/png"
    local_api.chunked = chunked
    filename = tmp_path / "graph.png"
    api = keepa.Keepa("x" * 64)
    api.download_graph_image(PRODUCT["asin"], filename)
    assert filename.read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("chunked", [False, True])
async def test_async_zstd_graph_image(local_api, tmp_path, chunked):
    local_api.body = PNG
    local_api.content_type = "image/png"
    local_api.chunked = chunked
    filename = tmp_path / "graph.png"
    api = await keepa.AsyncKeepa.create("x" * 64)
    await api.download_graph_image(PRODUCT["asin"], filename)
    assert filename.read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"\x89PNG", b"not png!"])
async def test_async_zstd_invalid_graph_image(local_api, tmp_path, body):
    local_api.body = body
    local_api.content_type = "image/png"
    local_api.chunked = True
    filename = tmp_path / "graph.png"
    api = await keepa.AsyncKeepa.create("x" * 64)
    with pytest.raises(ValueError, match="not a valid PNG image"):
        await api.download_graph_image(PRODUCT["asin"], filename)
    assert not filename.exists()


@pytest.mark.parametrize("status,message", [(400, "REQUEST_REJECTED"), (429, "NOT_ENOUGH_TOKEN")])
def test_sync_zstd_api_error(local_api, status, message):
    local_api.status = status
    api = keepa.Keepa("x" * 64)
    with pytest.raises(RuntimeError, match=message):
        api.query(PRODUCT["asin"], history=False, progress_bar=False, wait=False)
    assert api.tokens_left == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("status,message", [(400, "REQUEST_REJECTED"), (429, "NOT_ENOUGH_TOKEN")])
async def test_async_zstd_api_error(local_api, status, message):
    local_api.status = status
    api = await keepa.AsyncKeepa.create("x" * 64)
    with pytest.raises(RuntimeError, match=message):
        await api.query(PRODUCT["asin"], history=False, progress_bar=False, wait=False)
    assert api.tokens_left == 42


def test_sync_invalid_zstd(local_api):
    local_api.encoded_body = b"not a zstd frame"
    api = keepa.Keepa("x" * 64)
    with pytest.raises(requests.exceptions.ContentDecodingError):
        api.query(PRODUCT["asin"], history=False, progress_bar=False)


@pytest.mark.asyncio
async def test_async_invalid_zstd(local_api):
    local_api.encoded_body = b"not a zstd frame"
    api = await keepa.AsyncKeepa.create("x" * 64)
    with pytest.raises(RuntimeError, match="Invalid JSON from Keepa API"):
        await api.query(PRODUCT["asin"], history=False, progress_bar=False)


def test_sync_zstd_invalid_json(local_api):
    local_api.body = b"not JSON"
    api = keepa.Keepa("x" * 64)
    with pytest.raises(RuntimeError, match="Invalid JSON from Keepa API"):
        api.query(PRODUCT["asin"], history=False, progress_bar=False)


@pytest.mark.asyncio
async def test_async_zstd_invalid_json(local_api):
    local_api.body = b"not JSON"
    api = await keepa.AsyncKeepa.create("x" * 64)
    with pytest.raises(RuntimeError, match="Invalid JSON from Keepa API"):
        await api.query(PRODUCT["asin"], history=False, progress_bar=False)


def test_sync_zstd_token_retry(local_api):
    local_api.statuses = [200, 429, 200]
    api = keepa.Keepa("x" * 64)
    assert api.query(PRODUCT["asin"], history=False, progress_bar=False) == [PRODUCT]
    assert len(local_api.headers) == 3


@pytest.mark.asyncio
async def test_async_zstd_token_retry(local_api):
    local_api.statuses = [429, 200]
    api = await keepa.AsyncKeepa.create("x" * 64)
    response = await api.query(PRODUCT["asin"], history=False, progress_bar=False)
    assert response == [PRODUCT]
    assert len(local_api.headers) == 2
