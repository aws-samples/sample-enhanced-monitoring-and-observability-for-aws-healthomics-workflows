# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import os
import aws_cdk as cdk
from cdk.cdk_stack import omics_workflow_Stack
from aws_cdk import Aspects
import cdk_nag

app = cdk.App()
omics_workflow_Stack(app, "HealthOmicsMonitoringCdkStack",
    env=cdk.Environment(
        account=os.environ.get('CDK_DEFAULT_ACCOUNT'),
        region=os.environ.get('CDK_DEFAULT_REGION')
    )
)
Aspects.of(app).add(cdk_nag.AwsSolutionsChecks(verbose=True))
app.synth()
