# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fresh-session TikTok video timelines, entirely in Python.

The signing algorithm is ported locally from ../sign/example.py; that module,
browser state, captures, Node.js and remote signers are not runtime dependencies.
HTTP acquisition requires httpx[http2]. Default collection is bounded to two
pages. Signed URLs, cookies, tokens and visitor IDs are never printed.
See DOCS.md for the tested SDK mode, randomization and limitations.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import struct
import sys
import unittest


_MASK = 0xFFFFFFFF
_CONSTANTS = (1196819126, 600974999, 3863347763, 1451689750)
_STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_ALPHABET = "u09tbS3UvgDEe6r-ZVMXzLpsAohTn7mdINQlW412GqBjfYiyk8JORCF5/xKHwacP="
_TRANSLATION = str.maketrans(_STANDARD, _ALPHABET)


class UnsupportedSigningState(ValueError):
    """Missing, invalid, or unsupported inputs; messages never include values."""


@dataclass(frozen=True, repr=False)
class GnarlyState:
    """Explicit inputs; this module does not acquire or update SDK state.

    Counters are the effective values after SDK counter aggregation. The supported
    path requires clock_selector == 2, timestamp_masked == False, and no timing
    guard. env_code bit 32 still selects the source's constant-time low half.
    """

    env_code: int
    interaction_code: int
    seed: int
    performance_value: int
    total_requests: int
    intercepted_requests: int
    clock_selector: int
    timestamp_masked: bool
    timing_guard_triggered: bool


def _uint32(value: object) -> bool:
    return type(value) is int and 0 <= value <= _MASK


def _rotate(value: int, count: int) -> int:
    value &= _MASK
    return ((value << count) | (value >> (32 - count))) & _MASK


def _quarter(words: list[int], a: int, b: int, c: int, d: int) -> None:
    words[a] = (words[a] + words[b]) & _MASK
    words[d] = _rotate(words[d] ^ words[a], 16)
    words[c] = (words[c] + words[d]) & _MASK
    words[b] = _rotate(words[b] ^ words[c], 12)
    words[a] = (words[a] + words[b]) & _MASK
    words[d] = _rotate(words[d] ^ words[a], 8)
    words[c] = (words[c] + words[d]) & _MASK
    words[b] = _rotate(words[b] ^ words[c], 7)


def _crypt(payload: bytes, key_words: tuple[int, ...]) -> bytes:
    state = list(_CONSTANTS + key_words)
    rounds = 5 + (sum(key_words) & 15)
    output = bytearray()
    columns = ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15))
    # These last two tuples deliberately differ from standard ChaCha.
    diagonals = ((0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 12, 13), (3, 4, 13, 14))
    for offset in range(0, len(payload), 64):
        working = state.copy()
        for turn in range(rounds):
            for indices in columns if turn % 2 == 0 else diagonals:
                _quarter(working, *indices)
        block = struct.pack("<16I", *((x + y) & _MASK for x, y in zip(working, state)))
        output.extend(x ^ y for x, y in zip(payload[offset : offset + 64], block))
        state[12] = (state[12] + 1) & _MASK
    return bytes(output)


def _checksum(values: list[int | str], *, string_bytes: bool) -> int:
    result = 0
    for value in values:
        if isinstance(value, str):
            if string_bytes:
                value = int.from_bytes(value.encode("utf-8")[:4], "big")
            else:
                # JS bitwise coercion of the hex digests/version strings. Even a
                # digits-only digest goes through a binary64 Number first.
                try:
                    value = int(float(value))
                except (ValueError, OverflowError):
                    value = 0
        result ^= value & _MASK
    return result & _MASK


def _payload(query: str, user_agent: str, timestamp: int, state: GnarlyState) -> bytes:
    def md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()

    seed = state.seed
    proof = (
        (timestamp >> 16) ^ (seed >> 16) ^ (timestamp & 65535) ^ (seed & 65535)
    ) | (state.env_code << 16)
    proof &= _MASK
    if proof & 0x80000000:
        proof -= 1 << 32
    low_time = 1767225600 if state.env_code & 32 else timestamp
    time_seed = ((low_time ^ seed) & 65535) | (
        ((state.performance_value ^ (seed >> 16)) & 65535) << 16
    )
    pairs = [
        [0, 0],
        [1, state.env_code],
        [2, state.interaction_code],
        [3, md5(query)],
        [4, md5("")],  # This API supports GET with an empty body only.
        [5, md5(user_agent)],
        [6, timestamp],
        [7, state.performance_value],
        [8, seed],
        [9, "5.3.2"],
        [10, "1.0.0.417"],
        [11, 1],
        [12, state.total_requests],
        [13, state.intercepted_requests],
        [14, proof],
        [15, time_seed],
    ]
    pairs.append([16, _checksum([value for _, value in pairs], string_bytes=True)])
    pairs[0][1] = _checksum([value for _, value in pairs], string_bytes=False)
    shuffle_seed = seed
    for i in range(len(pairs) - 1, 0, -1):
        shuffle_seed = (1664525 * shuffle_seed + 1013904223) & _MASK
        j = (shuffle_seed * (i + 1)) // (1 << 32)
        pairs[i], pairs[j] = pairs[j], pairs[i]
    records = []
    for key, value in pairs:
        if isinstance(value, int):
            # The source omits negative/non-uint32 numeric records.
            if not 0 <= value <= _MASK:
                continue
            encoded = value.to_bytes(2 if value <= 65535 else 4, "big")
        else:
            encoded = value.encode("utf-8")
        records.append(bytes([key]) + len(encoded).to_bytes(2, "big") + encoded)
    return bytes([len(records)]) + b"".join(records)


