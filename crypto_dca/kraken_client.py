"""
Kraken REST API client.

Uses raw requests + HMAC-SHA512 signing as documented at:
https://docs.kraken.com/api/docs/guides/global-intro
"""

import base64
import hashlib
import hmac
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests


KRAKEN_API_URL = "https://api.kraken.com"


@dataclass
class Ticker:
    ask: float
    bid: float
    last: float


@dataclass
class OrderResult:
    txid: str
    description: str


@dataclass
class OrderStatus:
    txid: str
    status: str          # "open", "closed", "canceled", "expired", "pending"
    vol: float           # total volume ordered
    vol_exec: float      # volume filled so far
    price: float         # average fill price (0 if unfilled)
    cost: float          # total cost in quote currency


class KrakenAPIError(Exception):
    pass


class KrakenClient:
    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "crypto-dca-bot/1.0"})

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    def get_ticker(self, pair: str) -> Ticker:
        """Return best ask, bid and last trade price for the given pair."""
        resp = self._session.get(
            f"{KRAKEN_API_URL}/0/public/Ticker",
            params={"pair": pair},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["error"]:
            raise KrakenAPIError(f"Ticker error: {data['error']}")

        # Kraken may return the pair under an alias key; grab first result
        result = next(iter(data["result"].values()))
        return Ticker(
            ask=float(result["a"][0]),
            bid=float(result["b"][0]),
            last=float(result["c"][0]),
        )

    # ------------------------------------------------------------------
    # Private endpoints
    # ------------------------------------------------------------------

    def place_limit_order(
        self,
        pair: str,
        volume: float,
        price: float,
        userref: int,
    ) -> OrderResult:
        """
        Place a GTC limit buy order.

        userref is used as an idempotency key — if an open order with the
        same userref already exists Kraken will reject the duplicate.
        """
        data = {
            "ordertype": "limit",
            "type": "buy",
            "pair": pair,
            "volume": f"{volume:.8f}",
            "price": f"{price:.2f}",
            "userref": userref,
            "oflags": "post",   # post-only: reject if order would execute as taker
        }
        result = self._private_request("/0/private/AddOrder", data)
        txids = result.get("txid", [])
        if not txids:
            raise KrakenAPIError("AddOrder returned no txid")
        return OrderResult(
            txid=txids[0],
            description=result.get("descr", {}).get("order", ""),
        )

    def place_market_order(self, pair: str, volume: float, userref: int) -> OrderResult:
        """Fallback market buy order (used when limit order times out)."""
        data = {
            "ordertype": "market",
            "type": "buy",
            "pair": pair,
            "volume": f"{volume:.8f}",
            "userref": userref + 1,  # different userref so it isn't blocked
        }
        result = self._private_request("/0/private/AddOrder", data)
        txids = result.get("txid", [])
        if not txids:
            raise KrakenAPIError("AddOrder (market) returned no txid")
        return OrderResult(
            txid=txids[0],
            description=result.get("descr", {}).get("order", ""),
        )

    def get_order_status(self, txid: str) -> OrderStatus:
        """Query a single order by transaction ID."""
        result = self._private_request("/0/private/QueryOrders", {"txid": txid})
        if txid not in result:
            raise KrakenAPIError(f"Order {txid} not found in QueryOrders response")
        o = result[txid]
        return OrderStatus(
            txid=txid,
            status=o["status"],
            vol=float(o["vol"]),
            vol_exec=float(o["vol_exec"]),
            price=float(o["price"]),
            cost=float(o["cost"]),
        )

    def cancel_order(self, txid: str) -> None:
        """Cancel an open order."""
        self._private_request("/0/private/CancelOrder", {"txid": txid})

    def get_open_orders_by_userref(self, userref: int) -> list[str]:
        """Return list of txids for any open orders matching userref."""
        result = self._private_request("/0/private/OpenOrders", {"userref": userref})
        open_orders = result.get("open", {})
        return [
            txid
            for txid, order in open_orders.items()
            if order.get("userref") == userref
        ]

    # ------------------------------------------------------------------
    # Auth & transport
    # ------------------------------------------------------------------

    def _private_request(self, urlpath: str, data: dict) -> dict:
        data["nonce"] = str(int(time.time() * 1000))
        headers = {
            "API-Key": self._api_key,
            "API-Sign": self._sign(urlpath, data),
        }
        resp = self._session.post(
            f"{KRAKEN_API_URL}{urlpath}",
            data=data,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload["error"]:
            raise KrakenAPIError(f"Kraken API error: {payload['error']}")
        return payload["result"]

    def _sign(self, urlpath: str, data: dict) -> str:
        """
        HMAC-SHA512 signature as required by Kraken private endpoints.
        Signature = HMAC-SHA512(urlpath + SHA256(nonce + POST_data), base64_decoded_secret)
        """
        post_data = urllib.parse.urlencode(data)
        encoded = (data["nonce"] + post_data).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        secret = base64.b64decode(self._api_secret)
        signature = hmac.new(secret, message, hashlib.sha512)
        return base64.b64encode(signature.digest()).decode()
