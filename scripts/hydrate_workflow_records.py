# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import boto3
import argparse
import json
import os
import time
from botocore.config import Config
from uuid import uuid4


def parse_args():
    parser = argparse.ArgumentParser(description='Hydrate HealthOmics workflow records in')

    parser.add_argument('--dry-run', action='store_true',
                       help='Print what would be done without actually invoking Lambda')
    parser.add_argument('--sleep-between-api-calls', type=int, default=0.2,
                        help='Duration in seconds between each run being submitted to prevent API throttling')
    parser.add_argument('--lambda-timeout', type=int, default=300,
                        help='Timeout in seconds for Lambda invocation (default: 300, max: 900)')
    parser.add_argument('--lambda-function-name', type=str, default='healthomics_workflow_records_lambda',
                        help='Name of lambda function to invoke')
    
    return parser.parse_args()

def list_workflow_versions(omics_client, workflow_id, workflow_type):
    """List HealthOmics workflow versions"""
    print(f"\nFetching all versions for workflow {workflow_id}...")
    workflow_versions = []

    try:
        paginator = omics_client.get_paginator('list_workflow_versions')
        operation_parameters = {'workflowId': workflow_id, 'type': workflow_type}
        for page in paginator.paginate(**operation_parameters):
            for workflow in page['items']:
                workflow_versions.append(workflow)
    except Exception as e:
        print(f"Error listing workflow versions for workflow {workflow_id}: {str(e)}")
        raise

    return workflow_versions

def list_workflows(omics_client, type='PRIVATE'):
    """List HealthOmics workflows"""
    print(f"\nFetching all {type} workflows...")
    workflows = []
    
    try:
        paginator = omics_client.get_paginator('list_workflows')
        operation_parameters = {'type': 'PRIVATE'}
        for page in paginator.paginate(**operation_parameters):
            for run in page['items']:
                workflows.append(run)
    except Exception as e:
        print(f"Error listing {type} workflows : {str(e)}")
        raise
        
    return workflows

def get_workflow_details(omics_client, workflow_id, workflow_type):
    """Get workflow details from the GetWorkflow API"""
    try:
        response = omics_client.get_workflow(
            id=workflow_id,
            type=workflow_type
        )
        return response
    except Exception as e:
        raise(f"Error getting workflow name for workflow {workflow_id}: {str(e)}")

def get_workflow_version_details(omics_client, workflow_id, workflow_version_name):
    """Get workflow details from the GetWorkflow API"""
    try:
        response = omics_client.get_workflow_version(
            workflowId=workflow_id,
            versionName=workflow_version_name
        )
        return response
    except Exception as e:
        raise(f"Error getting workflow version details for workflow {workflow_id} and version {workflow_version_name}: {str(e)}")

def invoke_lambda_and_wait(lambda_client, function_name, payload):
    """Invoke Lambda and wait for completion"""
    print(f"\nInvoking Lambda function: {function_name}")
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',  # Synchronous invocation
            Payload=json.dumps(payload, default=str)
        )
        
        status_code = response['StatusCode']
        print(f"Lambda invocation status code: {status_code}")
        
        if status_code != 200:
            print(f"Lambda invocation failed with status: {status_code}")
            return False
            
        if 'FunctionError' in response:
            print(f"Lambda execution error: {response['FunctionError']}")
            payload = json.loads(response['Payload'].read())
            print(f"Error details: {payload}")
            return False
            
        # Parse the Lambda response
        response_payload = json.loads(response['Payload'].read())
        print(f"Lambda execution completed: {response_payload}")
        return True
    except Exception as e:
        print(f"Error invoking Lambda function: {str(e)}")
        return False