def generate_x_gnarly(
    *,
    query: str,
    user_agent: str,
    timestamp: int,
    state: GnarlyState,
    key_words: list[int] | tuple[int, ...],
) -> str:
    """Generate only X-Gnarly for the documented empty-body GET fast path.

    query is the exact serialized query AFTER X-Dynosaur and msToken have been
    appended, BEFORE X-Bogus and X-Gnarly. It excludes the URL and leading '?'.
    No query parsing, re-encoding, state mutation, network, clock read, random
    generation, or browser access occurs. key_words are twelve explicit uint32
    words from the SDK encryption RNG boundary, not a captured signature.
    """
    if not isinstance(query, str) or not isinstance(user_agent, str):
        raise UnsupportedSigningState("query and user_agent must be strings")
    try:
        query.encode("utf-8")
        user_agent.encode("utf-8")
    except UnicodeEncodeError:
        raise UnsupportedSigningState("unpaired Unicode surrogates are unsupported") from None
    if not isinstance(state, GnarlyState) or not _uint32(timestamp):
        raise UnsupportedSigningState("explicit state and uint32 timestamp are required")
    for value in (
        state.env_code, state.interaction_code, state.seed,
        state.total_requests, state.intercepted_requests,
    ):
        if not _uint32(value):
            raise UnsupportedSigningState("state numeric fields must be uint32 integers")
    if not (_uint32(state.performance_value) or type(state.performance_value) is int and state.performance_value == -1):
        raise UnsupportedSigningState("invalid canvas value")
    if (
        type(state.clock_selector) is not int or state.clock_selector != 2
        or state.timestamp_masked is not False
        or state.timing_guard_triggered is not False
    ):
        raise UnsupportedSigningState("only the documented SDK fast path is supported")
    if (
        not isinstance(key_words, (list, tuple)) or len(key_words) != 12
        or not all(_uint32(word) for word in key_words)
    ):
        raise UnsupportedSigningState("twelve explicit uint32 encryption words are required")
    return _envelope(_payload(query, user_agent, timestamp, state), tuple(key_words))


# Source RNG constants differ from the encryption prefix constants.
_RNG_PREFIX = (2517678443, 2718276124, 3212677781, 2633865432, 217618912,
               2931180889, 1498001188, 2157053261, 211147047, 185100057,
               2903579748, 3732962506)
_ENDPOINT = "https://www.tiktok.com/api/post/item_list/"
_SECURITY_FIELDS = {"X-Dynosaur", "msToken", "X-Bogus", "X-Gnarly"}


def _signed32(value: int) -> int:
    value &= _MASK
    return value - (1 << 32) if value & (1 << 31) else value


def _rng_block(state: list[int]) -> list[int]:
    # Unlike the cipher's final byte output, the RNG consumes untruncated JS
    # additions. Masking every addition here changes the generated word stream.
    words = state.copy()
    for turn in range(8):
        rows = ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15)) if turn % 2 == 0 else ((0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 12, 13), (3, 4, 13, 14))
        for a, b, c, d in rows:
            words[a] += words[b]
            words[d] = _signed32(_rotate(words[d] ^ words[a], 16))
            words[c] += words[d]
            words[b] = _signed32(_rotate(words[b] ^ words[c], 12))
            words[a] += words[b]
            words[d] = _signed32(_rotate(words[d] ^ words[a], 8))
            words[c] += words[d]
            words[b] = _signed32(_rotate(words[b] ^ words[c], 7))
    return [x + y for x, y in zip(words, state)]


@dataclass(repr=False)
class SigningState:
    """Mutable, explicit session state; serialize privately, never log it."""

    ms_token: str
    gnarly_seed: int
    dynosaur_seed: int
    rng_words: list[int]
    rng_index: int = 0
    total_requests: int = 0
    intercepted_requests: int = 0

    def encryption_words(self) -> tuple[int, ...]:
        import math

        output = []
        for _ in range(12):
            block = _rng_block(self.rng_words)
            low = block[self.rng_index]
            high = (block[self.rng_index + 8] & 4294965248) >> 11
            sample = float(low + 4294967296 * high) / (1 << 53)
            output.append(math.floor(sample * (1 << 32)) & _MASK)
            if self.rng_index == 7:
                self.rng_words[12] = _signed32(self.rng_words[12] + 1)
                self.rng_index = 0
            else:
                self.rng_index += 1
        return tuple(output)


@dataclass(frozen=True, repr=False)
class Environment:
    user_agent: str
    page_url: str
    # Source initial collector state and source missing-canvas error branch.
    env_code: int = 0
    interaction_code: int = 0
    canvas_hash: int = -1


@dataclass(frozen=True, repr=False)
class SigningResult:
    url: str
    fields: dict[str, str]


def _validate_token(token: object) -> None:
    if not isinstance(token, str) or not token or not token.isascii() or any(
        ord(c) <= 32 or ord(c) == 127 or c in "&?#" for c in token
    ):
        raise UnsupportedSigningState("a nonempty server-issued query token is required")


def _fingerprint_seed(timestamp_ms: int, first: float, second: float) -> int:
    import math

    return math.floor(abs((1000 * ((float(timestamp_ms) + first) + second)) % (1 << 31)))


def create_state(ms_token: str, *, timestamp_ms: int | None = None) -> SigningState:
    """Initialize the recovered SDK RNG/seeds using fresh local entropy.

    This does not acquire a token or contact a server. Supply an issued token;
    ProfileSession.bootstrap_profile() is the separate network acquisition helper.
    """
    import secrets
    import time

    _validate_token(ms_token)
    if timestamp_ms is None:
        timestamp_ms = time.time_ns() // 1_000_000
    if type(timestamp_ms) is not int or not 0 <= timestamp_ms // 1000 <= _MASK:
        raise UnsupportedSigningState("unsupported initialization time")
    entropy = [secrets.randbits(32) for _ in range(3)]
    samples = [secrets.randbits(53) / (1 << 53) for _ in range(4)]
    return SigningState(
        ms_token,
        _fingerprint_seed(timestamp_ms, samples[0], samples[1]),
        _fingerprint_seed(timestamp_ms, samples[2], samples[3]),
        list(_RNG_PREFIX) + [_signed32(timestamp_ms)] + entropy,
    )


def _encode_dyn_value(text: str, *, checksum: bool = False) -> bytes:
    units = text.encode("utf-16-le")
    count = len(units) // 2
    if count > 65535:
        raise UnsupportedSigningState("Dynosaur value exceeds the supported length")
    output = bytearray(max(6, count + 2))
    for index, (unit,) in enumerate(struct.iter_unpack("<H", units)):
        if checksum:
            value = ((unit ^ ((102 + index) & 255)) + (170 & index)) % 256
            value ^= 165
            value = ((value << 1) | (value >> 7)) & 255
            value ^= 187
        else:
            value = ((unit ^ ((103 + index) & 255)) + 1 + (170 & index)) % 256
            value = ((value << 2) | (value >> 6)) & 255
            value = ((value ^ 187) + 1) % 256
        output[index] = value
    for index in range(count, len(output) - 2):
        output[index] = (221 + index) & 255
    output[-2:] = count.to_bytes(2, "big")
    return bytes(output)


