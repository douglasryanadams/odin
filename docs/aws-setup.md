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

- AWS account with admin access
- AWS CLI configured (`aws configure` or SSO)
- A domain you control (to point at Route 53)
- `ACCOUNT_ID` and `REGION` set in your shell:

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REGION=us-east-1   # must be us-east-1 for CloudFront ACM
```

---

## 1. ECR Repository

```bash
aws ecr create-repository \
  --repository-name odin \
  --region $REGION
```

Note the repository URI — you'll need it for the GitHub Actions secret and deploy commands.

```bash
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/odin"
```

---

## 2. Route 53 Hosted Zone

Create the zone first — ACM DNS validation needs it.

```bash
aws route53 create-hosted-zone \
  --name yourdomain.com \
  --caller-reference $(date +%s)
```

Copy the four NS records from the output and set them at your domain registrar. DNS propagation may take up to 48 hours.

---

## 3. ACM Certificate

Must be in `us-east-1` for CloudFront.

```bash
CERT_ARN=$(aws acm request-certificate \
  --region us-east-1 \
  --domain-name yourdomain.com \
  --subject-alternative-names "*.yourdomain.com" \
  --validation-method DNS \
  --query CertificateArn --output text)
```

Get the DNS validation record to add to Route 53:

```bash
aws acm describe-certificate \
  --region us-east-1 \
  --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord'
```

Add the CNAME record to Route 53, then wait for validation (can take ~5 minutes):

```bash
aws acm wait certificate-validated \
  --region us-east-1 \
  --certificate-arn $CERT_ARN
```

---

## 4. IAM — EC2 Instance Role

```bash
# Create role
aws iam create-role \
  --role-name odinInstanceRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# SSM access (replaces SSH)
aws iam attach-role-policy \
  --role-name odinInstanceRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

# ECR pull
aws iam put-role-policy \
  --role-name odinInstanceRole \
  --policy-name ecr-pull \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      "Resource": "*"
    }]
  }'

# Secrets Manager read
aws iam put-role-policy \
  --role-name odinInstanceRole \
  --policy-name secrets-read \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": \"secretsmanager:GetSecretValue\",
      \"Resource\": \"arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:odin/*\"
    }]
  }"

# Instance profile (required to attach role to EC2)
aws iam create-instance-profile --instance-profile-name odinInstanceProfile
aws iam add-role-to-instance-profile \
  --instance-profile-name odinInstanceProfile \
  --role-name odinInstanceRole
```

---

## 5. IAM — GitHub Actions OIDC Role

```bash
# Create OIDC provider (one per account, skip if already exists)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# Create role trusted by GitHub Actions for this repo only
aws iam create-role \
  --role-name GitHubActionsOdinDeploy \
  --assume-role-policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Principal\": {\"Federated\": \"arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com\"},
      \"Action\": \"sts:AssumeRoleWithWebIdentity\",
      \"Condition\": {
        \"StringEquals\": {\"token.actions.githubusercontent.com:aud\": \"sts.amazonaws.com\"},
        \"StringLike\": {\"token.actions.githubusercontent.com:sub\": \"repo:douglasryanadams/odin:*\"}
      }
    }]
  }"

# ECR push permissions
aws iam put-role-policy \
  --role-name GitHubActionsOdinDeploy \
  --policy-name ecr-push \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Effect\": \"Allow\",
        \"Action\": \"ecr:GetAuthorizationToken\",
        \"Resource\": \"*\"
      },
      {
        \"Effect\": \"Allow\",
        \"Action\": [\"ecr:BatchCheckLayerAvailability\", \"ecr:PutImage\",
                    \"ecr:InitiateLayerUpload\", \"ecr:UploadLayerPart\", \"ecr:CompleteLayerUpload\"],
        \"Resource\": \"arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/odin\"
      }
    ]
  }"

# SSM deploy permissions
aws iam put-role-policy \
  --role-name GitHubActionsOdinDeploy \
  --policy-name ssm-deploy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["ssm:SendCommand", "ssm:GetCommandInvocation"],
      "Resource": "*"
    }]
  }'
```

---

## 6. Secrets Manager

Create the secret resources now; set real values in step 12 (after EC2 is running).

```bash
aws secretsmanager create-secret \
  --region $REGION \
  --name odin/anthropic-api-key \
  --description "Anthropic API key for odin — set real value before first deploy"

aws secretsmanager create-secret \
  --region $REGION \
  --name odin/searxng-secret \
  --description "SearXNG secret_key — set real value before first deploy"

aws secretsmanager create-secret \
  --region $REGION \
  --name odin/smtp \
  --description "SES SMTP credentials for magic link delivery — set real values after step 7"
