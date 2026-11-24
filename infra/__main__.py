from pulumi import Config, Output, export
import pulumi_aws as aws
import pulumi_awsx as awsx
 
config = Config()
container_port = config.get_int("containerPort", 80)
cpu = config.get_int("cpu", 512)
memory = config.get_int("memory", 128)

# Default VPC: public subnets in every AZ with an internet gateway already attached
vpc = awsx.ec2.DefaultVpc("default-vpc")
 
# --- Security groups -------------------------------------------------------
 
alb_sg = aws.ec2.SecurityGroup(
    "alb-sg",
    vpc_id=vpc.vpc_id,
    description="ALB: HTTP in, app port out to tasks",
)
 
task_sg = aws.ec2.SecurityGroup(
    "task-sg",
    vpc_id=vpc.vpc_id,
    description="Fargate tasks: app port from the ALB only",
)
 
# Public HTTP entry point
aws.vpc.SecurityGroupIngressRule(
    "alb-http-in",
    security_group_id=alb_sg.id,
    ip_protocol="tcp",
    from_port=80,
    to_port=80,
    cidr_ipv4="0.0.0.0/0",
)
 
aws.vpc.SecurityGroupEgressRule(
    "alb-to-tasks",
    security_group_id=alb_sg.id,
    ip_protocol="tcp",
    from_port=container_port,
    to_port=container_port,
    referenced_security_group_id=task_sg.id,
)
 
aws.vpc.SecurityGroupIngressRule(
    "tasks-from-alb",
    security_group_id=task_sg.id,
    ip_protocol="tcp",
    from_port=container_port,
    to_port=container_port,
    referenced_security_group_id=alb_sg.id,
)
 
# Outbound for ECR pulls, CloudWatch Logs and the /external-check call
aws.vpc.SecurityGroupEgressRule(
    "tasks-https-out",
    security_group_id=task_sg.id,
    ip_protocol="tcp",
    from_port=443,
    to_port=443,
    cidr_ipv4="0.0.0.0/0",
)

# --- Load balancer ---------------------------------------------------------
 
alb = aws.lb.LoadBalancer(
    "alb",
    load_balancer_type="application",
    subnets=vpc.public_subnet_ids,
    security_groups=[alb_sg.id],
    drop_invalid_header_fields=True,
)
 
target_group = aws.lb.TargetGroup(
    "app-tg",
    vpc_id=vpc.vpc_id,
    port=container_port,
    protocol="HTTP",
    target_type="ip",  # required for Fargate (awsvpc networking)
    deregistration_delay=30,
    health_check={
        "path": "/",
        "port": "traffic-port",
        "matcher": "200",
        "interval": 15,
        "healthy_threshold": 2,
        "unhealthy_threshold": 3,
    },
)
 
listener = aws.lb.Listener(
    "http",
    load_balancer_arn=alb.arn,
    port=80,
    protocol="HTTP",
    default_actions=[{"type": "forward", "target_group_arn": target_group.arn}],
)

# --- CloudFront ------------------------------------------------------------
 
caching_disabled = aws.cloudfront.get_cache_policy(name="Managed-CachingDisabled")
all_viewer_except_host = aws.cloudfront.get_origin_request_policy(
    name="Managed-AllViewerExceptHostHeader"
)
 
cdn = aws.cloudfront.Distribution(
    "cdn",
    enabled=True,
    comment="Zuno assessment web server",
    price_class="PriceClass_100",  # North America + Europe edges only
    http_version="http2and3",
    origins=[
        {
            "origin_id": "alb",
            "domain_name": alb.dns_name,
            "custom_origin_config": {
                "http_port": 80,
                "https_port": 443,
                "origin_protocol_policy": "http-only",  # ALB has no certificate
                "origin_ssl_protocols": ["TLSv1.2"],
            },
        }
    ],
    default_cache_behavior={
        "target_origin_id": "alb",
        "viewer_protocol_policy": "redirect-to-https",
        "allowed_methods": ["GET", "HEAD", "OPTIONS"],
        "cached_methods": ["GET", "HEAD"],
        "cache_policy_id": caching_disabled.id,
        "origin_request_policy_id": all_viewer_except_host.id,
        "compress": True,
    },
    # Don't cache errors: the app's random 500s should reach the viewer as they happen
    custom_error_responses=[
        {"error_code": code, "error_caching_min_ttl": 0}
        for code in (500, 502, 503, 504)
    ],
    restrictions={"geo_restriction": {"restriction_type": "none"}},
    viewer_certificate={"cloudfront_default_certificate": True},
)
 
# An ECS cluster to deploy into
cluster = aws.ecs.Cluster("cluster")
 
# An ECR repository to store the application's container image
repo = awsx.ecr.Repository("zuno-web-server", force_delete=True, image_tag_mutability="IMMUTABLE")
 
# Build and publish the application's container image from ./app to the ECR repository
image = awsx.ecr.Image(
    "image", repository_url=repo.url, context="../", platform="linux/amd64"
)

# Deploy an ECS Service on Fargate to host the application container
service = awsx.ecs.FargateService(
    "service",
    cluster=cluster.arn,
    network_configuration={
        "subnets": vpc.public_subnet_ids,
        "assign_public_ip": True,
        "security_groups": [task_sg.id],
    },
    task_definition_args={
        "container": {
            "name": "app",
            "image": image.image_uri,
            "cpu": cpu,
            "memory": memory,
            "essential": True,
            "port_mappings": [
                {
                    "container_port": container_port,
                    "host_port": container_port,
                    "protocol": "tcp",
                    "target_group": target_group,
                }
            ],
        },
    },
)
 
# Public HTTPS endpoint
export("url", Output.concat("https://", cdn.domain_name))
 
# The name of the ECS cluster
export("clusterName", cluster.name)
 