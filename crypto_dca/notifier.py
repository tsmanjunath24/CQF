"""
AWS SES email notifications for the DCA bot.
"""

import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from config import DCAConfig

logger = logging.getLogger(__name__)


def send_success_email(summary: dict[str, Any], config: DCAConfig) -> None:
    order_type_label = (
        "Limit order (maker)" if summary.get("order_type") == "limit" else "Market order (fallback)"
    )
    body = f"""Bitcoin DCA — Monthly Buy Complete
=====================================

Date/Time (UTC):  {summary.get('timestamp', 'N/A')}
Pair:             {summary.get('pair', 'N/A')}
Order type:       {order_type_label}
Transaction ID:   {summary.get('txid', 'N/A')}

Planned spend:    £{summary.get('gbp_planned', 0):.2f}
Actual spend:     £{summary.get('gbp_spent', 0):.2f}
Avg fill price:   £{summary.get('avg_price_gbp', 0):,.2f}
BTC acquired:     {summary.get('btc_acquired', 0):.8f} BTC

---
Fee tier: maker (0.16%) — saved vs taker (0.26%)
Fee saving vs market order: £{(summary.get('gbp_spent', 0) * 0.001):.4f}

This is an automated message from your crypto DCA bot.
"""
    _send(
        subject=f"[DCA] Bitcoin buy complete — £{summary.get('gbp_spent', 0):.2f} → {summary.get('btc_acquired', 0):.6f} BTC",
        body=body,
        config=config,
    )


def send_failure_email(error: str, config: DCAConfig) -> None:
    body = f"""Bitcoin DCA — Run FAILED
=========================

The monthly DCA bot encountered an error and could not complete the buy.

Error:
{error}

Action required:
  1. Check CloudWatch logs: /aws/lambda/crypto-dca-bot
  2. Verify your Kraken API key is valid and has Trade permissions
  3. Ensure your account has sufficient GBP balance
  4. Re-trigger manually if needed: aws lambda invoke --function-name crypto-dca-bot /dev/stdout

This is an automated message from your crypto DCA bot.
"""
    _send(
        subject="[DCA] ALERT — Bitcoin buy FAILED",
        body=body,
        config=config,
    )


def _send(subject: str, body: str, config: DCAConfig) -> None:
    if not config.notifications_enabled:
        logger.info("Notifications disabled — skipping email.")
        return
    try:
        ses = boto3.client("ses", region_name=config.aws_region)
        ses.send_email(
            Source=config.ses_sender_email,
            Destination={"ToAddresses": [config.ses_recipient_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
        logger.info("Email sent: %s", subject)
    except ClientError as exc:
        logger.error("Failed to send SES email: %s", exc)
