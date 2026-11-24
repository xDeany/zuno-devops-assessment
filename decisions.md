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
    * Do we want additional monitoring and alerting? Setup simple logging for now.
    * Maybe change which route to run the healthcheck on? I think this is just here to make sure self healing is a part of the solution.
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

* Ideally, containers would be in private subnet, but that requires paying for a NAT to route traffic back out to the internet (not free).
* Can run in public subnets, but increases need for SGs to be configured precisely. Also incurs a cost on assigning public IP addresses.

## Implementation

Going to write this in Pulumi directly, given the parallels to Terraform. 

Started by getting everything installed and configured for my AWS account, then found and used the `pulumi new container-aws-python` as a starting point. This gave me a simple ECR repo and Fargate service fronted by an ALB. However, it defines its own Dockerfile and also doesn't handle Cloudfront for securing the inbound connection behind HTTPS.

Considered defining VPC related resources (e.g. Subnets, route tables and internet gateway). Decided against it, the default is sufficient here.

Updated the template to use the test Dockerfile. Planned the Pulumi changes. Adjusted resource names. Added global tags.

Read into the AWSx provider, that wraps around the standard AWS provider. Looks like it handles what I need nicely.

Attempted initial deployment. Failed to connect to my Docker daemon for the image, but the rest of the stack created successfully.

Fixed docker installation with WSL.

Stack failed to deploy due to host & container port mapping mismatch. Fixed that, now the target group needs updating to route port 80 -> 8080.

This can't be done using the FargateService resource directly, going to need to define the LB/TG myself and pass that in.

That worked nicely, now to setup cloudfront for https. This requires full control over the ALB & TG, so moved that off of AWSx provider to the raw AWS one.

Done. Learned about a security pattern for cloudfront distributions along the way. https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html

Basically, traffic is currently permitted to the load balancer via ANY cloudfront distribution, so by adding this rotating header to our one, we can ensure traffic only gets to the ALB via the Cloudfron distro we want. Adding this in next, before wrapping up the test. This adds the need to set a secret in the pulumi config before applying. This could be set and pulled from secrets manager.

Removed leftover unusued resources from earlier in.

Before finishing, I'm considering changing the health check. The default requires 3 failures in a row to kill a task. That's a 0.1% chance each group of three health checks. Checking with AI, each task will currently survive, on average, 4.6 hours.

Also realised the secret I've created won't be able to be decrypted by the team wanting to run this deployment. Will generate this in code instead.

## Areas for future improvement

* Resiliency. Given it's a simple web server, we could spin up more containers to avoid downtime when one fails a health check. In addition, we would distribute these across AZ's, giving resiliency to an AZ failure. We could go further with regional scaling, but that would require more re-architecting via additional load balancers.
* Image building. Currently, it builds on every `pulumi up`, which is fine for a test, but if this were a real application, then we would want CI/CD to manage running application building & testing prior to deployment.
* Image scanning. Part of that CI pipeline should scan the docker image for vulnerabilities, but we could also enable ECR enhanced scanning if we wished.