```

---

## 7. Amazon SES (email)

Magic links are sent over SMTP. SES is the simplest relay; the app only needs standard SMTP credentials.

### 7a. Verify your sender domain

In the SES console → **Verified identities → Create identity**, choose **Domain**, enter `yourdomain.com`, and add the DKIM CNAME records it shows you to Route 53. Verification usually completes within a few minutes.

Alternatively, verify a single address (**Email address** identity type) if you only need one sender and don't want to manage DKIM records.

### 7b. Request production access

New SES accounts start in sandbox mode — outbound email only reaches verified addresses. Submit a production-access request in the SES console (**Account dashboard → Request production access**) before go-live. Typical approval time is 24 hours.

### 7c. Generate SMTP credentials

In the SES console → **SMTP settings → Create SMTP credentials**. This creates a dedicated IAM user and immediately shows you the generated username and password — **copy both now**, they cannot be retrieved again.

Note the SMTP endpoint shown on the same page:

```
Host:  email-smtp.<region>.amazonaws.com
Port:  587  (STARTTLS)
```

### 7d. Store credentials in Secrets Manager

```bash
aws secretsmanager put-secret-value \
  --region $REGION \
  --secret-id odin/smtp \
  --secret-string "{
    \"host\": \"email-smtp.${REGION}.amazonaws.com\",
    \"from\": \"noreply@yourdomain.com\",
    \"user\": \"<smtp-username-from-console>\",
    \"pass\": \"<smtp-password-from-console>\"
  }"
```

---

## 8. EC2 Instance

```bash
# Get the CloudFront origin-facing prefix list for your region
CF_PREFIX_LIST=$(aws ec2 describe-managed-prefix-lists \
  --region $REGION \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)

# Security group: port 8000 from CloudFront only
SG_ID=$(aws ec2 create-security-group \
  --region $REGION \
  --group-name odin-sg \
  --description "Odin — CloudFront to app" \
  --query GroupId --output text)

aws ec2 authorize-security-group-ingress \
  --region $REGION \
  --group-id $SG_ID \
  --ip-permissions "[{
    \"IpProtocol\": \"tcp\",
    \"FromPort\": 8000,
    \"ToPort\": 8000,
    \"PrefixListIds\": [{\"PrefixListId\": \"${CF_PREFIX_LIST}\"}]
  }]"

# Get latest Amazon Linux 2023 ARM64 AMI
AMI_ID=$(aws ec2 describe-images \
  --region $REGION \
  --owners amazon \
  --filters \
    Name=name,Values="al2023-ami-*-arm64" \
    Name=state,Values=available \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text)

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
  --region $REGION \
  --image-id $AMI_ID \
  --instance-type t4g.small \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=odinInstanceProfile \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=odin}]' \
  --user-data '#!/bin/bash
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
git clone https://github.com/douglasryanadams/odin.git /opt/odin
' \
  --query 'Instances[0].InstanceId' --output text)

echo "Instance ID: $INSTANCE_ID"

# Elastic IP
ALLOC_ID=$(aws ec2 allocate-address --region $REGION --query AllocationId --output text)
aws ec2 associate-address \
  --region $REGION \
  --instance-id $INSTANCE_ID \
  --allocation-id $ALLOC_ID

EC2_IP=$(aws ec2 describe-addresses \
  --region $REGION \
  --allocation-ids $ALLOC_ID \
  --query 'Addresses[0].PublicIp' --output text)

echo "Elastic IP: $EC2_IP"
```

Verify SSM is reachable (may take ~2 minutes for the agent to start):

```bash
aws ssm start-session --region $REGION --target $INSTANCE_ID
```

---

## 9. CloudFront Distribution

```bash
aws cloudfront create-distribution --distribution-config "{
  \"CallerReference\": \"odin-$(date +%s)\",
  \"Origins\": {
    \"Quantity\": 1,
    \"Items\": [{
      \"Id\": \"ec2\",
      \"DomainName\": \"${EC2_IP}\",
      \"CustomOriginConfig\": {
        \"HTTPPort\": 8000,
        \"HTTPSPort\": 443,
        \"OriginProtocolPolicy\": \"http-only\",
        \"OriginReadTimeout\": 180,
        \"OriginKeepaliveTimeout\": 60
      }
    }]
  },
  \"DefaultCacheBehavior\": {
    \"TargetOriginId\": \"ec2\",
    \"ViewerProtocolPolicy\": \"redirect-to-https\",
    \"AllowedMethods\": {
      \"Quantity\": 7,
      \"Items\": [\"GET\",\"HEAD\",\"OPTIONS\",\"PUT\",\"POST\",\"PATCH\",\"DELETE\"],
      \"CachedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}
    },
    \"CachePolicyId\": \"4135ea2d-6df8-44a3-9df3-4b5a84be39ad\",
    \"OriginRequestPolicyId\": \"216adef6-5c7f-47e4-b989-5492eafa07d3\",
    \"Compress\": true,
    \"ForwardedValues\": {\"QueryString\": false, \"Cookies\": {\"Forward\": \"none\"}}
  },
  \"CacheBehaviors\": {
    \"Quantity\": 1,
    \"Items\": [{
      \"PathPattern\": \"/static/*\",
      \"TargetOriginId\": \"ec2\",
      \"ViewerProtocolPolicy\": \"redirect-to-https\",
      \"AllowedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"],
        \"CachedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}},
      \"CachePolicyId\": \"658327ea-f89d-4fab-a63d-7e88639e58f6\",
      \"Compress\": true,
      \"ForwardedValues\": {\"QueryString\": false, \"Cookies\": {\"Forward\": \"none\"}}
    }]
  },
  \"Aliases\": {\"Quantity\": 1, \"Items\": [\"yourdomain.com\"]},
  \"ViewerCertificate\": {
    \"ACMCertificateArn\": \"${CERT_ARN}\",
    \"SSLSupportMethod\": \"sni-only\",
    \"MinimumProtocolVersion\": \"TLSv1.2_2021\"
  },
  \"Enabled\": true,
  \"HttpVersion\": \"http2and3\",
  \"PriceClass\": \"PriceClass_100\",
  \"Comment\": \"odin\",
  \"Restrictions\": {\"GeoRestriction\": {\"RestrictionType\": \"none\", \"Quantity\": 0}}
}"
```

Note the `DomainName` from the output (e.g. `xxxx.cloudfront.net`).

---

## 10. Route 53 Alias Record

Get your hosted zone ID:

```bash
ZONE_ID=$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='yourdomain.com.'].Id" \
  --output text | sed 's|/hostedzone/||')

