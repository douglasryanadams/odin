# AWS Setup Guide

Manual steps to provision the production environment. Update this file as you go — commands are a starting point, not guaranteed to be verbatim correct for your account.

## Architecture

```
Browser → CloudFront (HTTPS, ACM cert) → EC2 t4g.small (HTTP:8000)
               └─ /static/* cached           └─ docker-compose
               └─ /* pass-through                 ├─ web:8000
                  (120s SSE timeout)              ├─ searxng:8080
                                                  ├─ searxng-valkey
                                                  └─ odin-valkey

Magic link emails → Purelymail (SMTP relay, port 587)
```

Shield Standard (DDoS) is included free with CloudFront. EC2 port 8000 is locked to the CloudFront origin prefix list — not publicly reachable.

---

## Prerequisites

- AWS account with admin access, signed into the AWS Console
- A domain you control (to point at Route 53)
- The default region for almost every step is **US West (Oregon) us-west-2**. The only exception is ACM (step 3) and the CloudFront viewer certificate, which must live in **US East (N. Virginia) us-east-1**. When a step says "switch the region picker," it means the dropdown in the top-right of the console.

As you work through the steps, keep a scratchpad. Several sections produce values that later sections need. Each section flags those with a "**Note this**" callout.

---

## 1. ECR Repository

Region: **us-west-2**.

1. Open the **Elastic Container Registry** console → **Repositories** → **Create repository**.
2. Visibility settings: **Private**.
3. Repository name: `odin`. Leave the rest at defaults (mutable tags, no scan-on-push required for P0).
4. **Create**.
5. Open the new repository and copy the **URI** at the top of the page. It looks like `123456789012.dkr.ecr.us-west-2.amazonaws.com/odin`.

**Note this:** the repository URI and the 12-digit AWS account ID embedded in it. You'll need both later.

---

## 2. Route 53 Hosted Zone

Region: not applicable (Route 53 is global).

If you registered the domain through Route 53, AWS automatically created a public hosted zone for it and pointed its NS records at AWS nameservers. Open **Route 53** → **Hosted zones** and confirm `yourdomain.com` is listed; you're done with this step.

If the domain is registered elsewhere:

1. Open the **Route 53** console → **Hosted zones** → **Create hosted zone**.
2. Domain name: `yourdomain.com`. Type: **Public hosted zone**.
3. **Create hosted zone**.
4. On the zone detail page, find the **NS** record. Copy the four name-server values.
5. Sign in to your domain registrar and replace the nameservers for `yourdomain.com` with those four values. DNS propagation may take up to 48 hours.

ACM DNS validation (step 3) needs this zone to exist, so do not skip ahead.

---

## 3. ACM Certificate

Region: **us-east-1** (CloudFront requirement). Switch the region picker before you start.

1. Open the **AWS Certificate Manager** console → **Request a certificate**.
2. **Request a public certificate** → **Next**.
3. Fully qualified domain name: `yourdomain.com`. Click **Add another name to this certificate** and add `*.yourdomain.com`.
4. Validation method: **DNS validation**.
5. Key algorithm: **RSA 2048**.
6. **Request**.
7. On the certificate detail page, expand the **Domains** section. For each row, click **Create record in Route 53** → **Create records**. ACM writes the CNAME validation records into the hosted zone for you.
8. Refresh the page every minute or so. The status flips from *Pending validation* to *Issued* (usually within ~5 minutes).

**Note this:** the certificate **ARN** (top of the page). CloudFront in step 9 needs it.

---

## 4. IAM — EC2 Instance Role

Region: not applicable (IAM is global).

This role lets the EC2 instance (a) be managed by SSM Session Manager, (b) pull images from ECR, and (c) read its secrets from Secrets Manager.

### 4a. Create the role

1. Open the **IAM** console → **Roles** → **Create role**.
2. Trusted entity type: **AWS service**. Use case: **EC2**. **Next**.
3. Permissions — search for and check **AmazonSSMManagedInstanceCore**. (Skip the others; you'll add inline policies next.) **Next**.
4. Role name: `odinInstanceRole`. **Create role**.

### 4b. Add the ECR pull inline policy

1. Open the role → **Add permissions** → **Create inline policy** → **JSON** tab.
2. Paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
       "Resource": "*"
     }]
   }
   ```
3. **Next**. Policy name: `ecr-pull`. **Create policy**.

### 4c. Add the Secrets Manager read inline policy

Same flow as 4b. JSON (replace `<account-id>` with your 12-digit account ID from step 1):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "arn:aws:secretsmanager:us-west-2:<account-id>:secret:odin/*"
  }]
}
```