def main():
    session = boto3.session.Session()

    args = parse_args()


    # Initialize AWS clients
    omics_client = boto3.client('omics')
    
    # Configure Lambda client with custom timeout
    lambda_timeout = min(900, max(60, args.lambda_timeout))  # Ensure timeout is between 60 and 900 seconds
    print(f"Setting Lambda client timeout to {lambda_timeout} seconds")
    lambda_config = Config(
        connect_timeout=lambda_timeout,
        read_timeout=lambda_timeout,
        retries={'max_attempts': 0}  # Disable auto-retries to avoid duplicate processing
    )
    lambda_client = boto3.client('lambda', config=lambda_config)

    payloads_to_invoke = []

    # Get ready2run workflows listed
    ready2run_workflows = list_workflows(omics_client, 'READY2RUN')
    print(f"Found {len(ready2run_workflows)} READY2RUN workflows to process")
    # use run list if provided, else pull from listruns
    private_workflows = list_workflows(omics_client, 'PRIVATE')
    print(f"Found {len(private_workflows)} PRIVATE workflows to process")

    all_workflows = ready2run_workflows + private_workflows
    
    caller_account = boto3.client('sts').get_caller_identity()['Account']
    caller_aws_region = os.environ.get('AWS_DEFAULT_REGION')

    # Process each workflow
    success_count = 0
    for workflow in all_workflows:

        print(f"\nProcessing workflow: {workflow['id']}")
        print(f"Fetch workflow details for workflow:{workflow['id']}")
        workflow_details = get_workflow_details(omics_client, workflow['id'], workflow['type'])
        
        # Ensure payload mimics service's event schema
        # https://docs.aws.amazon.com/omics/latest/dev/eventbridge.html
        payload = {
            "version": "0",
            "id": f"reprocess-eventid-{uuid4()}",
            "detail-type": "Workflow Status Change",
            "source": "hydrate_workflow_records.py",
            "account": caller_account,
            "time": workflow['creationTime'],
            "region": caller_aws_region,
            "resources": [
                workflow['arn']
            ],
            "detail": {
                "omicsVersion": "1.0.0",
                "arn": workflow['arn'],
                "status": workflow_details['status'],
                "workflowUuid": workflow_details['uuid']
            }
        }
        payloads_to_invoke.append(payload)
        success_count += 1
        time.sleep(args.sleep_between_api_calls)

        # Check if multiple versions available for this parent workflow
        workflow_versions = list_workflow_versions(omics_client, workflow['id'], workflow['type'])
        if len(workflow_versions) > 0:
            print(f"Found {len(workflow_versions)} versions for workflow {workflow['id']}")
            for version in workflow_versions:
                print(f"\nProcessing version: {version['arn']}")
                # Ensure payload mimics service's event schema
                payload = {
                    "version": "0",
                    "id": f"reprocess-eventid-{uuid4()}",
                    "detail-type": "Workflow Status Change",
                    "source": "hydrate_workflow_records.py",
                    "account": caller_account,
                    "time": version['creationTime'],
                    "region": caller_aws_region,
                    "resources": [
                        version['arn']
                    ],
                    "detail": {
                        "omicsVersion": "1.0.0",
                        "arn": workflow['arn'],
                        "status": version['status'],
                        "workflowVersionName": version['versionName'],
                        "workflowUuid": 
                            get_workflow_version_details(
                                omics_client=omics_client,
                                workflow_id=workflow['id'], 
                                workflow_version_name=version['versionName'])['uuid']
                    }
                }
                payloads_to_invoke.append(payload)   
                success_count += 1
                time.sleep(args.sleep_between_api_calls)
        else:
            print(f"No versions found for workflow {workflow['id']}")
        print(f"Done preparing all event payloads, total: {success_count}")

    print("Preparing to process these events:")
    failed_payloads = []
    for payload in payloads_to_invoke:
        print(json.dumps(payload, default=str, indent=4))
        if not args.dry_run:
            if not invoke_lambda_and_wait(lambda_client, args.lambda_function_name, payload):
                print(f"Failed to process resource {payload['resources'][0]}")
                failed_payloads.append(payload)
                continue
            else:
                print(f"Successfully processed resource {payload['resources'][0]}")
            time.sleep(args.sleep_between_api_calls)
    print(f"Done processing all events, failed total: {len(failed_payloads)}")
       

if __name__ == '__main__':
    main()