def _dyn_hash(text: str) -> bytes:
    value = 2166136260
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & _MASK
        value = (value * 33) & _MASK
    return value.to_bytes(4, "big")


def _envelope(payload: bytes, words: tuple[int, ...]) -> str:
    ciphertext = _crypt(payload, words)
    key = struct.pack("<12I", *words)
    insertion = (sum(ciphertext) + sum(key)) % (len(ciphertext) + 1)
    binary = b"\x4b" + ciphertext[:insertion] + key + ciphertext[insertion:]
    return base64.b64encode(binary).decode("ascii").translate(_TRANSLATION)


def _dyn_payload(query: str, environment: Environment, timestamp: int,
                 state: SigningState, location: str) -> bytes:
    encode = _encode_dyn_value
    proof = _signed32(
        (timestamp >> 16) ^ (state.dynosaur_seed >> 16)
        ^ (timestamp & 65535) ^ (state.dynosaur_seed & 65535)
        | (environment.env_code << 16)
    )
    # The extension-not-initialized branch: no server extended proof/callback,
    # extension seed, or extension version. These are source defaults, not
    # captured proof values. Only this missing-extension branch is implemented.
    values = [
        _dyn_hash(""), _dyn_hash(query), _dyn_hash(environment.user_agent),
        encode(str(environment.env_code)), encode(str(environment.interaction_code)),
        encode(str(timestamp)), encode(str(environment.canvas_hash)),
        encode("5.3.2"), encode("1.0.0.417"), encode("0"),
        encode(str(state.total_requests)), encode(str(state.intercepted_requests)),
        encode(str(proof)), encode(str(state.dynosaur_seed)), encode("0"),
        _dyn_hash(""), encode("0"), encode("0"), encode(location),
        encode("0"), encode("0"), encode("0"),
    ]
    order = (19, 12, 11, 3, 5, 16, 9, 7, 0, 6, 21, 1, 10, 2, 8, 17, 14, 13, 18, 4, 20, 15)
    marker = bytes((94, 222, 223, 224, 0, 1))
    records = [marker, marker, marker] + [values[index] for index in order]
    checksum = 0
    for value in records:
        checksum ^= value[1]
    records[0] = encode(str(checksum), checksum=True)
    return b"".join(bytes([32 + index]) + len(value).to_bytes(2, "big") + value
                    for index, value in enumerate(records))


