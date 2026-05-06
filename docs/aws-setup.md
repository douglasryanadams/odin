# AWS Setup Guide

Manual steps to provision the production environment. Update this file as you go — commands are a starting point, not guaranteed to be verbatim correct for your account.

## Architecture

```
Browser → CloudFront (HTTPS, ACM cert) → EC2 t4g.small (HTTP:8000)
               └─ /static/* cached           └─ docker-compose
               └─ /* pass-through                 ├─ web:8000
                  (180s SSE timeout)              ├─ searxng:8080
                                                  └─ searxng-valkey
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

Create the secret resources now; set real values in step 11 (after EC2 is running).

```bash
aws secretsmanager create-secret \
  --region $REGION \
  --name odin/anthropic-api-key \
  --description "Anthropic API key for odin — set real value before first deploy"

aws secretsmanager create-secret \
  --region $REGION \
  --name odin/searxng-secret \
  --description "SearXNG secret_key — set real value before first deploy"
```

---

## 7. EC2 Instance

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

## 8. CloudFront Distribution

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

## 9. Route 53 Alias Record

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

## 10. GitHub Actions Secrets

In the GitHub repo settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `AWS_ACCOUNT_ID` | your 12-digit account ID |
| `EC2_INSTANCE_ID` | the instance ID from step 7 |

---

## 11. Set Real Secret Values

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

---

## 12. First Deploy

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

## Cost Reference

| Item | Monthly |
|---|---|
| EC2 t4g.small (on-demand) | ~$12 |
| Elastic IP (attached) | $0 |
| CloudFront + Shield Standard | $0 (free tier) |
| ACM certificate | $0 |
| Route 53 hosted zone | $0.50 |
| ECR storage | ~$0.10 |
| Secrets Manager (2 secrets) | ~$0.80 |
| **Total** | **~$13/month** |

1-year Reserved Instance reduces EC2 to ~$6/month → **~$7/month total**.
Optional AWS WAF: +~$5–8/month when needed.
