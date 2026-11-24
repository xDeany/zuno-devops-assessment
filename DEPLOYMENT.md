# Deploying

The infrastructure is defined with [Pulumi](https://www.pulumi.com/) (Python) in `infra/`. A single `pulumi up` builds the container image, pushes it to ECR and deploys the full stack.

## Decisions

A breakdown of my thought process, decisions made and areas for future improvement can be found in [decisions.md](./decisions.md)

## What gets created

- **CloudFront distribution**: the public HTTPS endpoint (default `*.cloudfront.net` certificate, caching disabled)
- **Application Load Balancer**: in the default VPC's public subnets, reachable only from CloudFront (managed prefix list plus a secret origin header)
- **ECS Fargate service**: runs the Go web server on port 8080, in public subnets with a public IP for outbound access (no NAT gateway)
- **ECR repository**: holds the container image

## Prerequisites

- An AWS account and credentials with permission to create the resources above
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), configured (`aws sts get-caller-identity` should succeed)
- [Pulumi CLI](https://www.pulumi.com/docs/install/)
- Python 3.9 or later
- Docker, running (the image is built locally during deployment)

## Deploy

```bash
cd infra

# 1. Choose where Pulumi keeps state: Pulumi Cloud (free for individuals)...
pulumi login
#    ...or an S3 bucket you own:  pulumi login s3://<your-state-bucket>

# 2. Create your own stack (use any name except the one already committed)
pulumi stack init <your-stack-name>

# 3. Set the AWS region
pulumi config set aws:region eu-west-2

# 4. Install Python dependencies into the project's virtualenv
pulumi install

# 5. Preview, then deploy
pulumi preview
pulumi up
```

The first deployment takes about 10 minutes, most of it waiting for CloudFront to roll out to its edge locations.

No secrets need to be configured. The CloudFront-to-ALB origin secret is generated per stack and stored encrypted in Pulumi state.

## Test

```bash
# Public endpoint: mostly "Uptime: N", with an occasional deliberate 500
curl -i "$(pulumi stack output url)"

# External dependency check
curl -i "$(pulumi stack output url)/external-check"
```

Requests sent directly to the load balancer, bypassing CloudFront, are blocked.

## Tear down

Remove everything when finished:

```bash
pulumi destroy
pulumi stack rm <your-stack-name>
```

## Troubleshooting

- **Docker errors during `pulumi up`**: make sure Docker is running and that `docker ps` works without `sudo`.
- **Slow image build on Apple Silicon or other ARM machines**: the image targets `linux/amd64`, so Docker builds it under emulation. This is slower but works.
- **403 from the public URL straight after deploying**: CloudFront is still propagating. Wait a few minutes and retry.
