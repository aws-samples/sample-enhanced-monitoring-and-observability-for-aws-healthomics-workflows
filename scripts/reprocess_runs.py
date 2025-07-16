# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import boto3
import argparse
import json
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError
from botocore.config import Config


def get_function_name_from_ssm(parameter_name):
    """Get Lambda function name from SSM Parameter Store"""
    ssm_client = boto3.client('ssm')
    try:
        response = ssm_client.get_parameter(Name=parameter_name)
        return response['Parameter']['Value']
    except ClientError as e:
        print(f"Error getting SSM parameter: {str(e)}")
        raise

PROCESSOR_CONFIG = {
    "run_analyzer": {
        "function_parameter": "/healthomics/lambda/run-analyzer-function"
    },
    "manifest": {
        "function_parameter": "/healthomics/lambda/manifest-log-function"
    },
    "run_status_change_event": {
        "function_parameter": "/healthomics/lambda/run-status-change-function"
    }
}

def parse_args():
    parser = argparse.ArgumentParser(description='Reprocess HealthOmics runs through selected logs processor Lambda functions')
    parser.add_argument('--limit', type=int, default=50,
                       help='Maximum number of runs to process (default: 50)')
    parser.add_argument('--processors', 
                       nargs='+',  # Accept one or more values
                       choices=['run_analyzer', 'manifest', 'run_status_change_event', 
                              'ALL'],
                       default=['ALL'],  # Default value
                       help='Specify which log processors to run. Use ALL for all processors')
    parser.add_argument('--dry-run', action='store_true',
                       help='Print what would be done without actually invoking Lambda')
    parser.add_argument('--sleep-between-runs', type=int, default=1,
                        help='Duration in seconds between each run being submitted to prevent API throttling')
    parser.add_argument('--lambda-timeout', type=int, default=300,
                        help='Timeout in seconds for Lambda invocation (default: 300, max: 900)')
    parser.add_argument('--run-ids', type=str, default=None,
                        help="CSV list of runs to process. It will ignore the --limit parameter")
    
    return parser.parse_args()

def find_run_analyzer_lambda():
    """Auto-detect the run analyzer Lambda function."""
    lambda_client = boto3.client('lambda')
    matching_functions = []

    try:
        # List all functions and filter for our run analyzer
        paginator = lambda_client.get_paginator('list_functions')
        for page in paginator.paginate():
            for function in page['Functions']:
                # Look for functions that match our CDK naming pattern
                if 'healthomicsrunanalyzer' in function['FunctionName'].lower():
                    matching_functions.append(function['FunctionName'])
                    
        if not matching_functions:
            raise ValueError("Could not find run analyzer Lambda function. Please specify with --lambda-function")
            
        if len(matching_functions) > 1:
            matches = "\n  - ".join(matching_functions)
            raise ValueError(
                f"Found multiple matching Lambda functions:\n  - {matches}\n"
                "Please specify which function to use with --lambda-function"
            )
            
        print(f"Found run analyzer Lambda: {matching_functions[0]}")
        return matching_functions[0]
        
    except ClientError as e:
        print(f"Error listing Lambda functions: {str(e)}")
        raise

def invoke_lambda_and_wait(lambda_client, function_name, payload):
    """Invoke Lambda and wait for completion"""
    print(f"\nInvoking Lambda function: {function_name}")
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',  # Synchronous invocation
            Payload=json.dumps(payload)
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

def list_workflow_runs(omics_client, max_runs):
    """List HealthOmics workflow runs"""
    print(f"\nFetching up to {max_runs} workflow runs...")
    runs = []
    
    try:
        paginator = omics_client.get_paginator('list_runs')
        for page in paginator.paginate():
            for run in page['items']:
                runs.append(run)
                if len(runs) >= max_runs:
                    return runs
    except Exception as e:
        print(f"Error listing workflow runs: {str(e)}")
        raise
        
    return runs

def get_run_status(omics_client, run_id):
    """Get the current status of a workflow run"""
    try:
        response = omics_client.get_run(id=run_id)
        return response.get('status')
    except Exception as e:
        print(f"Error getting status for run {run_id}: {str(e)}")
        raise

def get_workflow_name(omics_client, workflow_id, workflow_type):
    """Get workflow name from the GetWorkflow API"""
    try:
        response = omics_client.get_workflow(
            id=workflow_id,
            type=workflow_type
        )
        return response.get('name', 'Unknown')
    except Exception as e:
        print(f"Error getting workflow name for workflow {workflow_id}: {str(e)}")
        return 'Unknown'

def main():
    session = boto3.session.Session()

    args = parse_args()

    

    if 'ALL' in args.processors:
        args.processors = list(PROCESSOR_CONFIG.keys())
        print(f"Running all processors: {args.processors}")

    for processor_name in args.processors:
        config = PROCESSOR_CONFIG[processor_name]
        lambda_function = get_function_name_from_ssm(config['function_parameter'])
        if not lambda_function:
            raise(f"Unknown processor: {processor_name}")

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

    # use run list if provided, else pull from listruns
    if args.run_ids is not None:
        runs = args.run_ids.split(',')
    else:
        _runs = list_workflow_runs(omics_client, args.limit)
        runs = [r['id'] for r in _runs]
    print(f"Found {len(runs)} workflow runs to process")

    if args.dry_run:
        print("Dry run - would process these runs:", json.dumps(runs, indent=2))
        return
    
    caller_account = boto3.client('sts').get_caller_identity()['Account']
    caller_aws_region = os.environ.get('AWS_REGION')

    # Process each run
    success_count = 0
    for run in runs:
        print(f"\nProcessing run: {run}")

        # Get current run status
        run_details = omics_client.get_run(id=run)
        run_status = get_run_status(omics_client, run)
        workflow_id = run_details.get('workflowId')
        workflow_type = run_details.get('workflowType')
        workflow_name = get_workflow_name(omics_client, workflow_id, workflow_type)
        print(f"Run status: {run_status}")
        
        # Ensure payload mimics service's event schema
        # https://docs.aws.amazon.com/omics/latest/dev/eventbridge.html
        payload = {
            "version": "0",
            "id": f"reprocess-{run}",
            "detail-type": "Omics Workflow Run Status Change",
            "source": "reprocess_runs.py",
            "account": caller_account,
            "time": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            "region": caller_aws_region,
            "detail": {
                "runId": run,
                "status": run_status,
                "workflowName": workflow_name,
                "reprocess": True
            }
        }
        
        for processor_name in args.processors:
            config = PROCESSOR_CONFIG[processor_name]
            lambda_function = get_function_name_from_ssm(config['function_parameter'])

            if not invoke_lambda_and_wait(lambda_client, lambda_function, payload):
                print(f"Failed to process run {run} with {lambda_function}")
                continue
        success_count += 1
            
        time.sleep(args.sleep_between_runs)
    
    print(f"\nSuccessfully processed {success_count} out of {len(runs)} runs")
    

if __name__ == '__main__':
    main()