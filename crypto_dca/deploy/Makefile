STACK_NAME   ?= crypto-dca-bot
REGION       ?= eu-west-2
SENDER_EMAIL ?= your-verified@email.com
RECIPIENT    ?= your-verified@email.com

# Build and deploy to AWS (first run will prompt for S3 bucket etc.)
deploy:
	cd .. && sam build --template deploy/template.yaml
	sam deploy \
		--stack-name $(STACK_NAME) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM \
		--parameter-overrides \
			SenderEmail=$(SENDER_EMAIL) \
			RecipientEmail=$(RECIPIENT) \
			DryRun=false

# Deploy in dry-run mode (no real orders placed)
deploy-dry:
	cd .. && sam build --template deploy/template.yaml
	sam deploy \
		--stack-name $(STACK_NAME)-dry \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM \
		--parameter-overrides \
			SenderEmail=$(SENDER_EMAIL) \
			RecipientEmail=$(RECIPIENT) \
			DryRun=true

# Invoke the Lambda directly (one-shot test)
invoke:
	aws lambda invoke \
		--function-name crypto-dca-bot \
		--region $(REGION) \
		--log-type Tail \
		--query 'LogResult' \
		--output text \
		/dev/stdout | base64 --decode

# Stream live CloudWatch logs
logs:
	aws logs tail /aws/lambda/crypto-dca-bot --follow --region $(REGION)

# Local test with env vars from .env file (requires sam cli + Docker)
local-invoke:
	cd .. && sam local invoke DCABotFunction \
		--template deploy/template.yaml \
		--env-vars deploy/local-env.json

# Store Kraken secrets in SSM Parameter Store
store-secrets:
	@read -p "Kraken API Key: " key; \
	aws ssm put-parameter --name /dca/KRAKEN_API_KEY --value "$$key" \
		--type SecureString --region $(REGION) --overwrite
	@read -sp "Kraken API Secret: " secret; echo; \
	aws ssm put-parameter --name /dca/KRAKEN_API_SECRET --value "$$secret" \
		--type SecureString --region $(REGION) --overwrite

# Delete the stack
destroy:
	aws cloudformation delete-stack --stack-name $(STACK_NAME) --region $(REGION)

.PHONY: deploy deploy-dry invoke logs local-invoke store-secrets destroy