def sign(unsigned_url: str, state: SigningState, environment: Environment,
         *, timestamp_ms: int | None = None) -> SigningResult:
    """Sign an already serialized, empty-body GET item_list URL without network.

    The input URL is preserved, including query order, duplicates and escaping.
    Security parameters must be absent. State advances by one request and 24 RNG
    words; failed transports must not roll it back. This implements the tested
    no-extension SDK branch, not arbitrary extension proof configurations.
    """
    import time
    from urllib.parse import unquote, urlsplit

    if not isinstance(unsigned_url, str) or not unsigned_url.isascii() or "#" in unsigned_url:
        raise UnsupportedSigningState("supply an ASCII, percent-encoded URL without a fragment")
    try:
        url = urlsplit(unsigned_url)
    except ValueError:
        raise UnsupportedSigningState("unsupported request URL") from None
    if (url.scheme != "https" or url.netloc != "www.tiktok.com"
            or url.path != "/api/post/item_list/" or not url.query or url.fragment
            or any(ord(c) <= 32 or ord(c) == 127 for c in unsigned_url)):
        raise UnsupportedSigningState("unsupported request URL")
    if any(unquote(part.partition("=")[0]) in _SECURITY_FIELDS for part in url.query.split("&")):
        raise UnsupportedSigningState("request must not contain security parameters")
    if not isinstance(state, SigningState) or not isinstance(environment, Environment):
        raise UnsupportedSigningState("explicit signing state and environment are required")
    _validate_token(state.ms_token)
    if not all(_uint32(value) for value in (state.gnarly_seed, state.dynosaur_seed,
               state.total_requests, state.intercepted_requests, environment.env_code,
               environment.interaction_code)):
        raise UnsupportedSigningState("unsupported numeric signing state")
    if not (_uint32(environment.canvas_hash) or type(environment.canvas_hash) is int and environment.canvas_hash == -1):
        raise UnsupportedSigningState("unsupported canvas state")
    if (type(state.rng_words) is not list or len(state.rng_words) != 16
            or not all(type(value) is int for value in state.rng_words)
            or tuple(state.rng_words[:12]) != _RNG_PREFIX
            or not all(_uint32(value) for value in state.rng_words[13:])
            or type(state.rng_words[12]) is not int or not -(1 << 31) <= state.rng_words[12] < (1 << 31)
            or type(state.rng_index) is not int or not 0 <= state.rng_index < 8):
        raise UnsupportedSigningState("unsupported RNG state")
    if not isinstance(environment.user_agent, str) or not isinstance(environment.page_url, str):
        raise UnsupportedSigningState("explicit User-Agent and page URL are required")
    try:
        environment.user_agent.encode("utf-8")
        page = urlsplit(environment.page_url)
    except (ValueError, UnicodeError):
        raise UnsupportedSigningState("unsupported environment strings") from None
    if page.scheme != "https" or page.netloc != "www.tiktok.com" or not page.path.startswith("/@"):
        raise UnsupportedSigningState("unsupported public-profile context")
    location = (page.netloc + page.path)[:50]
    if not location.isascii():
        raise UnsupportedSigningState("percent-encode the public-profile context")
    if timestamp_ms is None:
        timestamp_ms = time.time_ns() // 1_000_000
    if type(timestamp_ms) is not int or not _uint32(timestamp_ms // 1000):
        raise UnsupportedSigningState("unsupported request time")
    if state.total_requests == _MASK or state.intercepted_requests == _MASK:
        raise UnsupportedSigningState("request counters exhausted")
    timestamp = timestamp_ms // 1000
    state.total_requests += 1
    state.intercepted_requests += 1
    dynosaur = _envelope(_dyn_payload(url.query, environment, timestamp, state, location), state.encryption_words())
    prefix = unsigned_url + "&X-Dynosaur=" + dynosaur + "&msToken=" + state.ms_token
    gnarly = generate_x_gnarly(
        query=prefix.partition("?")[2], user_agent=environment.user_agent,
        timestamp=timestamp,
        state=GnarlyState(environment.env_code, environment.interaction_code,
                          state.gnarly_seed, environment.canvas_hash,
                          state.total_requests, state.intercepted_requests, 2, False, False),
        key_words=state.encryption_words(),
    )
    fields = {"X-Dynosaur": dynosaur, "msToken": state.ms_token, "X-Bogus": "1", "X-Gnarly": gnarly}
    return SigningResult(prefix + "&X-Bogus=1&X-Gnarly=" + gnarly, fields)


@dataclass(frozen=True, repr=False)
class BrowserProfile:
    version: int
    language: str
    locale: str
    accept_language: str
    timezone: str
    width: int
    height: int
    history_length: int

    @property
    def user_agent(self) -> str:
        return (f"Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:{self.version}.0) "
                f"Gecko/20100101 Firefox/{self.version}.0")


def generate_browser() -> BrowserProfile:
    """Generate one coherent desktop context and keep it stable per session."""
    import secrets

    locale, language, accept_language, timezone = secrets.choice((
        ("en-US", "en", "en-US,en;q=0.9", "UTC"),
        ("pt-BR", "pt", "pt-BR,pt;q=0.9,en;q=0.8", "America/Sao_Paulo"),
    ))
    width, height = secrets.choice(((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)))
    return BrowserProfile(secrets.choice((156, 157)), language, locale,
                          accept_language, timezone, width, height, secrets.randbelow(3) + 1)


@dataclass(frozen=True, repr=False)
class Profile:
    handle: str
    sec_uid: str
    device_id: str
    odin_id: str
    web_id_created: str
    region: str

    @property
    def url(self) -> str:
        return "https://www.tiktok.com/@" + self.handle


def build_unsigned_url(profile: Profile, browser: BrowserProfile, *, cursor: str = "0") -> str:
    from urllib.parse import quote, urlencode

    if not isinstance(cursor, str):
        raise UnsupportedSigningState("cursor must be text")
    pairs = [
        ("WebIdLastTime", profile.web_id_created), ("aid", "1988"),
        ("app_language", browser.language), ("app_name", "tiktok_web"),
        ("browser_language", browser.locale), ("browser_name", "Mozilla"),
        ("browser_online", "true"), ("browser_platform", "Linux x86_64"),
        ("browser_version", browser.user_agent.removeprefix("Mozilla/")),
        ("channel", "tiktok_web"), ("cookie_enabled", "true"), ("count", "16"),
        ("coverFormat", "0"), ("cursor", cursor), ("data_collection_enabled", "false"),
        ("device_id", profile.device_id), ("device_platform", "web_pc"),
        ("focus_state", "true"), ("history_len", str(browser.history_length)),
        ("is_fullscreen", "false"), ("is_page_visible", "true"),
        ("language", browser.language), ("odinId", profile.odin_id), ("os", "linux"),
        ("priority_region", ""), ("referer", ""), ("region", profile.region),
        ("root_referer", ""), ("screen_height", str(browser.height)),
        ("screen_width", str(browser.width)), ("secUid", profile.sec_uid),
        ("tz_name", browser.timezone), ("user_is_login", "false"),
        ("video_encoding", "dash"), ("webcast_language", browser.language),
    ]
    return _ENDPOINT + "?" + urlencode(pairs, quote_via=quote)


class AcquisitionError(RuntimeError):
    """Redacted acquisition/response failure, never an empty-timeline fallback."""


class TimelineSession:
    """Fresh HTTP/2 cookie jar and locally generated browser/signing state."""

    def __init__(self):
        try:
            import httpx
            self.browser = generate_browser()
            self.client = httpx.Client(
                http2=True, follow_redirects=False, timeout=30,
                headers={"User-Agent": self.browser.user_agent,
                         "Accept-Language": self.browser.accept_language,
                         "Accept-Encoding": "identity"},
            )
        except ImportError:
            raise AcquisitionError("install httpx[http2] for network operations") from None
        self._httpx = httpx
        self.state: SigningState | None = None
        self.request_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _get(self, url: str, headers: dict[str, str]):
        try:
            request = self.client.build_request("GET", url, headers=headers)
            if str(request.url) != url:
                raise AcquisitionError("transport would change the signed URL")
            self.request_count += 1
            response = self.client.send(request)
        except self._httpx.HTTPError:
            raise AcquisitionError("HTTP request failed; inspect privately") from None
        if response.status_code != 200:
            raise AcquisitionError("unexpected HTTP status; no redirect followed")
        if response.http_version != "HTTP/2":
            raise AcquisitionError("HTTP/2 was not negotiated")
        return response

    def _refresh_token(self, response) -> None:
        token = response.headers.get("x-ms-token")
        issued = [cookie.value for cookie in response.cookies.jar if cookie.name == "msToken"]
        if token and issued and any(value != token for value in issued):
            raise AcquisitionError("inconsistent response token update")
        if token is None:
            if len(set(issued)) > 1:
                raise AcquisitionError("ambiguous cookie-only token update")
            if issued:
                token = issued[0]
        if token is not None:
            try:
                _validate_token(token)
            except UnsupportedSigningState:
                raise AcquisitionError("unsupported response token") from None
            if self.state is None:
                self.state = create_state(token)
            else:
                self.state.ms_token = token
        if self.state is None:
            raise AcquisitionError("profile response did not issue a usable session token")

    def bootstrap_profile(self, handle: str) -> Profile:
        import re
        from html.parser import HTMLParser

        if not isinstance(handle, str) or re.fullmatch(r"[A-Za-z0-9_.]{1,24}", handle) is None:
            raise AcquisitionError("unsupported public handle")
        response = self._get("https://www.tiktok.com/@" + handle, {"Accept": "text/html"})
        if "text/html" not in response.headers.get("content-type", "").lower():
            raise AcquisitionError("profile response is not HTML")

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.active = False
                self.parts = []

            def handle_starttag(self, tag, attrs):
                if tag == "script" and dict(attrs).get("id") == "__UNIVERSAL_DATA_FOR_REHYDRATION__":
                    self.active = True

            def handle_data(self, data):
                if self.active:
                    self.parts.append(data)

            def handle_endtag(self, tag):
                if tag == "script":
                    self.active = False

        parser = Parser()
        try:
            parser.feed(response.text)
            scopes = json.loads("".join(parser.parts))["__DEFAULT_SCOPE__"]
            detail = scopes["webapp.user-detail"]
            user = detail["userInfo"]["user"]
            context = scopes["webapp.app-context"]
            if (not isinstance(user, dict) or not isinstance(user.get("uniqueId"), str)
                    or type(detail["statusCode"]) is not int or detail["statusCode"] != 0
                    or user["uniqueId"].lower() != handle.lower() or user.get("privateAccount")):
                raise AcquisitionError("profile unavailable, restricted, or challenged")
            values = [user["uniqueId"], user["secUid"], context["wid"], context["odinId"],
                      context["webIdCreatedTime"], context["region"]]
            if not all(isinstance(value, str) and value for value in values):
                raise AcquisitionError("unsupported profile metadata")
        except (KeyError, TypeError, ValueError, RecursionError):
            raise AcquisitionError("profile metadata unavailable; inspect for a challenge") from None
        self._refresh_token(response)
        return Profile(*values)

    def fetch_page(self, profile: Profile, *, cursor: str = "0") -> dict:
        if self.state is None:
            raise AcquisitionError("bootstrap a profile before requesting a page")
        request = sign(build_unsigned_url(profile, self.browser, cursor=cursor), self.state,
                       Environment(self.browser.user_agent, profile.url))
        response = self._get(request.url, {"Accept": "*/*", "Referer": profile.url})
        self._refresh_token(response)
        if "application/json" not in response.headers.get("content-type", "").lower():
            raise AcquisitionError("listing response is not JSON")
        try:
            body = response.json()
        except (ValueError, RecursionError):
            raise AcquisitionError("empty or invalid JSON response; not an accepted request") from None
        if (not isinstance(body, dict) or type(body.get("statusCode")) is not int or body["statusCode"] != 0
                or type(body.get("status_code")) is not int or body["status_code"] != 0
                or not isinstance(body.get("itemList"), list) or type(body.get("hasMore")) is not bool
                or not isinstance(body.get("cursor"), str)):
            raise AcquisitionError("unsuccessful or unsupported listing response")
        if body["hasMore"] and (not body["cursor"] or body["cursor"] == cursor or not body["itemList"]):
            raise AcquisitionError("pagination cursor or items did not progress")
        for item in body["itemList"]:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not item["id"].isascii() or not item["id"].isdecimal()
                    or not isinstance(item.get("author"), dict)
                    or item["author"].get("secUid") != profile.sec_uid
                    or item["author"].get("uniqueId") != profile.handle):
                raise AcquisitionError("listing contains unexpected author or item data")
        return body

    def timeline(self, profile: Profile, *, pages: int = 2) -> dict:
        """Deduplicate and sort a bounded publication timeline, newest first."""
        from datetime import datetime, timezone

        if type(pages) is not int or pages <= 0:
            raise AcquisitionError("pages must be a positive integer")
        cursor = "0"
        seen_cursors = {cursor}
        posts = {}
        page_counts, new_counts = [], []
        has_more = True
        for _ in range(pages):
            body = self.fetch_page(profile, cursor=cursor)
            new_ids = {item["id"] for item in body["itemList"]} - posts.keys()
            if body["hasMore"] and body["itemList"] and not new_ids:
                raise AcquisitionError("page repeated previously collected posts")
            for item in body["itemList"]:
                posts.setdefault(item["id"], normalize_video(item, profile))
            page_counts.append(len(body["itemList"]))
            new_counts.append(len(new_ids))
            has_more = body["hasMore"]
            if not has_more:
                break
            cursor = body["cursor"]
            if cursor in seen_cursors:
                raise AcquisitionError("pagination cursor repeated")
            seen_cursors.add(cursor)
        videos = sorted(posts.values(), key=lambda video: (-video["create_time"], video["id"]))
        return {"author": profile.handle, "videos": videos, "pages_fetched": len(page_counts),
                "page_item_counts": page_counts, "page_new_counts": new_counts,
                "has_more": has_more, "complete": not has_more,
                "collected_at": datetime.now(timezone.utc).isoformat()}


