NunuIRL staging runbook

This file explains how to run a staging stack locally and basic secrets guidance.

NunuIRL staging runbook

This document explains how to run a local staging stack, fetch secrets for staging, and includes a short troubleshooting checklist.

## Quick start (local staging)

From the `infra/` directory:

PowerShell (Windows):

```powershell
# Fetch secrets into .env.staging (see below for details)
.\fetch_secrets.ps1 -SecretName 'nunuirl/staging' -OutFile '.env.staging'

docker compose -f docker-compose.staging.yml up -d --build
```

Bash (Linux/macOS/WSL):

```bash
./fetch_secrets.sh nunuirl/staging .env.staging
docker compose -f docker-compose.staging.yml up -d --build
```

Ensure `.env.staging` contains required variables like `NUNUIRL_API_KEY`, `DISCORD_WEBHOOK_URL`, `POSTGRES_PASSWORD`, etc. Do not commit this file to git.

## Fetch secrets

Two helper scripts are included:

- `fetch_secrets.sh` (bash) — usage: `./fetch_secrets.sh <secret-name> <out-file> [format]`
- `fetch_secrets.ps1` (PowerShell) — usage: `.
	\fetch_secrets.ps1 -SecretName <name> -OutFile <file> [-Format dotenv|json]`

Both default to `dotenv` output (KEY=VALUE). If you prefer raw JSON, pass `json` as the format.

Example (dotenv):

```bash
./infra/fetch_secrets.sh my/secret/name .env.staging
```

Example (json):

```powershell
.\infra\fetch_secrets.ps1 -SecretName 'my/secret' -OutFile 'secret.json' -Format json
```

### Expected secret shape

The secret value should be a JSON object with top-level string keys and values. Example:

```json
{
	"NUNUIRL_API_KEY": "xxxxx",
	"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/...",
	"POSTGRES_PASSWORD": "pass"
}
```

## IAM / Permissions (AWS)

The identity used to call AWS Secrets Manager must have permission to call `secretsmanager:GetSecretValue` for the secret ARN or name.

Minimal example policy:

```json
{
	"Version": "2012-10-17",
	"Statement": [
		{
			"Effect": "Allow",
			"Action": ["secretsmanager:GetSecretValue"],
			"Resource": ["arn:aws:secretsmanager:REGION:ACCOUNT:secret:nunuirl/*"]
		}
	]
}
```

## Safety & rotation

- Never commit `.env.staging` to git. Add it to `.gitignore` if necessary.
- If a secret is exposed, rotate the key and update the secret in the secrets manager immediately.

## Troubleshooting

- `aws: command not found` — install and configure the AWS CLI (or use the PowerShell helper which requires AWSPowerShell.NetCore).
- `jq: command not found` — install jq (homebrew / apt / chocolatey).
- `Secret string is not valid JSON` — verify the secret value in the manager is a JSON object (use the console to inspect).
- `docker compose` errors — check that ports 8000/3000/9090/9093 are free, and try `docker compose down --remove-orphans -v` before `up`.

## Verification (sanity)

1. Fetch secrets and bring up staging:

```powershell
.\infra\fetch_secrets.ps1 -SecretName 'nunuirl/staging' -OutFile '.env.staging'
docker compose -f docker-compose.staging.yml up -d --build
```

2. Run synthetic alert (PowerShell from `infra/`):

```powershell
powershell -File .\alert_test.ps1 -SendSyntheticAlert
```

3. Inspect Alertmanager at `http://localhost:9093` and confirm Discord receives the alert.

## Do not check in

Add `.env.staging` to `.gitignore` if you have a local copy. Treat it like any other secret.

End of staging runbook