CF_DOMAIN="xxxx.cloudfront.net"   # from step 8 output
```

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id $ZONE_ID \
  --change-batch "{
    \"Changes\": [{
      \"Action\": \"CREATE\",
      \"ResourceRecordSet\": {
        \"Name\": \"yourdomain.com\",
        \"Type\": \"A\",
        \"AliasTarget\": {
          \"HostedZoneId\": \"Z2FDTNDATAQYW2\",
          \"DNSName\": \"${CF_DOMAIN}\",
          \"EvaluateTargetHealth\": false
        }
      }
    }]
  }"
```

Note: `Z2FDTNDATAQYW2` is CloudFront's fixed hosted zone ID — it's the same for all distributions.

---

## 11. GitHub Actions Secrets

In the GitHub repo settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `AWS_ACCOUNT_ID` | your 12-digit account ID |
| `EC2_INSTANCE_ID` | the instance ID from step 7 |

---

## 12. Set Real Secret Values

```bash
aws secretsmanager put-secret-value \
  --region $REGION \
  --secret-id odin/anthropic-api-key \
  --secret-string "sk-ant-your-real-key-here"

aws secretsmanager put-secret-value \
  --region $REGION \
  --secret-id odin/searxng-secret \
  --secret-string "$(openssl rand -hex 32)"
```

The `odin/smtp` secret was already populated in step 7d.

---

## 13. First Deploy

SSH into the EC2 instance via SSM and start the stack manually for the first time:

```bash
aws ssm start-session --region $REGION --target $INSTANCE_ID
```

Inside the session:

```bash
cd /opt/odin

# Pull secrets into environment
export ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value \
  --region us-east-1 --secret-id odin/anthropic-api-key \
  --query SecretString --output text)
export SEARXNG_SECRET=$(aws secretsmanager get-secret-value \
  --region us-east-1 --secret-id odin/searxng-secret \
  --query SecretString --output text)

# Pull and unpack SMTP credentials
_SMTP=$(aws secretsmanager get-secret-value \
  --region us-east-1 --secret-id odin/smtp \
  --query SecretString --output text)
export SMTP_HOST=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['host'])")
export SMTP_FROM=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['from'])")
export SMTP_USER=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['user'])")
export SMTP_PASS=$(echo "$_SMTP" | python3 -c "import sys,json; print(json.load(sys.stdin)['pass'])")
unset _SMTP

# Login to ECR and pull the prod image
ECR_URI="ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/odin"
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin $ECR_URI

# On first deploy, build locally since there's no ECR image yet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
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

## Region note

The new P0 sections below assume the workload runs in **us-west-2** (Oregon). The ACM certificate step earlier in this doc still uses `us-east-1` because CloudFront requires its cert there — that's the only resource pinned to us-east-1. AWS Budgets reads billing data that AWS surfaces from `us-east-1` regardless of region, so the budget resource is created without a region setting (account-scoped).

When the AWS Console asks for a region, pick **US West (Oregon) us-west-2** unless the section explicitly says otherwise.

---

## Cost ceilings

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
9. SSM into it (`Session Manager` from the EC2 console row), then `cd /opt/odin && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
10. **Elastic IP** console → reassociate the EIP with the restored instance.
11. `curl https://yourdomain.com/health` → confirm 200.
12. Terminate the original instance.

Run this drill once against a throwaway sandbox EC2 before launch so you've actually clicked through the buttons before you need them.

---

## Monitoring

### CloudWatch Logs

`docker-compose.prod.yml` already has the `awslogs` log driver wired for all four services. Log groups are created automatically on first start:

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
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps web
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
