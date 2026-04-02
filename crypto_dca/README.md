# crypto_dca — Bitcoin DCA Bot

Monthly Dollar-Cost Averaging into Bitcoin via the **Kraken Pro API**, using **limit orders** to minimise fees, scheduled via **AWS Lambda + EventBridge**.

---

## Why limit orders?

| Order type | Fee tier | Fee on £100 buy |
|---|---|---|
| Market (taker) | 0.26% | £0.26 |
| Limit (maker)  | 0.16% | £0.16 |

Saving: ~38% on every trade. Over years of monthly DCA this compounds significantly.

The bot places a **post-only limit order** priced `ask + 0.1%` — just above the best ask — so it typically fills within seconds while still counting as a maker order. If it isn't filled within 30 minutes (e.g. during a sharp rally), it cancels and falls back to a market order to ensure the DCA always executes.

---

## Architecture

```
EventBridge (cron: 1st of month, 09:00 UTC)
         │
         ▼
  AWS Lambda (Python 3.12)
  ┌─────────────────────────────────────┐
  │  1. Fetch XXBTZGBP ticker           │
  │  2. Calculate limit price & volume  │
  │  3. Idempotency check (userref)     │
  │  4. Place post-only limit order     │
  │  5. Poll for fill (60s intervals)   │
  │  6. Fallback to market if timeout   │
  │  7. Send SES summary email          │
  └─────────────────────────────────────┘
         │
         ▼
  AWS SES (email notification)
  AWS CloudWatch Logs
  AWS SSM Parameter Store (secrets)
```

**Cost**: essentially £0/month — Lambda free tier covers 1 invocation/month comfortably.

---

## Files

```
crypto_dca/
├── config.py          # Config dataclass (env vars)
├── kraken_client.py   # Kraken REST API wrapper (HMAC-SHA512 auth)
├── dca_bot.py         # Lambda handler + DCA orchestration
├── notifier.py        # AWS SES email notifications
├── requirements.txt   # requests, boto3
├── .env.example       # Template for local development
└── deploy/
    ├── template.yaml  # AWS SAM (Lambda + EventBridge + IAM)
    └── Makefile       # make deploy / invoke / logs / store-secrets
```

---

## Prerequisites

- AWS account with CLI configured (`aws configure`)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- Kraken account with API key — generate at **Account → Security → API**
  - Required permissions: `Query Funds`, `Query Open Orders & Trades`, `Create & Modify Orders`
- SES sender email verified in AWS SES (or a verified sending domain)

---

## Setup

### 1. Store Kraken secrets in SSM Parameter Store

```bash
cd deploy
make store-secrets
```

This will prompt for your API key and secret and store them encrypted in SSM.

Or manually:
```bash
aws ssm put-parameter --name /dca/KRAKEN_API_KEY \
    --value "YOUR_KEY" --type SecureString --region eu-west-2

aws ssm put-parameter --name /dca/KRAKEN_API_SECRET \
    --value "YOUR_SECRET" --type SecureString --region eu-west-2
```

### 2. Verify your email in SES

```bash
aws ses verify-email-identity --email-address you@yourdomain.com --region eu-west-2
```

Check your inbox and click the verification link.

### 3. Deploy

```bash
cd deploy
make deploy SENDER_EMAIL=dca-bot@yourdomain.com RECIPIENT=you@yourdomain.com
```

SAM will package the Lambda, create the EventBridge schedule, and set up IAM permissions.

### 4. Test with a dry run

```bash
make invoke   # triggers the deployed Lambda once
```

Or locally (no AWS needed for the dry run logic):
```bash
cd ..
DRY_RUN=true KRAKEN_API_KEY=x KRAKEN_API_SECRET=x \
    python -c "from dca_bot import handler; print(handler({}, {}))"
```

### 5. Monitor

```bash
make logs     # stream CloudWatch logs live
```

---

## Configuration reference

| Env var | Default | Description |
|---|---|---|
| `KRAKEN_API_KEY` | required | Kraken API key |
| `KRAKEN_API_SECRET` | required | Kraken base64 private key |
| `DCA_AMOUNT_GBP` | `100` | Monthly GBP amount to invest |
| `KRAKEN_PAIR` | `XXBTZGBP` | Kraken trading pair |
| `LIMIT_OFFSET_PCT` | `0.001` | Limit price offset above ask (0.1%) |
| `ORDER_TIMEOUT_MINUTES` | `30` | Minutes before falling back to market order |
| `SES_SENDER_EMAIL` | — | Verified SES sender address |
| `SES_RECIPIENT_EMAIL` | — | Notification recipient address |
| `AWS_REGION` | `eu-west-2` | AWS region |
| `DRY_RUN` | `false` | Simulate without placing real orders |

---

## Idempotency

Each monthly run uses `userref = YYYYMM` (e.g. `202601` for January 2026). Kraken rejects a new order if an open order with the same `userref` already exists, preventing duplicate buys if Lambda is triggered more than once in a month.

---

## Changing the schedule

Edit `deploy/template.yaml`:

```yaml
Schedule: cron(0 9 1 * ? *)   # 1st of month, 09:00 UTC
```

Cron format: `cron(minutes hours day-of-month month day-of-week year)`

Examples:
- `cron(0 9 15 * ? *)` — 15th of each month
- `cron(0 7 1 * ? *)` — 1st of month at 07:00 UTC (good for UK mornings)
