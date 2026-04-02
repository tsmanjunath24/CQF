"""
Bitcoin DCA Bot — AWS Lambda entry point.

Flow:
  1. Load config from environment variables
  2. Fetch current XXBTZGBP ticker
  3. Calculate limit price (ask + LIMIT_OFFSET_PCT) and BTC volume
  4. Check for existing open order this month (idempotency via userref=YYYYMM)
  5. Place post-only limit buy order
  6. Poll every 60 s until filled or ORDER_TIMEOUT_MINUTES elapses
  7. On timeout: cancel limit order, place market order as fallback
  8. Send SES email summarising the outcome
  9. Any unhandled exception → send failure email, re-raise (Lambda marks invocation failed)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

from config import DCAConfig
from kraken_client import KrakenAPIError, KrakenClient, OrderResult, OrderStatus
from notifier import send_failure_email, send_success_email

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

POLL_INTERVAL_SECONDS = 60


def _userref_for_month(dt: datetime) -> int:
    """Return an integer like 202601 that uniquely identifies this month's DCA run."""
    return int(dt.strftime("%Y%m"))


def run_dca(config: DCAConfig) -> dict[str, Any]:
    """
    Execute one DCA cycle.  Returns a summary dict suitable for logging / email.
    Raises on unrecoverable errors.
    """
    client = KrakenClient(config.kraken_api_key, config.kraken_api_secret)
    now = datetime.now(tz=timezone.utc)
    userref = _userref_for_month(now)

    # --- Step 1: Ticker ---
    ticker = client.get_ticker(config.kraken_pair)
    logger.info("Ticker %s — ask=%.2f bid=%.2f last=%.2f",
                config.kraken_pair, ticker.ask, ticker.bid, ticker.last)

    # --- Step 2: Limit price & volume ---
    limit_price = round(ticker.ask * (1 + config.limit_offset_pct), 2)
    btc_volume = config.dca_amount_gbp / limit_price
    logger.info("Planning limit buy: £%.2f @ £%.2f = %.8f BTC (userref=%d)",
                config.dca_amount_gbp, limit_price, btc_volume, userref)

    if config.dry_run:
        logger.info("DRY RUN — no order placed.")
        return {
            "dry_run": True,
            "pair": config.kraken_pair,
            "limit_price": limit_price,
            "btc_volume": btc_volume,
            "gbp_amount": config.dca_amount_gbp,
        }

    # --- Step 3: Idempotency check ---
    existing = client.get_open_orders_by_userref(userref)
    if existing:
        logger.warning("Open order(s) already exist for userref %d: %s — skipping placement.",
                       userref, existing)
        return {"skipped": True, "reason": "duplicate_userref", "existing_txids": existing}

    # --- Step 4: Place limit order ---
    order: OrderResult = client.place_limit_order(
        pair=config.kraken_pair,
        volume=btc_volume,
        price=limit_price,
        userref=userref,
    )
    logger.info("Limit order placed: txid=%s  desc='%s'", order.txid, order.description)

    # --- Step 5: Poll for fill ---
    deadline = time.monotonic() + config.order_timeout_minutes * 60
    final_status: OrderStatus | None = None

    while time.monotonic() < deadline:
        status = client.get_order_status(order.txid)
        logger.info("Order %s — status=%s vol_exec=%.8f / %.8f",
                    order.txid, status.status, status.vol_exec, status.vol)

        if status.status == "closed":
            final_status = status
            break
        if status.status in ("canceled", "expired"):
            raise KrakenAPIError(f"Order {order.txid} unexpectedly {status.status}")

        time.sleep(POLL_INTERVAL_SECONDS)

    # --- Step 6: Fallback to market order if limit timed out ---
    if final_status is None:
        logger.warning("Limit order %s not filled after %d min — cancelling and placing market order.",
                       order.txid, config.order_timeout_minutes)
        try:
            client.cancel_order(order.txid)
        except KrakenAPIError as exc:
            logger.warning("Cancel failed (order may have filled): %s", exc)

        # Re-check in case it filled during cancel race
        status = client.get_order_status(order.txid)
        if status.status == "closed":
            final_status = status
            logger.info("Order filled during cancel window — using limit fill.")
        else:
            fallback: OrderResult = client.place_market_order(
                pair=config.kraken_pair,
                volume=btc_volume,
                userref=userref,
            )
            logger.info("Market order placed: txid=%s", fallback.txid)
            # Wait up to 60 s for market fill confirmation
            for _ in range(6):
                time.sleep(10)
                mstatus = client.get_order_status(fallback.txid)
                if mstatus.status == "closed":
                    final_status = mstatus
                    break
            if final_status is None:
                final_status = mstatus  # best effort — may still be pending

    summary = {
        "txid": final_status.txid,
        "pair": config.kraken_pair,
        "status": final_status.status,
        "btc_acquired": final_status.vol_exec,
        "avg_price_gbp": final_status.price,
        "gbp_spent": final_status.cost,
        "gbp_planned": config.dca_amount_gbp,
        "order_type": "limit" if final_status.txid == order.txid else "market_fallback",
        "timestamp": now.isoformat(),
    }
    logger.info("DCA complete: %s", summary)
    return summary


def handler(event: dict, context: Any) -> dict:
    """AWS Lambda entry point."""
    config = DCAConfig()
    try:
        summary = run_dca(config)
        if config.notifications_enabled and not config.dry_run and not summary.get("skipped"):
            send_success_email(summary, config)
        return {"statusCode": 200, "body": summary}
    except Exception as exc:
        logger.exception("DCA run failed: %s", exc)
        if config.notifications_enabled:
            send_failure_email(str(exc), config)
        raise