def normalize_video(item: dict, profile: Profile) -> dict:
    from datetime import datetime, timezone

    timestamp = item.get("createTime")
    video, stats = item.get("video"), item.get("stats", {})
    if (type(timestamp) is not int or timestamp < 0 or not isinstance(video, dict)
            or item.get("imagePost") is not None
            or not isinstance(item.get("desc"), str) or not isinstance(stats, dict)
            or type(item.get("isPinnedItem", False)) is not bool):
        raise AcquisitionError("unsupported video metadata")
    try:
        published_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        raise AcquisitionError("unsupported publication time") from None
    counts = {key: stats[key] for key in
              ("playCount", "diggCount", "commentCount", "shareCount", "collectCount") if key in stats}
    if not all(type(value) is int and value >= 0 for value in counts.values()):
        raise AcquisitionError("unsupported engagement counts")
    duration = video.get("duration")
    if type(duration) is not int or duration < 0:
        raise AcquisitionError("unsupported video duration")
    return {"id": item["id"], "create_time": timestamp, "published_at": published_at,
            "caption": item["desc"], "pinned": item.get("isPinnedItem", False),
            "duration": duration, "stats": counts,
            "url": profile.url + "/video/" + item["id"]}


def fetch_timeline(handle: str, *, pages: int = 2) -> dict:
    """New Python-only session per call; no imported cookies or signer module."""
    if type(pages) is not int or pages <= 0:
        raise AcquisitionError("pages must be a positive integer")
    with TimelineSession() as session:
        profile = session.bootstrap_profile(handle.removeprefix("@") if isinstance(handle, str) else handle)
        return session.timeline(profile, pages=pages)


