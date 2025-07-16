# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import boto3
from typing import List, Dict, Any, Optional
import os
import logging
import json

RUN_MANIFEST_SCHEMA = {
    "arn": str,
    "creationTime": str,
    "digest": str,
    "failureReason": str,
    "metrics": str,
    "name": str,
    "outputUri": str,
    "parameterTemplate": str,
    "parameters": str,
    "resourceDigests": str,
    "roleArn": str,
    "startTime": str,
    "startedBy": str,
    "status": str,
    "statusMessage": str,
    "stopTime": str,
    "storageType": str,
    "uuid": str,
    "workflow": str
}

TASK_MANIFEST_SCHEMA = {
    "arn": str,
    "cpus": int,
    "creationTime": str,
    "failureReason": str,
    "gpus": int,
    "image": str,
    "instanceType": str,
    "memory": int,
    "metrics": str,
    "name": str,
    "run": str,
    "startTime": str,
    "status": str,
    "statusMessage": str,
    "stopTime": str,
    "uuid": str,
    "workflow": str
}
def convert_data_types(data, type_mapping):
    if isinstance(data, dict):
        for key, value in data.items():
            if key in type_mapping:
                target_type = type_mapping[key]
                if value is not None:
                    try:
                        data[key] = target_type(value)
                    except ValueError:
                         print(f"Could not convert value '{value}' for key '{key}' to type '{target_type.__name__}'")
                else:
                    data[key] = None
            elif isinstance(value, (dict, list)):
                convert_data_types(value, type_mapping)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                convert_data_types(item, type_mapping)
    return data

# function to write a JSON as a file in S3
def write_json_to_s3(bucket_name, file_name, json_data):
    s3 = boto3.resource('s3')
    s3_object = s3.Object(bucket_name, file_name)
    s3_object.put(
        Body=(bytes(json.dumps(json_data).encode('UTF-8')))
    )


