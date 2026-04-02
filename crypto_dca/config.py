import os
from dataclasses import dataclass, field


@dataclass
class DCAConfig:
    # Kraken credentials (loaded from SSM / env vars)
    kraken_api_key: str = field(default_factory=lambda: os.environ["KRAKEN_API_KEY"])
    kraken_api_secret: str = field(default_factory=lambda: os.environ["KRAKEN_API_SECRET"])

    # Trade parameters
    dca_amount_gbp: float = field(
        default_factory=lambda: float(os.environ.get("DCA_AMOUNT_GBP", "100"))
    )
    kraken_pair: str = field(
        default_factory=lambda: os.environ.get("KRAKEN_PAIR", "XXBTZGBP")
    )
    # How far above the current ask to set limit price (0.001 = 0.1%).
    # Keeps us in the order book just above best ask — typically fills within seconds
    # while still qualifying for the maker fee tier (0.16% vs 0.26% taker).
    limit_offset_pct: float = field(
        default_factory=lambda: float(os.environ.get("LIMIT_OFFSET_PCT", "0.001"))
    )
    # Minutes to wait for limit order fill before cancelling and falling back to market
    order_timeout_minutes: int = field(
        default_factory=lambda: int(os.environ.get("ORDER_TIMEOUT_MINUTES", "30"))
    )

    # AWS SES notification
    ses_sender_email: str = field(
        default_factory=lambda: os.environ.get("SES_SENDER_EMAIL", "")
    )
    ses_recipient_email: str = field(
        default_factory=lambda: os.environ.get("SES_RECIPIENT_EMAIL", "")
    )
    aws_region: str = field(
        default_factory=lambda: os.environ.get("AWS_REGION", "eu-west-2")
    )

    # Set DRY_RUN=true to simulate without placing real orders
    dry_run: bool = field(
        default_factory=lambda: os.environ.get("DRY_RUN", "false").lower() == "true"
    )

    @property
    def notifications_enabled(self) -> bool:
        return bool(self.ses_sender_email and self.ses_recipient_email)
