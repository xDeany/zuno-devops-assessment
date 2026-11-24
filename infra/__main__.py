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

# An ECS cluster to deploy into
cluster = aws.ecs.Cluster("cluster")

# An ALB to serve the container endpoint to the internet
loadbalancer = awsx.lb.ApplicationLoadBalancer("loadbalancer")

# An ECR repository to store the application's container image
repo = awsx.ecr.Repository("zuno-web-server", force_delete=True, image_tag_mutability="IMMUTABLE")

# Build and publish the application's container image from ./app to the ECR repository
image = awsx.ecr.Image(
    "image", repository_url=repo.url, context="../", platform="linux/amd64"
)
 
# ALB listens on 80 and forwards to the tasks on the container port
loadbalancer = awsx.lb.ApplicationLoadBalancer(
    "loadbalancer2",
    subnet_ids=vpc.public_subnet_ids,
    security_groups=[alb_sg.id],
    listener={"port": 80, "protocol": "HTTP"},
    default_target_group={
        "vpc_id": vpc.vpc_id,
        "port": container_port,
        "protocol": "HTTP",
        "target_type": "ip",
        "health_check": {
            "path": "/",
            "port": "traffic-port",
            "matcher": "200",
            "interval": 15,
            "healthy_threshold": 2,
            "unhealthy_threshold": 3,
        },
    },
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
                    "target_group": loadbalancer.default_target_group,
                }
            ],
        },
    },
)

# The URL at which the container's HTTP endpoint will be available
export("url", Output.concat("http://", loadbalancer.load_balancer.dns_name))

# The name of the ECS cluster
export("clusterName", cluster.name)