def find_log_streams_by_prefix(
    log_group_name: str,
    prefix: str,
    region: str,
    limit: Optional[int] = None,
    order_by: str = "LastEventTime",  # or "LogStreamName"
    descending: bool = False,
    profile_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Find CloudWatch log streams within a log group by prefix.

    Args:
        log_group_name: The name of the CloudWatch log group
        prefix: The prefix to filter log streams by
        region: AWS region name 
        limit: Maximum number of log streams to return (default: None, returns all)
        order_by: Sort order - "LogStreamName" or "LastEventTime" (default: LogStreamName)
        descending: Whether to sort in descending order (default: False)
        profile_name: AWS profile name to use (default: None, uses default profile)

    Returns:
        List of log stream objects matching the prefix
    """
    # Create a session with the specified profile if provided
    if profile_name:
        session = boto3.Session(profile_name=profile_name, region_name=region)
    else:
        session = boto3.Session(region_name=region)

    # Create CloudWatch Logs client
    logs_client = session.client('logs')

    # Parameters for the API call
    params = {
        'logGroupName': log_group_name,
        'logStreamNamePrefix': prefix,
        'orderBy': order_by,
        'descending': descending
    }

    # Add limit if specified
    if limit:
        params['limit'] = limit

    # Initialize result list and pagination token
    all_streams = []
    next_token = None

    # Paginate through results
    while True:
        # Add next token if we have one
        if next_token:
            params['nextToken'] = next_token

        # Make the API call
        response = logs_client.describe_log_streams(**params)

        # Add the log streams to our result
        all_streams.extend(response.get('logStreams', []))

        # Check if there are more results
        next_token = response.get('nextToken')
        if not next_token or (limit and len(all_streams) >= limit):
            break

    # If limit was specified, ensure we don't return more than requested
    if limit and len(all_streams) > limit:
        all_streams = all_streams[:limit]

    return all_streams


def get_log_events_by_stream_prefix(
    log_group_name: str,
    prefix: str,
    region: str,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    max_streams: int = 10,
    profile_name: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get log events from all streams matching a prefix in a log group.

    Args:
        log_group_name: The name of the CloudWatch log group
        prefix: The prefix to filter log streams by
        start_time: Start time in milliseconds since epoch (default: None)
        end_time: End time in milliseconds since epoch (default: None)
        region: AWS region name
        max_streams: Maximum number of streams to process (default: 10)
        profile_name: AWS profile name to use (default: None, uses default profile)

    Returns:
        Dictionary mapping stream names to lists of log events
    """
    # Find matching log streams
    streams = find_log_streams_by_prefix(
        log_group_name=log_group_name,
        prefix=prefix,
        region=region,
        limit=max_streams,
        order_by="LogStreamName",
        descending=True,
        profile_name=profile_name
    )

    # Create a session with the specified profile if provided
    if profile_name:
        session = boto3.Session(profile_name=profile_name, region_name=region)
    else:
        session = boto3.Session(region_name=region)

    # Create CloudWatch Logs client
    logs_client = session.client('logs')

    # Dictionary to store results
    all_events = {}

    # Process each stream
    for stream in streams:
        stream_name = stream['logStreamName']
        print(f"Fetching events from stream: {stream_name}")

        # Parameters for the get-log-events call
        params = {
            'logGroupName': log_group_name,
            'logStreamName': stream_name,
            'startFromHead': True
        }

        # Add time range if specified
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time

        # Initialize events list and pagination token
        stream_events = []
        next_token = None

        # Paginate through results
        while True:
            # Add next token if we have one
            if next_token:
                params['nextToken'] = next_token

            # Make the API call
            response = logs_client.get_log_events(**params)

            # Add the events to our result
            events = response.get('events', [])
            stream_events.extend(events)

            # Check if there are more results
            next_token = response.get('nextForwardToken')
            if not next_token or next_token == params.get('nextToken'):
                break

        # Store the events for this stream
        all_events[stream_name] = stream_events

    return all_events

def lambda_handler(event, context):
    arn_elements = context.invoked_function_arn.split(":")
    OMICS_AWS_REGION = arn_elements[3]
    try:
        DATA_LAKE_BUCKET = os.environ['DATA_LAKE_BUCKET']
        S3_PREFIX = os.environ.get('S3_PREFIX', '')
    except KeyError as e:
        raise ValueError(f"Required environment variable {str(e)} is not set")

    VERBOSE_LOGGING = os.environ.get('VERBOSE_LOGGING', 'false').lower() == 'true'
    log_level = logging.DEBUG if VERBOSE_LOGGING else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Reduce boto3 logging noise
    logging.getLogger('boto3').setLevel(logging.INFO)
    logging.getLogger('botocore').setLevel(logging.INFO)

    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        run_id = event['detail']['runId']
    except KeyError as e:
        logger.error(f"Failed to extract required information from event: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps('Missing required event detail')
        }
    
    manifest_log_stream_prefix = f"manifest/run/{run_id}"
    streams = find_log_streams_by_prefix(
        log_group_name="/aws/omics/WorkflowLog",
        prefix=manifest_log_stream_prefix,
        limit=10,
        region=OMICS_AWS_REGION,
        order_by="LogStreamName",
        descending=True
    )

    # Print the results , ideally 1 stream only
    if len(streams) > 1:
        logger.warning(f"Found more than 1 stream for run {run_id}, using the first one")
    stream = streams[0]
    logger.info(f"Found {len(streams)} streams for run {run_id}")
    logger.info(f"Using stream {stream['logStreamName']}")

    # Optionally, fetch and print log events for each stream
    events = get_log_events_by_stream_prefix(
        log_group_name="/aws/omics/WorkflowLog",
        prefix=stream['logStreamName'],
        region=OMICS_AWS_REGION,
        max_streams=1
    )

    S3_KEY_RUN = f"{S3_PREFIX}/runs/{run_id}.json"

    # Store stream event message as json
    for stream_name, stream_events in events.items():
        for event in stream_events:
            event_message = json.loads(event['message'])
            logger.info(f"{event_message}")
            
            if ":run/" in event_message['arn']:
                transformed_event_message = convert_data_types(event_message, RUN_MANIFEST_SCHEMA)
                write_json_to_s3(DATA_LAKE_BUCKET, S3_KEY_RUN, transformed_event_message)
            elif ":task/" in event_message['arn']:
                task_id = event_message['arn'].split('/')[-1]
                S3_KEY_TASK = f"{S3_PREFIX}/tasks/{task_id}.json"
                transformed_event_message = convert_data_types(event_message, TASK_MANIFEST_SCHEMA)
                write_json_to_s3(DATA_LAKE_BUCKET, S3_KEY_TASK, transformed_event_message)
            else:
                logger.error(f"Unknown event type: {event_message['arn']}")
                raise
    

    return {
        'statusCode': 200,
        'body': 'Manifest ETL complete'
    }

# Example usage
if __name__ == "__main__":
    # Find log streams in a log group with a specific prefix
    os.environ['DATA_LAKE_BUCKET'] = 'tests3metadatanbulsara'
    os.environ['S3_PREFIX'] = 'workflow_manifest'
    lambda_handler({'detail': {'runId': '4408708'}}, None)
    