Policy name: `secrets-read`.

### 4d. Attach the CloudWatch Logs managed policy

The `awslogs` driver in `docker-compose.awslogs.yml` calls `logs:CreateLogStream` / `logs:PutLogEvents` at container start; without these permissions the first deploy fails before any container reaches *running*.

1. Role → **Add permissions** → **Attach policies**.
2. Search for `CloudWatchAgentServerPolicy` → check it → **Add permissions**.

### 4e. Instance profile

When you create a role with the **EC2** trusted-entity use case, IAM auto-creates a matching instance profile of the same name (`odinInstanceRole`). You can confirm by running through the EC2 launch wizard in step 8 — `odinInstanceRole` will appear in the IAM instance profile dropdown. No extra clicks needed here.

---

## 5. IAM — GitHub Actions OIDC Role

Region: not applicable.

### 5a. Create the OIDC provider (skip if it already exists)

1. **IAM** console → **Identity providers** → **Add provider**.
2. Provider type: **OpenID Connect**.
3. Provider URL: `https://token.actions.githubusercontent.com`.
4. Audience: `sts.amazonaws.com`.
5. **Add provider**.

AWS manages the OIDC thumbprint for `token.actions.githubusercontent.com` automatically; the wizard has no thumbprint field.

### 5b. Create the role

1. **IAM** console → **Roles** → **Create role**.
2. Trusted entity type: **Web identity**. Identity provider: `token.actions.githubusercontent.com`. Audience: `sts.amazonaws.com`.
3. GitHub organization: `douglasryanadams`. GitHub repository: `odin`. Leave branch/tag empty for now (you'll tighten the trust policy in 5c).
4. **Next**. Skip permissions for now (you'll add inline policies after creation). **Next**.
5. Role name: `GitHubActionsOdinDeploy`. **Create role**.

### 5c. Tighten the trust policy

The wizard generates a fairly permissive condition. Replace it with one that pins to the repo only:

1. Open the role → **Trust relationships** tab → **Edit trust policy**.
2. Replace the `Condition` block so the full document looks like this (substitute your account ID):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": {"Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"},
       "Action": "sts:AssumeRoleWithWebIdentity",
       "Condition": {
         "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
         "StringLike": {"token.actions.githubusercontent.com:sub": "repo:douglasryanadams/odin:*"}
       }
     }]
   }
   ```
3. **Update policy**.

### 5d. Add the ECR push inline policy

Role → **Permissions** tab → **Add permissions** → **Create inline policy** → **JSON**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:PutImage",
                 "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload"],
      "Resource": "arn:aws:ecr:us-west-2:<account-id>:repository/odin"
    }
  ]
}
```

Policy name: `ecr-push`.

### 5e. Add the SSM deploy inline policy

