# Decisions

## Assessment Criteria

### Use Pulumi to provision the required AWS infrastructure.
* New to Pulumi, could write in Terraform first and convert it?
* Straight to Pulumi?

### The Pulumi language is your choice, although we prefer Python.
* Looks like Go and Python are both supported. Comfortable with either, going with employer's preference

### Build the container provided in the assessment repository and deploy it to AWS.
* This will need deploying to ECR. Infra for this to be created in Pulumi

### The application endpoints should be reachable from the public internet once deployed.
* Need inbound routes to the app, server is being hosted on port 8080
* Healthcheck on `/`, with 10% chance to fail. If we run in ECS, this could lead to regular container restarts of the container.
    * Do we want additional monitoring and alerting?
* "External check" on `/external-check` to see if outbound traffic is open. Will need to keep the outbound SG open for this, and route out through an internet gateway.

### Infrastructure and application configuration should follow appropriate security best practices.
* VPC & Subnets. Keep app in private, ELB in public.
    * Check free tier for ELB
* Will need an IAM for task execution
* App might need an IAM for logging

## Architecture

* My first instinct is to run this in ECS with Fargate backend. It would save running containerised instances.
* ECS with containerised instances is also easy enough to configure for this, but adds an extra layer to manage manually.
* EKS would likely be overkill for one web service.
* Could use Elasticbeanstalk, but that's never been fun to configure.
* Technically could run this on Lambda, but that's better suited for API type containers, not longer running web servers.
* ECS Express Service would be ideal here as well, although it solves too many things for me given this is a tech test.

**Decision: Fargate for compute.**

* Cloudfront > ALB > ECS traffic route. This gets us network security and encrypted traffic.
* Generally would like a custom domain, but that's not free.
* ECS Express would give this out of the box.
* API Gateway could work, but that's suited for API's not web services.

**Decision: Cloudfront & ALB for routing traffic.**

* Ideally, container instances would be in private subnet, but that requires paying for a NAT to route traffic back out to the internet (not free).
* Can run in public subnets, but increases need for SGs to be configured precisely