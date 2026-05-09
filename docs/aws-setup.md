# AWS Setup Guide

Manual steps to provision the production environment. Update this file as you go — commands are a starting point, not guaranteed to be verbatim correct for your account.

## Architecture

```
Browser → CloudFront (HTTPS, ACM cert) → EC2 t4g.small (HTTP:8000)
               └─ /static/* cached           └─ docker-compose
               └─ /* pass-through                 ├─ web:8000
                  (180s SSE timeout)              ├─ searxng:8080
                                                  ├─ searxng-valkey
                                                  └─ odin-valkey

Magic link emails → Amazon SES (SMTP relay, port 587)
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

### 4d. Instance profile

When you create a role with the **EC2** trusted-entity use case, IAM auto-creates a matching instance profile of the same name (`odinInstanceRole`). You can confirm by running through the EC2 launch wizard in step 8 — `odinInstanceRole` will appear in the IAM instance profile dropdown. No extra clicks needed here.

---

## 5. IAM — GitHub Actions OIDC Role

Region: not applicable.

### 5a. Create the OIDC provider (skip if it already exists)

1. **IAM** console → **Identity providers** → **Add provider**.
2. Provider type: **OpenID Connect**.
3. Provider URL: `https://token.actions.githubusercontent.com`. Click **Get thumbprint**.
4. Audience: `sts.amazonaws.com`.
5. **Add provider**.

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
      "Action": ["ecr:BatchCheckLayerAvailability", "ecr:PutImage",
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

Create three empty secret resources now; set real values in step 12 (after EC2 is running). Empty placeholders are fine — Secrets Manager lets you skip the value at create time.

For each of the three names below:

1. Open the **Secrets Manager** console → **Store a new secret**.
2. Secret type: **Other type of secret**.
3. Key/value pairs: leave blank and switch to **Plaintext** tab. Enter `placeholder` (you'll overwrite this in step 12).
4. Encryption key: **aws/secretsmanager** (default).
5. **Next**.
6. Secret name and description (one per loop):

| Secret name | Description |
|---|---|
| `odin/anthropic-api-key` | Anthropic API key for odin — set real value before first deploy |
| `odin/searxng-secret` | SearXNG secret_key — set real value before first deploy |
| `odin/smtp` | SES SMTP credentials for magic link delivery — set real values after step 7 |

7. **Next** through automatic rotation (skip — leave **Disable automatic rotation**).
8. **Next** → **Store**.

---

## 7. Amazon SES (email)

Region: **us-west-2**. Magic links are sent over SMTP. SES is the simplest relay; the app only needs standard SMTP credentials.

### 7a. Verify your sender domain

In the SES console → **Verified identities** → **Create identity**, choose **Domain**, enter `yourdomain.com`. Leave **Use a custom MAIL FROM domain** unchecked unless you have a reason. Under **DKIM**, accept the default Easy DKIM with RSA 2048-bit. **Create identity**.

On the identity detail page, expand **DKIM**. Click **Publish DNS records** to **Amazon Route 53** → **Publish records**. SES writes the CNAMEs into your hosted zone. Verification usually completes within a few minutes; the status on the identity page flips to **Verified**.

Alternatively, verify a single address (**Email address** identity type) if you only need one sender and don't want to manage DKIM records.

### 7b. Request production access

New SES accounts start in sandbox mode — outbound email only reaches verified addresses. In the SES console: **Account dashboard** → **Request production access**. Fill in the form (use case: transactional, mail type: transactional, website URL: your domain) and submit. Typical approval time is 24 hours.

### 7c. Generate SMTP credentials

In the SES console → **SMTP settings** → **Create SMTP credentials**. This opens an IAM user-creation flow with sensible defaults; accept the suggested IAM user name and **Create user**. The next page shows the generated SMTP **username** and **password** — **download the .csv or copy both now**, they cannot be retrieved again.

Note the SMTP endpoint shown on the SMTP settings page:

```
Host:  email-smtp.us-west-2.amazonaws.com
Port:  587  (STARTTLS)
```

### 7d. Store credentials in Secrets Manager

1. **Secrets Manager** console → open `odin/smtp` → **Retrieve secret value** → **Edit**.
2. Switch to the **Plaintext** tab and paste:
   ```json
   {
     "host": "email-smtp.us-west-2.amazonaws.com",
     "from": "noreply@yourdomain.com",
     "user": "<smtp-username-from-7c>",
     "pass": "<smtp-password-from-7c>"
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
   - In the source field, start typing `pl-` and pick the prefix list named `com.amazonaws.global.cloudfront.origin-facing` from the dropdown. (This is AWS's managed list of CloudFront edge IPs — it locks port 8000 to CloudFront only.)
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
     dnf install -y docker git
     systemctl enable --now docker
     usermod -aG docker ec2-user
     mkdir -p /usr/local/lib/docker/cli-plugins
     curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64 \
       -o /usr/local/lib/docker/cli-plugins/docker-compose
     chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
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
2. **Origin**:
   - Origin domain: paste the **EIP** from step 8c.
   - Protocol: **HTTP only**.
   - HTTP port: `8000`.
   - Name: `ec2` (or accept the auto-generated name).
   - Expand **Add custom header** — none needed.
   - Expand **Connection attempts/timeout** under additional settings:
     - **Origin response timeout (read timeout)**: `180`
     - **Origin keep-alive timeout**: `60`
3. **Default cache behavior**:
   - Viewer protocol policy: **Redirect HTTP to HTTPS**.
   - Allowed HTTP methods: **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE**.
   - Cache key and origin requests: **Cache policy and origin request policy**.
     - Cache policy: **CachingDisabled** (managed). The dynamic app should not cache by default; the static behavior below handles assets.
     - Origin request policy: **AllViewer** (managed).
   - Compress objects automatically: **Yes**.
4. **Web Application Firewall (WAF)**: **Do not enable security protections** for P0 (you can flip this later).
5. **Settings**:
   - Price class: **Use only North America and Europe** (`PriceClass_100`).
   - Alternate domain name (CNAME): `yourdomain.com`.
   - Custom SSL certificate: pick the certificate from step 3 (it's the only one in us-east-1 that matches).
   - Security policy: **TLSv1.2_2021**.
   - Supported HTTP versions: **HTTP/2** and **HTTP/3** both checked.
   - Default root object: leave blank.
6. **Create distribution**.

### 9a. Add the `/static/*` cache behavior

CloudFront only lets you create one behavior at a time, so the static-asset rule is added after the distribution exists.

1. Open the new distribution → **Behaviors** tab → **Create behavior**.
2. Path pattern: `/static/*`. Origin: the `ec2` origin.
3. Viewer protocol policy: **Redirect HTTP to HTTPS**.
4. Allowed HTTP methods: **GET, HEAD**.
5. Cache key and origin requests: **Cache policy and origin request policy**.
   - Cache policy: **CachingOptimized** (managed).
6. Compress objects automatically: **Yes**.
7. **Create behavior**.

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

In the GitHub repo settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `AWS_ACCOUNT_ID` | your 12-digit account ID (from step 1) |
| `EC2_INSTANCE_ID` | the instance ID from step 8b |

The deploy workflow assumes the `GitHubActionsOdinDeploy` role from step 5 via OIDC, so no AWS access keys are stored in GitHub.

---

## 12. Set Real Secret Values

Region: **us-west-2**. Repeat the edit flow from 7d for each secret:

1. **Secrets Manager** console → open the secret → **Retrieve secret value** → **Edit** → **Plaintext** tab.
2. Replace the placeholder with the real value, then **Save**.

| Secret | Plaintext value |
|---|---|
| `odin/anthropic-api-key` | `sk-ant-your-real-key-here` |
| `odin/searxng-secret` | a 64-character hex string. Generate one locally with `openssl rand -hex 32` and paste the output. |

The `odin/smtp` secret was already populated in step 7d.

---

## 13. First Deploy

Open an SSM Session Manager shell to the instance and start the stack manually for the first time:

1. **EC2** console → **Instances** → select `odin` → **Connect** → **Session Manager** tab → **Connect**.

A browser-based shell opens. Everything below runs inside that shell — there is no UI alternative for `docker compose`.

```bash
cd /opt/odin

# Pull secrets into environment
export ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value \
  --region us-west-2 --secret-id odin/anthropic-api-key \
  --query SecretString --output text)
export SEARXNG_SECRET=$(aws secretsmanager get-secret-value \
  --region us-west-2 --secret-id odin/searxng-secret \
  --query SecretString --output text)

# Pull and unpack SMTP credentials
_SMTP=$(aws secretsmanager get-secret-value \
  --region us-west-2 --secret-id odin/smtp \
  --query SecretString --output text)
export SMTP_HOST=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['host'])")
export SMTP_FROM=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['from'])")
export SMTP_USER=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['user'])")
export SMTP_PASS=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['pass'])")
unset _SMTP

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
   - Threshold 1: **50%** of budgeted amount, **Actual**, email recipient `douglasryanadams@gmail.com`
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
5. **Notification**: create a new SNS topic `odin-alerts`, email endpoint `douglasryanadams@gmail.com`. Confirm the subscription email AWS sends you.
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

The EC2 instance role needs CloudWatch Logs permissions. If you used the Step 4 IAM policy from earlier in this doc, you have the SSM core permissions but not log permissions yet — add the AWS-managed policy:

1. **IAM** console → **Roles** → `odinInstanceRole` → **Add permissions** → **Attach policies**.
2. Search for `CloudWatchAgentServerPolicy` → check it → **Add permissions**.

After the next container restart, log groups appear automatically. Set retention to bound cost:

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
5. **Next** → **Create alarm: Yes** → SNS topic `odin-alerts` (created earlier). Email: `douglasryanadams@gmail.com`.
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
| CloudFront + Shield Standard | $0 (free tier) |
| ACM certificate | $0 |
| Route 53 hosted zone | $0.50 |
| ECR storage | ~$0.10 |
| Secrets Manager (3 secrets) | ~$1.20 |
| SES (first 62k emails/month) | $0 (free tier) |
| **Total** | **~$14/month** |

1-year Reserved Instance reduces EC2 to ~$6/month → **~$8/month total**.
Optional AWS WAF: +~$5–8/month when needed.