Same flow:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ssm:SendCommand", "ssm:GetCommandInvocation"],
    "Resource": "*"
  }]
}
```

Policy name: `ssm-deploy`.

**Note this:** the role ARN (shown at the top of the role page). The deploy workflow needs it.

---

## 6. Secrets Manager

Region: **us-west-2**.

A single secret named `odin/app` holds every runtime credential as JSON. One billing line, one `GetSecretValue` call at boot, and the IAM policy in step 4c (`odin/*`) already covers it.

1. Open the **Secrets Manager** console → **Store a new secret**.
2. Secret type: **Other type of secret**.
3. Switch to the **Plaintext** tab and paste this placeholder (you'll fill in real values in steps 7d and 12):
   ```json
   {
     "anthropic_api_key": "placeholder",
     "secret_key": "placeholder",
     "app_url": "placeholder",
     "searxng_secret": "placeholder",
     "smtp_host": "placeholder",
     "smtp_from": "placeholder",
     "smtp_user": "placeholder",
     "smtp_pass": "placeholder"
   }
   ```
4. Encryption key: **aws/secretsmanager** (default).
5. **Next**.
6. Secret name: `odin/app`. Description: `Odin runtime credentials — Anthropic, SearXNG, Purelymail SMTP`.
7. **Next** through automatic rotation (skip — leave **Disable automatic rotation**).
8. **Next** → **Store**.

---

## 7. Purelymail (email)

Region: not applicable (Purelymail is external; the only AWS touchpoint is the Route 53 DNS records in 7b).

Magic links are sent over SMTP. The app defaults to Purelymail (`smtp.purelymail.com:587`); override `SMTP_HOST`/`SMTP_FROM` if you prefer a different provider. Either way the app only needs standard SMTP credentials.

### 7a. Create a Purelymail account and add your domain

1. Sign up at **purelymail.com** and pay the one-time or annual fee.
2. **Domains → Add domain** → enter `yourdomain.com`.
3. Purelymail shows the DNS records you need to add. Keep that page open for the next step.

### 7b. Add DNS records in Route 53

In the Route 53 console, open the hosted zone for `yourdomain.com` and add the records Purelymail listed. Typical set:

- **MX** at the apex pointing to Purelymail's inbound hosts
- **TXT** at the apex containing the SPF policy (`v=spf1 include:_spf.purelymail.com -all`)
- **TXT** at `<selector>._domainkey.yourdomain.com` containing the DKIM public key
- **TXT** at `_dmarc.yourdomain.com` containing the DMARC policy

Use the exact values Purelymail's domain page shows; copy them verbatim. Verification usually completes within a few minutes once the records propagate. Purelymail's domain page will flip each row to a green check when it sees the record.

### 7c. Create the sending mailbox

1. **Users → Create user** → mailbox `odin@yourdomain.com`.
2. Set a strong password — this doubles as the SMTP submission password.
3. Note the SMTP endpoint:

```
Host:  smtp.purelymail.com
Port:  587  (STARTTLS)
User:  odin@yourdomain.com
Pass:  <password from step 7c.2>
```

### 7d. Store credentials in Secrets Manager

1. **Secrets Manager** console → open `odin/app` → **Retrieve secret value** → **Edit**.
2. Switch to the **Plaintext** tab. Replace the four `smtp_*` placeholder values with the real ones from step 7c, leaving the other keys untouched for now:
   ```json
   {
     "anthropic_api_key": "placeholder",
     "secret_key": "placeholder",
     "app_url": "placeholder",
     "searxng_secret": "placeholder",
     "smtp_host": "smtp.purelymail.com",
     "smtp_from": "odin@yourdomain.com",
     "smtp_user": "odin@yourdomain.com",
     "smtp_pass": "<password from step 7c.2>"
   }
   ```
3. **Save**.

---

## 8. EC2 Instance

Region: **us-west-2**.

### 8a. Security group

1. **EC2** console → **Security Groups** → **Create security group**.
2. Name: `odin-sg`. Description: `Odin — CloudFront to app`. VPC: default.
3. Inbound rules → **Add rule**:
   - Type: **Custom TCP**
   - Port range: `8000`
   - Source type: **Custom**
   - In the source field, start typing `pl-` and pick the prefix list named **`com.amazonaws.global.cloudfront.origin-facing`** — this is the IPv4 list. AWS also exposes `com.amazonaws.global.ipv6.cloudfront.origin-facing`; do not pick that one. CloudFront edges contact origins over IPv4 by default, so an IPv6-only rule silently drops every connection from CloudFront and requests hang until the origin response timeout fires. (Both prefix lists are AWS-managed lists of CloudFront edge IPs; the IPv4 one locks port 8000 to CloudFront only.)
4. Outbound rules: leave the default *all traffic* rule.
5. **Create security group**.

### 8b. Launch the instance

1. **EC2** console → **Instances** → **Launch instances**.
2. Name: `odin`.
3. Application and OS: **Amazon Linux** → AMI: **Amazon Linux 2023 AMI** → architecture: **64-bit (Arm)**.
4. Instance type: `t4g.small`.
5. Key pair: **Proceed without a key pair**. (You'll connect via SSM Session Manager, not SSH.)
6. Network settings → **Edit**:
   - VPC: default. Subnet: **No preference**. Auto-assign public IP: **Enable**.
   - Firewall: **Select existing security group** → pick `odin-sg`.
7. Configure storage: change the root volume to **20 GiB**, type **gp3**.
8. Expand **Advanced details**:
   - **IAM instance profile**: `odinInstanceRole`.
   - **User data**: paste the script below. Leave **User data has been base64 encoded** unchecked.
     ```bash
     #!/bin/bash
     dnf install -y docker git jq
     systemctl enable --now docker
     usermod -aG docker ec2-user
     mkdir -p /usr/local/lib/docker/cli-plugins

     # Enable memory overcommit for Valkey/Redis background saves
     echo "vm.overcommit_memory = 1" > /etc/sysctl.d/99-valkey.conf
     sysctl -w vm.overcommit_memory=1

     # docker compose plugin
     curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64 \
       -o /usr/local/lib/docker/cli-plugins/docker-compose
     chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

     # docker buildx plugin (required by `docker compose build` ≥ v2.30)
     BUILDX_VERSION=v0.19.0
     curl -SL https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-arm64 \
       -o /usr/local/lib/docker/cli-plugins/docker-buildx
     chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

     git clone https://github.com/douglasryanadams/odin.git /opt/odin
     ```
9. **Launch instance**.

**Note this:** the **Instance ID** (e.g. `i-0abc123...`) from the launch confirmation. GitHub Actions secrets in step 11 need it.

### 8c. Allocate and associate an Elastic IP

1. **EC2** console → **Elastic IPs** → **Allocate Elastic IP address** → defaults → **Allocate**.
2. With the new EIP selected: **Actions** → **Associate Elastic IP address**. Resource type: **Instance**. Pick the `odin` instance. **Associate**.

**Note this:** the public IPv4 address of the EIP. CloudFront in step 9 uses it as the origin.

### 8d. Verify SSM is reachable

The SSM agent on Amazon Linux 2023 starts automatically; give it ~2 minutes after the instance reaches *Running*.

1. **EC2** console → **Instances** → select `odin` → **Connect** → **Session Manager** tab → **Connect**.
2. A browser shell should open. Type `whoami` to confirm you're in. Close the tab.

If the **Connect** button is disabled, the agent hasn't registered yet — wait another minute and refresh.

---

## 9. CloudFront Distribution

Region: not applicable (CloudFront is global; the console may keep showing N. Virginia).

1. Open the **CloudFront** console → **Distributions** → **Create distribution**.
2. **Choose a plan**: pick **Free** ($0/month, 1M requests + 100 GB transfer + 5 GB S3 storage). For Odin's launch traffic that's ~33k requests/day of headroom. AWS WAF and DDoS protection are bundled into every plan, including Free, at no extra charge.
3. **Specify origin** page:
   - **Origin type**: pick **Other** (publicly resolvable URL). (VPC origin is the cleaner long-term option since it removes the EIP requirement, but it's gated behind extra setup; punt on it for P0.)
   - **Origin domain**: the EC2 instance's **Public IPv4 DNS** (e.g. `ec2-44-230-41-145.us-west-2.compute.amazonaws.com`), shown on the EC2 instance detail page. The **Other** origin type requires a hostname, not a raw IP. The public DNS is stable as long as the EIP stays attached; if the EIP ever changes, update this field to the new EC2 public DNS.
   - **Origin path**: leave blank.
   - **Origin settings**: pick **Customize origin settings**, then set:
     - Protocol: **HTTP only**
     - HTTP port: `8000`
     - Origin response timeout: `120` (max allowed; range 1–120)
     - Origin keep-alive timeout: `60` (range 1–120)
     - Custom headers: none
   - **Cache settings**: pick **Customize cache settings**, then set:
     - Viewer protocol policy: **Redirect HTTP to HTTPS**
     - Allowed HTTP methods: **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE**
     - Cache policy: **CachingDisabled** (managed) — the dynamic app should not cache; the `/static/*` behavior added in 9a handles assets
     - Origin request policy: **AllViewer** (managed)
   - **Next**.
4. **Enable security** page (WAF):
   - The three "Included security protections" (common-vulnerability rules, vulnerability-discovery blocking, IP threat-intel) are always on at the Free plan — no toggle.
   - **Use monitor mode**: ✅ check. Counts what would be blocked without actually blocking. Leave it on for a few days post-launch, scan the WAF logs for false positives on magic-link redemptions and SSE streams, then uncheck to start blocking.
   - **Rate limiting** (Recommended): ✅ enable. Cheap flood protection.
   - **SQL protections**: skip — Pro plan only, and Odin doesn't use SQL.
   - **Layer 7 DDoS**: skip — Business plan only.
5. **Get TLS certificate** page:
   - The wizard auto-discovers ACM certificates in us-east-1. Pick the cert created in step 3 (its **Covered domains** column should list `yourdomain.com` and `*.yourdomain.com`).
   - **Next**.
6. **Review and create** page:
   - Confirm the summary: distribution name set, **Domains to serve** = `yourdomain.com`, **Custom origin** = the EC2 public DNS, **Cache policy** = CachingDisabled, **Origin request policy** = AllViewer, **Security protections** = Enabled with monitor mode, **TLS certificate** ARN matches step 3.
   - **Create distribution**.

The Free-plan wizard doesn't expose price class, security policy (TLS minimum version), supported HTTP versions, or default root object. They're at managed defaults — fine for P0. If you ever need to tighten them, the distribution's **General → Edit** screen post-creation lets you override.

### 9a. Add the `/static/*` cache behavior

CloudFront only lets you create one behavior at a time, so the static-asset rule is added after the distribution exists.

1. Open the new distribution → **Behaviors** tab → **Create behavior**.
2. **Settings**:
   - Path pattern: `/static/*`
   - Origin and origin groups: the EC2 origin from step 9
   - Compress objects automatically: **Yes**
3. **Viewer**:
   - Viewer protocol policy: **Redirect HTTP to HTTPS**
   - Allowed HTTP methods: **GET, HEAD**
   - Restrict viewer access: **No**
4. **Cache key and origin requests**:
   - Cache policy: **CachingOptimized** (managed; recommended for this path pattern)
   - Origin request policy: leave blank
   - Response headers policy: leave blank
5. **Create behavior**.

Distributions take ~5–10 minutes to deploy. The status column shows **Deploying** → **Enabled**.

**Note this:** the distribution **Domain name** (e.g. `d1234abcd.cloudfront.net`) shown on the distribution detail page. Step 10 needs it.

---

## 10. Route 53 Alias Record

Region: not applicable.

1. **Route 53** console → **Hosted zones** → open `yourdomain.com` → **Create record**.
2. Record name: leave blank (apex). Record type: **A — Routes traffic to an IPv4 address and some AWS resources**.
3. Toggle **Alias** on.
4. Route traffic to: **Alias to CloudFront distribution**. A region selector appears — CloudFront has no region. Pick the distribution from the dropdown (its domain name will match the one you noted in 9).
5. Routing policy: **Simple routing**. Evaluate target health: **No**.
6. **Create records**.

DNS propagates in a minute or two. After CloudFront finishes deploying, `https://yourdomain.com` should reach the (not-yet-running) app.

---

## 11. GitHub Actions Secrets

1. In the GitHub repo, open **Settings → Secrets and variables → Actions** → **Secrets** tab.
2. Under **Repository secrets**, click **New repository secret** and add each of these in turn:

| Name | Value |
|---|---|
| `AWS_ACCOUNT_ID` | your 12-digit account ID (from step 1) |
| `EC2_INSTANCE_ID` | the instance ID from step 8b |

Neither value is strictly secret (account IDs and instance IDs aren't credentials), but the deploy workflow at `.github/workflows/deploy.yml` reads both via `${{ secrets.* }}`, so they go under Secrets rather than Variables.

The workflow assumes the `GitHubActionsOdinDeploy` role from step 5 via OIDC, so no AWS access keys are stored in GitHub.

---

## 12. Set Real Secret Values

Region: **us-west-2**.

1. **Secrets Manager** console → open `odin/app` → **Retrieve secret value** → **Edit** → **Plaintext** tab.
2. Replace the two remaining placeholders with the real values, then **Save**:

| Key | Value |
|---|---|
| `anthropic_api_key` | `sk-ant-your-real-key-here` |
| `secret_key` | a 64-character hex string for HMAC cookie/magic-link signing. Generate locally with `openssl rand -hex 32`. Min 32 chars. |
| `app_url` | the public origin used to build magic-link URLs, e.g. `https://yourdomain.com`. No trailing slash. |
| `searxng_secret` | a 64-character hex string. Generate one locally with `openssl rand -hex 32` and paste the output. |

The `smtp_*` keys were already populated in step 7d.

---

## 13. First Deploy

Open an SSM Session Manager shell to the instance and start the stack manually for the first time:

1. **EC2** console → **Instances** → select `odin` → **Connect** → **Session Manager** tab → **Connect**.

A browser-based shell opens as `ssm-user`. Everything below runs inside that shell — there is no UI alternative for `docker compose`.

`ssm-user` isn't in the docker group, so first switch to `ec2-user` (which is, courtesy of the user_data script in step 8b):

```bash
sudo -i -u ec2-user
cd /opt/odin

# Pull all credentials in one call and unpack into environment
_SECRETS=$(aws secretsmanager get-secret-value \
  --region us-west-2 --secret-id odin/app \
  --query SecretString --output text)
export ANTHROPIC_API_KEY=$(echo "$_SECRETS" | jq -r '.anthropic_api_key')
export SECRET_KEY=$(echo "$_SECRETS" | jq -r '.secret_key')
export APP_URL=$(echo "$_SECRETS" | jq -r '.app_url')
export SEARXNG_SECRET=$(echo "$_SECRETS" | jq -r '.searxng_secret')
export SMTP_HOST=$(echo "$_SECRETS" | jq -r '.smtp_host')
export SMTP_FROM=$(echo "$_SECRETS" | jq -r '.smtp_from')
export SMTP_USER=$(echo "$_SECRETS" | jq -r '.smtp_user')
export SMTP_PASS=$(echo "$_SECRETS" | jq -r '.smtp_pass')
unset _SECRETS

# Login to ECR and pull the prod image (substitute your 12-digit account ID from step 1)
ECR_URI="<account-id>.dkr.ecr.us-west-2.amazonaws.com/odin"
aws ecr get-login-password --region us-west-2 \
  | docker login --username AWS --password-stdin $ECR_URI

# On first deploy, build locally since there's no ECR image yet
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.awslogs.yml up -d
```

After the first GitHub Actions deploy runs successfully, subsequent deploys pull from ECR automatically.

---

## Verification

```bash
# App responds through CloudFront
curl https://yourdomain.com/health

# SSE streams incrementally (events should arrive one by one, not all at once)
curl -N https://yourdomain.com/profile/stream?q=test

# EC2 is NOT directly reachable (should time out)
curl --connect-timeout 5 http://<EC2_IP>:8000/health
```

---

## Cost ceilings

AWS Budgets reads billing data that AWS surfaces from `us-east-1` regardless of region, so the budget resource is created without a region setting (account-scoped). The CloudWatch billing alarm step below explicitly switches to `us-east-1` because billing metrics only publish there.

### Anthropic Console spend limit

The application spend ceiling lives in the Anthropic Console, not in Odin code.

1. Go to **console.anthropic.com**.
2. Click your workspace name in the top-left, then **Settings** → **Spend limit**.
3. Set a **monthly limit**. Recommended start: **$25/month**. Increase as traffic grows.
4. Save.

When the cap trips, the API returns `BadRequestError` with `error.type == "billing_error"`. Odin catches this (and `RateLimitError`) and emits a `service_unavailable` SSE event so the UI shows a friendly "Odin is temporarily paused" message. Adjusting the cap later is a Console-only change — no code or redeploy needed.

### AWS Budget

1. Open the **AWS Billing and Cost Management** console (search "Billing" in the top bar).
2. Left nav: **Budgets** → **Create budget**.
3. **Budget setup**: pick **Customize (advanced)**. Budget type: **Cost budget**.
4. **Set budget amount**:
   - Name: `odin-monthly`
   - Period: **Monthly**
   - Budget renewal: **Recurring**
   - Start month: current month
   - Budgeting method: **Fixed**
   - Enter your budgeted amount: **$50**
5. **Configure alerts**: click **Add an alert threshold** three times, then fill in:
   - Threshold 1: **50%** of budgeted amount, **Actual**, email recipient `odin@odinseye.info`
   - Threshold 2: **80%**, **Actual**, same email
   - Threshold 3: **100%**, **Actual**, same email
6. **Attach actions**: skip (none).
7. **Review** → **Create budget**.

### CloudWatch billing alarm (early warning)

The Budget above is the primary cap. Add a CloudWatch alarm for a faster ping:

1. **Region in the top-right must be `us-east-1`** — billing metrics only publish there.
2. Open **CloudWatch** → left nav **Alarms** → **All alarms** → **Create alarm**.
3. **Select metric** → **Billing** → **Total Estimated Charge** → check the row with `Currency = USD` → **Select metric**.
4. **Conditions**: Threshold type **Static**, **Greater than 25**.
5. **Notification**: create a new SNS topic `odin-alerts`, email endpoint `odin@odinseye.info`. Confirm the subscription email AWS sends you.
6. Name the alarm `odin-billing-25`. **Create alarm**.

---

## Backups

### Named volumes (already configured)

`docker-compose.yml` mounts `odin-valkey-data` and `searxng-valkey-data` as named volumes. They live on the EC2 root EBS volume and persist across container restarts. Nothing to do here.

### AWS Backup — daily EBS snapshots

1. Open **AWS Backup** console. Region: **us-west-2**.
2. Left nav: **Backup vaults** → **Create backup vault**.
   - Name: `odin-vault`
   - Encryption key: **(default) aws/backup**
   - **Create backup vault**.
3. Left nav: **Backup plans** → **Create backup plan** → **Build a new plan**.
   - Plan name: `odin-daily`
   - Rule name: `DailyEBS`
   - Backup vault: `odin-vault`
   - Backup frequency: **Daily**
   - Backup window: **Use backup window defaults** (or pick an off-hours window)
   - Lifecycle: **Delete after** → **7 days**
   - **Create plan**.
4. After creation, you'll be on the plan detail page. Click **Assign resources**.
   - Resource assignment name: `odin-ec2`
   - IAM role: **Default role** (AWS Backup creates one the first time)
   - Assign resources by: **Include specific resource types**
   - Resource type: **EC2**
   - Instance ID: pick the Odin EC2 instance
   - **Assign resources**.

The first snapshot runs at the next scheduled window. You can also click **Create on-demand backup** from the plan to run one immediately for verification.

### Restore drill (document, run once before launch)

1. **AWS Backup** console → **Backup vaults** → `odin-vault` → pick the most recent recovery point.
2. **Actions** → **Restore**.
3. Restore type: **Create new instance**. Pick the same instance type, VPC, subnet, and key pair as the live instance. Do NOT pick the same Elastic IP yet.
4. Wait for the restore to complete (Backup → **Jobs** shows progress; ~5–10 min for a small EBS volume).
5. **EC2** console → confirm the restored instance is running.
6. **Stop** (do not terminate) the original instance.
7. **EC2** → **Volumes** → detach the original instance's root volume, then attach the restored volume to the original instance as `/dev/xvda`. (Alternative simpler path: skip the volume swap and just keep the new instance.)
8. **Start** the restored or rebuilt instance.
9. SSM into it (`Session Manager` from the EC2 console row), then `cd /opt/odin && docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.awslogs.yml up -d`.
10. **Elastic IP** console → reassociate the EIP with the restored instance.
11. `curl https://yourdomain.com/health` → confirm 200.
12. Terminate the original instance.

Run this drill once against a throwaway sandbox EC2 before launch so you've actually clicked through the buttons before you need them.

---

## Monitoring

### CloudWatch Logs

`docker-compose.awslogs.yml` (a separate overlay applied on top of the prod compose file on EC2) configures the `awslogs` log driver for all four services. The driver is split into its own file because it requires EC2 IMDS to authenticate, which CI runners don't have. Log groups are created automatically on first start:

- `/odin/web`
- `/odin/searxng`
- `/odin/searxng-valkey`
- `/odin/odin-valkey`

Log groups appear automatically once containers start (the role permission for this was attached in step 4d). Set retention to bound cost:

1. **CloudWatch** → **Logs** → **Log groups**. Region: **us-west-2**.
2. For each of the four `/odin/*` log groups: click the group → **Actions** → **Edit retention setting** → **2 weeks** → **Save**.

### Uptime check

Pick one:

**Option A — UptimeRobot (free, 5-minute interval):**

1. Sign up at uptimerobot.com.
2. **+ New monitor** → Monitor type **HTTP(s)** → URL `https://yourdomain.com/health` → name `Odin /health`.
3. Monitoring interval: **5 minutes**.
4. Alert contacts: add your email.
5. **Create monitor**.

**Option B — Route 53 health check (~$0.50/month):**

1. **Route 53** console → left nav **Health checks** → **Create health check**.
2. Name: `odin-health`. What to monitor: **Endpoint**.
3. Specify endpoint by domain. Domain name: `yourdomain.com`. Path: `/health`. Port: `443`. Protocol: **HTTPS**.
4. Request interval: **Standard (30 seconds)**. Failure threshold: **3**.
5. **Next** → **Create alarm: Yes** → SNS topic `odin-alerts` (created earlier). Email: `odin@odinseye.info`.
6. **Create health check**.

### EC2 status-check alarm

Free, alerts when the underlying host or instance loses health:

1. **CloudWatch** → **Alarms** → **All alarms** → **Create alarm**. Region: **us-west-2**.
2. **Select metric** → **EC2** → **Per-Instance Metrics** → find your instance ID → check **StatusCheckFailed** → **Select metric**.
3. Statistic: **Maximum**. Period: **1 minute**.
4. Threshold type: **Static**. Greater than or equal to **1**.
5. Additional configuration → Datapoints to alarm: **2 out of 2**.
6. **Next** → **Notification** → existing SNS topic `odin-alerts` → **Next**.
7. Name: `odin-ec2-status-check`. **Create alarm**.

---

## Post-deploy verification

The GitHub Actions workflow runs `curl https://yourdomain.com/health` after the SSM deploy completes, retrying every 10 seconds for ~2 minutes. A failed check fails the workflow run, so a broken deploy is visible immediately rather than discovered by a user.

If the deploy URL ever needs to change (custom domain, staging), update the `HEALTH_URL` env var in `.github/workflows/deploy.yml` and the Route 53 health check above.

---

## Manual rollback

There is no automatic rollback in P0. To roll back via the GitHub UI:

1. **GitHub** → repo → **Actions** → **Deploy** workflow.
2. Click **Run workflow** (top-right of the runs list).
3. Branch: pick `main`. Then in the dropdown, select an older commit SHA (the previous green deploy).
4. Click **Run workflow**. The job rebuilds and redeploys; the post-deploy health check verifies success.

Alternatively, push a revert commit to `main`:

- Identify the bad commit in **GitHub** → **Commits**.
- Click the commit → **Revert** button (top-right) → opens a PR with the revert → merge it. The deploy workflow runs automatically.

**Emergency rollback (skip CI):**

1. **EC2** console → select the instance → **Connect** → **Session Manager** → **Connect**.
2. In the session:
   ```bash
   cd /opt/odin
   ECR_URI="<account>.dkr.ecr.us-west-2.amazonaws.com/odin"
   aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin $ECR_URI
   docker pull $ECR_URI:<previous-sha>
   docker tag $ECR_URI:<previous-sha> odin-prod
   docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.awslogs.yml up -d --no-deps web
   ```
3. `curl https://yourdomain.com/health` → confirm 200.

ECR retains all image tags by SHA, so any prior deploy is recoverable as long as ECR lifecycle hasn't expired it.

---

## SearXNG limiter

Pre-configured in `searxng/limiter.toml` and enabled via `searxng/settings.yml` (`server.limiter: true`). The Odin client at `src/odin/searxng.py` spoofs `X-Forwarded-For: 127.0.0.1` so internal calls from `web` to `searxng` bypass bot detection. External traffic — which should not exist (SearXNG is internal-only, port 8080 is not exposed past the docker network) — would be subject to the limiter as defense-in-depth.

No deploy-time action required.

---

## Cost Reference

| Item | Monthly |
|---|---|
| EC2 t4g.small (on-demand) | ~$12 |
| Elastic IP (attached) | $0 |
| CloudFront Free plan (1M req + 100 GB + WAF + Shield Standard) | $0 |
| ACM certificate | $0 |
| Route 53 hosted zone | $0.50 |
| ECR storage | ~$0.10 |
| Secrets Manager (1 secret) | ~$0.40 |
| Purelymail | billed separately |
| **Total** | **~$13/month** |

1-year Reserved Instance reduces EC2 to ~$6/month → **~$7/month total**.
If traffic outgrows the CloudFront Free plan (1M requests or 100 GB/mo), the next step up is the Pro plan at $15/month (10M requests + 50 TB).
