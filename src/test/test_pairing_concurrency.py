from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tilauscope.pairing import PairingManager


def test_pairing_token_is_consumed_once_across_threads() -> None:
    pairing = PairingManager()
    token, _ttl = pairing.mint_pairing_token()
    barrier = Barrier(2)

    def pair(device_id: str) -> str | None:
        barrier.wait()
        return pairing.pair(token, device_id, device_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(pair, ('device-a', 'device-b')))

    assert sum(result is not None for result in results) == 1