def validate_live() -> list[dict]:
    """Two fresh Python sessions, two targets, two pages; redacted proof only."""
    from dataclasses import asdict

    results = []
    visitors, tokens = set(), set()
    browsers = []
    for index in range(1, 3):
        with TimelineSession() as session:
            if list(session.client.cookies.jar) or session.state is not None:
                raise AcquisitionError("validation session was not initially empty")
            browsers.append(asdict(session.browser))
            for handle in ("laila_verissimo", "metropolesoficial"):
                before = session.request_count
                profile = session.bootstrap_profile(handle)
                if handle == "laila_verissimo":
                    if profile.device_id in visitors or session.state.ms_token in tokens:
                        raise AcquisitionError("fresh visitor/token state was not distinct")
                    visitors.add(profile.device_id)
                    tokens.add(session.state.ms_token)
                timeline = session.timeline(profile, pages=2)
                if (timeline["pages_fetched"] != 2
                        or not all(timeline["page_new_counts"])
                        or not all(timeline["page_item_counts"])):
                    raise AcquisitionError("live check did not establish initial and continuation pages")
                if session.state.total_requests != session.state.intercepted_requests:
                    raise AcquisitionError("signing state did not advance consistently")
                results.append({"session": index, "target": handle,
                                "page_items": timeline["page_item_counts"],
                                "new_items": timeline["page_new_counts"],
                                "unique_videos": len(timeline["videos"]),
                                "http_requests": session.request_count - before,
                                "http_version": "HTTP/2", "statusCode": 0, "status_code": 0,
                                "sorted": True, "fresh_session": True,
                                "randomized_browser": True})
    for result in results:
        result["distinct_initial_visitors_and_tokens"] = True
        result["browser_profiles_differ"] = browsers[0] != browsers[1]
    return results


_REQUEST_VECTORS = [
  {
    "dynosaur": "MkMN-X58jVxCrsegKZhkxJ4-X4ilu1ScWGGvhZePGwbXTHRJ640vIqErE20fAjUEoDiqeCKe9zXzStyJdjlkorkth8mHiPnA5ta-j0/hzuwkh-jP0BrEWE3Sd-KZyta1VzXvJ8j6bhD3Hp2C0TxdL31E7LjPRBdxmkJ2U1n87CeTUaLeLOb9crkYv3zZ3zc8jLeXJdRVo3A5QKfumEOL0sbGvdp0AfzRBlfoKUu0oLm5rKoMhY-Tf4lgh9jIN/KL2uMJlpu1mNQkZTHY7x1o0XBijqU1KNvLM-CHp126vfWu5FTvkFBeAfAD59F0M-1LGc1cMIPGbpDkA05T74LFxmYBVKM1FZeqY5d5AVNlg73H42AcxAcrjnmP5pW8R5zraZJBzGCUm8Hi-g7RG-YPhZA=",
    "gnarly": "MKJd-2vAMhL9xP69m1pzGuTq7ZMH4bVSDKeeUH09SAUIyWNoMnPeDVX-iJgTJ4K-RLsHT2v9NGjxrqi3i1JL7sgivP/94SRp/U5Wla6bUvPRSLx6TSdlI8/p7xZ9Qnm-ltN4uZd3BaOtwc0By0O/D2Q4nyFdhkHBY66Xeoq/bOox/C-S0aK6xf8QvDcvMNa6LLlZtYAr-Z23BCUdkQah694MEJRBsnwNm4lFfaF2LvCsEwfJ//bT2BJ9rlAYB64-HmPK/zEuJwvnM-Rlq7aUcuS8URUZkW-Sz01rb/r6jNOjSFUcI4jeFm4gSYP322nv",
    "rng_hash": "a6e12874b517738346ae11edbffb2a68fdd99be65013a8e5e0c0d297ca71ba7f"
  },
  {
    "dynosaur": "MRe/bpLKfgyBtMB0yy087SRNP4TOukQOEefaKUdXS0c6XrFOAXM2Xo5wa5-4jJWa3Zjaydk5I/R7j-VquTmhkxDOLYfE6qhVJfKi3HuuuoZUCTyHm24TALy3lqyuwQBFhyS2AUzh8fw9ZVlbWVgnO0ckkZyoFvRpwuz5ufCEx/BVhmqYaPk6KrEWeQp/AqYbkMVnui6O8gcSOcMHrdkVI3JkCd73OSCFpQ3ZoScbmzhE/DrPwPiIyRDhhpAau-kL9E-ScbOu6ipKYhI-tLZWr3gXWd0tvuTlCcOItR3tKYLGg2-USv0dwGfbDej0uGkylmAiF7HeDe6dhwvvu-/e5wGiZtVY0ZlRiLRD5WEaVBDAzC8269dhqiqgQAQZAas-YaAHD3/rLzz3X0s6F5-ZqpeWfhAVo-QQUk==",
    "gnarly": "Mxl9-z34iij/b6kUQjrWkgUvD4xvAGi8PiDNAMXSmTzc/pIja8i3bZ7sNd2EE/E0Nd2UimxrN8dYaqfGx0L/c2dEwQcKZ--BqGWpukP7fC4m0OVhg21LsLYeTSV20QtpsHNqNymkHSyA2ATQsSQwpLoUGMdDd3TEmtsILKWhjIuqjSRT2MJb2YSl8Ib6H0yMkJW745vf2JUj1K9E0u5nQcZ4Qiv91043qe5A8JwZen/Egx53BeEWWnYyVU6ioGO8Z90T2ZpvXHX31mDf/P76oIkKfzdim4HMLn8pNTS1pm2qj2jlebwLhQd/iVON1--NW3ggXOgnhI==",
    "rng_hash": "6816aa92467c74b41b053a344eb2a1f767823665be207b1b2b26e58e2362d067"
  }
]


