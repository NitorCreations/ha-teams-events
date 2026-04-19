#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from stacks.relay_stack import RelayStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-1"),
)

RelayStack(
    app,
    "TeamsEventsRelay",
    env=env,
    description="Teams events relay: Graph webhook -> WebSocket forwarding",
)

app.synth()