def _self_tests() -> unittest.TestResult:
    from contextlib import redirect_stderr, redirect_stdout
    from dataclasses import asdict, replace
    from io import StringIO
    from types import SimpleNamespace
    from unittest.mock import patch

    class Tests(unittest.TestCase):
        def fixture(self, index=0):
            timestamp = (1791323574, 1791323600)[index]
            state = SigningState(
                "synthetic", (123456789, _MASK)[index], 123456789 + index,
                list(_RNG_PREFIX) + [_signed32(timestamp * 1000), 0x12345678, _MASK, 0],
                total_requests=(0, 6)[index], intercepted_requests=(0, 2)[index],
            )
            environment = Environment(
                ("Synthetic UA/1.0", "Synthetic ação 🎵")[index],
                "https://www.tiktok.com/@synthetic", (0, 32)[index], (0, 17)[index], (-1, _MASK)[index],
            )
            return _ENDPOINT + f"?cursor={index}&empty=&a=1&a=2&space=%20&literal=%2B", state, environment, timestamp * 1000

        def test_source_signature_vectors(self):
            for index, expected in enumerate(_REQUEST_VECTORS):
                with self.subTest(index=index):
                    url, state, environment, timestamp = self.fixture(index)
                    result = sign(url, state, environment, timestamp_ms=timestamp)
                    self.assertEqual(result.fields["X-Dynosaur"], expected["dynosaur"])
                    self.assertEqual(result.fields["X-Gnarly"], expected["gnarly"])
                    self.assertEqual(result.fields["X-Bogus"], "1")

        def test_source_rng_vectors(self):
            for index, expected in enumerate(_REQUEST_VECTORS):
                _, state, _, _ = self.fixture(index)
                words = [word for _ in range(4) for word in state.encryption_words()][:40]
                self.assertEqual(hashlib.sha256(struct.pack("<40I", *words)).hexdigest(), expected["rng_hash"])

        def test_seed_initialization(self):
            with patch("secrets.randbits", side_effect=[0x12345678, _MASK, 0, 0, 1 << 52, 1 << 51, 3 << 51]):
                state = create_state("synthetic", timestamp_ms=1791323574000)
            self.assertEqual((state.gnarly_seed, state.dynosaur_seed), (89021300, 89021800))

        def test_invalid_rng_rejected_before_mutation(self):
            url, state, environment, timestamp = self.fixture()
            state.rng_words = [float(value) for value in state.rng_words]
            before = asdict(state)
            with self.assertRaises(UnsupportedSigningState):
                sign(url, state, environment, timestamp_ms=timestamp)
            self.assertEqual(asdict(state), before)

        def test_invalid_url_rejected_before_mutation(self):
            url, state, environment, timestamp = self.fixture()
            before = asdict(state)
            for bad in (url + "#", url + "&msToken=private-marker",
                        url + "&%58-Gnarly=private-marker", url.replace("www.tiktok.com", "example.org")):
                with self.assertRaises(UnsupportedSigningState):
                    sign(bad, state, environment, timestamp_ms=timestamp)
                self.assertEqual(asdict(state), before)

        def test_counter_rng_and_token_continuation(self):
            url, state, environment, timestamp = self.fixture()
            first = sign(url, state, environment, timestamp_ms=timestamp)
            state.ms_token = "fresh-synthetic"
            saved = SigningState(**json.loads(json.dumps(asdict(state))))
            next_url = url.replace("cursor=0", "cursor=next%2Bopaque")
            second = sign(next_url, state, environment, timestamp_ms=timestamp + 1000)
            self.assertEqual(second, sign(next_url, saved, environment, timestamp_ms=timestamp + 1000))
            self.assertNotEqual(first.fields["X-Gnarly"], second.fields["X-Gnarly"])
            self.assertEqual(state.total_requests, 2)

        def test_generated_browser_and_query_are_consistent(self):
            from urllib.parse import parse_qs, urlsplit
            with patch("secrets.choice", side_effect=[
                ("pt-BR", "pt", "pt-BR,pt;q=0.9,en;q=0.8", "America/Sao_Paulo"),
                (1920, 1080), 156,
            ]), patch("secrets.randbelow", return_value=2):
                browser = generate_browser()
            profile = Profile("synthetic", "sec", "visitor", "odin", "100", "BR")
            query = parse_qs(urlsplit(build_unsigned_url(profile, browser, cursor="next+opaque")).query,
                             keep_blank_values=True)
            self.assertEqual(query["cursor"], ["next+opaque"])
            self.assertEqual(query["browser_version"], [browser.user_agent.removeprefix("Mozilla/")])
            self.assertEqual(query["screen_width"], ["1920"])
            self.assertEqual(query["language"], ["pt"])
            self.assertEqual(query["browser_language"], ["pt-BR"])
            self.assertEqual(query["tz_name"], ["America/Sao_Paulo"])
            self.assertEqual(query["history_len"], ["3"])
            self.assertFalse(_SECURITY_FIELDS & query.keys())
            self.assertNotIn("verifyFp", query)

        def item(self, identifier="1", timestamp=100, pinned=False):
            return {"id": identifier, "createTime": timestamp, "desc": "ação 🎵",
                    "author": {"uniqueId": "synthetic", "secUid": "sec"},
                    "video": {"duration": 10, "playAddr": "https://example.org/?signature=private-marker"},
                    "stats": {"playCount": 4}, "isPinnedItem": pinned}

        def session(self):
            session = object.__new__(TimelineSession)
            session.state = self.fixture()[1]
            session.browser = BrowserProfile(157, "en", "en-US", "en-US,en;q=0.9", "UTC", 1280, 720, 1)
            session.request_count = 0
            return session

        def profile(self):
            return Profile("synthetic", "sec", "visitor", "odin", "100", "BR")

        def page(self, items, cursor="next", more=True):
            return {"statusCode": 0, "status_code": 0, "itemList": items, "cursor": cursor, "hasMore": more}

        def test_timeline_dedup_sort_and_no_signed_media(self):
            session = self.session()
            pages = [
                self.page([self.item("1", 50, True), self.item("2", 300)]),
                self.page([self.item("1", 50, True), self.item("3", 200)], "last", False),
            ]
            with patch.object(session, "fetch_page", side_effect=pages) as fetch:
                result = session.timeline(self.profile(), pages=3)
            self.assertEqual([v["id"] for v in result["videos"]], ["2", "3", "1"])
            self.assertEqual(result["page_new_counts"], [2, 1])
            self.assertTrue(result["complete"])
            self.assertFalse(result["has_more"])
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args.kwargs["cursor"], "next")
            self.assertNotIn("private-marker", json.dumps(result))

        def test_terminal_pinned_overlap_is_not_a_loop(self):
            session = self.session()
            pinned = self.item("1", 50, True)
            with patch.object(session, "fetch_page", side_effect=[
                self.page([pinned, self.item("2", 100)]), self.page([pinned], "next", False),
            ]):
                result = session.timeline(self.profile(), pages=2)
            self.assertTrue(result["complete"])
            self.assertEqual(result["page_new_counts"], [2, 0])
            self.assertEqual(len(result["videos"]), 2)

        def test_page_limit_is_not_complete_history(self):
            session = self.session()
            session.fetch_page = lambda *args, **kwargs: self.page([self.item()])
            result = session.timeline(self.profile(), pages=1)
            self.assertFalse(result["complete"])
            self.assertTrue(result["has_more"])

        def test_repeated_ids_or_cursor_fail(self):
            for pages in (
                [self.page([self.item()]), self.page([self.item()], "last")],
                [self.page([self.item()]), self.page([self.item("2")], "next")],
                [self.page([self.item()]), self.page([self.item("2")], "0")],
            ):
                session = self.session()
                with patch.object(session, "fetch_page", side_effect=pages), self.assertRaises(AcquisitionError):
                    session.timeline(self.profile(), pages=2)

        def test_bad_or_non_video_metadata_fails(self):
            for item in (self.item() | {"video": None}, self.item() | {"createTime": True},
                         self.item() | {"createTime": 10**30}, self.item() | {"stats": {"playCount": -1}},
                         self.item() | {"video": {"duration": 0}, "imagePost": {"images": [{}]}},
                         self.item() | {"video": {"duration": 0}, "imagePost": {}}):
                with self.subTest(keys=list(item)), self.assertRaises(AcquisitionError):
                    normalize_video(item, self.profile())
            self.assertEqual(normalize_video(self.item() | {"imagePost": None}, self.profile())["id"], "1")

        def test_response_validation(self):
            good = self.page([self.item()])
            for body in (good | {"statusCode": False}, good | {"status_code": 1},
                         good | {"cursor": "0"}, good | {"itemList": []},
                         good | {"itemList": [self.item() | {"author": {"uniqueId": "other", "secUid": "other"}}]}):
                session = self.session()
                session._get = lambda *args: SimpleNamespace(headers={"content-type": "application/json"},
                                                             json=lambda: body)
                session._refresh_token = lambda response: None
                with self.assertRaises(AcquisitionError):
                    session.fetch_page(self.profile())

        def test_empty_listing_body_is_a_failure(self):
            session = self.session()
            def invalid_json():
                raise ValueError("private-marker")
            session._get = lambda *args: SimpleNamespace(
                headers={"content-type": "application/json"}, json=invalid_json,
            )
            session._refresh_token = lambda response: None
            with self.assertRaisesRegex(AcquisitionError, "empty or invalid JSON") as error:
                session.fetch_page(self.profile())
            self.assertNotIn("private-marker", str(error.exception))

        def test_token_update_and_conflicts(self):
            session = self.session()
            response = SimpleNamespace(headers={"x-ms-token": "fresh"}, cookies=SimpleNamespace(
                jar=[SimpleNamespace(name="msToken", value="fresh")]))
            session._refresh_token(response)
            self.assertEqual(session.state.ms_token, "fresh")
            response.cookies.jar[0].value = "different"
            with self.assertRaises(AcquisitionError):
                session._refresh_token(response)
            response.headers = {}
            response.cookies.jar.append(SimpleNamespace(name="msToken", value="another"))
            with self.assertRaises(AcquisitionError):
                session._refresh_token(response)
            self.assertEqual(session.state.ms_token, "fresh")

        def test_bootstrap_from_synthetic_html(self):
            metadata = {"__DEFAULT_SCOPE__": {
                "webapp.app-context": {"wid": "visitor", "odinId": "odin", "webIdCreatedTime": "100", "region": "BR"},
                "webapp.user-detail": {"statusCode": 0, "userInfo": {"user": {
                    "uniqueId": "synthetic", "secUid": "sec", "privateAccount": False}}},
            }}
            session = self.session()
            session.state = None
            response = SimpleNamespace(headers={"content-type": "text/html", "x-ms-token": "issued-synthetic"},
                                       cookies=SimpleNamespace(jar=[]),
                                       text='<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">' + json.dumps(metadata) + '</script>')
            session._get = lambda *args: response
            profile = session.bootstrap_profile("synthetic")
            self.assertEqual(profile.device_id, "visitor")
            self.assertEqual(profile.sec_uid, "sec")
            self.assertEqual(session.state.ms_token, "issued-synthetic")
            with self.assertRaises(AcquisitionError):
                session.bootstrap_profile("different")

        def test_transport_identity_http2_and_redaction(self):
            session = self.session()
            class HTTPError(Exception):
                pass
            session._httpx = SimpleNamespace(HTTPError=HTTPError)
            session.client = SimpleNamespace(
                build_request=lambda *args, **kwargs: SimpleNamespace(url="changed"),
                send=lambda request: None,
            )
            with self.assertRaisesRegex(AcquisitionError, "transport would change"):
                session._get("https://www.tiktok.com/", {})
            self.assertEqual(session.request_count, 0)
            session.client.build_request = lambda method, url, **kwargs: SimpleNamespace(url=url)
            session.client.send = lambda request: SimpleNamespace(status_code=200, http_version="HTTP/1.1")
            with self.assertRaisesRegex(AcquisitionError, "HTTP/2"):
                session._get("https://www.tiktok.com/", {})

        def test_cli_redacts_arguments_and_failures(self):
            for arguments in (["--unknown", "private-marker"], ["synthetic"]):
                output, errors = StringIO(), StringIO()
                with redirect_stdout(output), redirect_stderr(errors), patch(
                    __name__ + ".fetch_timeline", side_effect=AcquisitionError("private-marker")
                ):
                    try:
                        status = main(arguments)
                    except SystemExit as error:
                        status = error.code
                self.assertEqual(status, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertNotIn("private-marker", errors.getvalue())

    return unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    )


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, json.dumps({"error": "invalid_arguments"}) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("handle", nargs="?", help="public username, optionally prefixed with @")
    parser.add_argument("--pages", type=int, default=2, help="maximum pages; default 2")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--self-test", action="store_true", help="synthetic offline tests; no HTTP dependencies")
    modes.add_argument("--validate-live", action="store_true", help="network: fresh sessions, two targets, two pages")
    args = parser.parse_args(argv)
    if args.handle and (args.self_test or args.validate_live):
        parser.error("choose either a handle or validation mode")
    if args.self_test:
        result = _self_tests()
        print(json.dumps({"ok": result.wasSuccessful(), "tests": result.testsRun}))
        return 0 if result.wasSuccessful() else 1
    if not args.validate_live and not args.handle:
        parser.error("a handle or validation mode is required")
    try:
        result = validate_live() if args.validate_live else fetch_timeline(args.handle, pages=args.pages)
    except (AcquisitionError, UnsupportedSigningState):
        print(json.dumps({"error": "timeline_failed"}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
