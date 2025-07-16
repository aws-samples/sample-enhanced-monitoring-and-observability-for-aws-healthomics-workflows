# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json
import boto3
from datetime import datetime
import uuid
import os
import logging

# Create a function to flatten the event JSON 
def flatten(event):
    flat_event = {}
    for key, value in event.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat_event[f"{sub_key}"] = sub_value
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for sub_key, sub_value in item.items():
                        flat_event[f"{sub_key}_{i}"] = sub_value
                else:
                    flat_event[f"{key}_{i}"] = item
        else:
            flat_event[key] = value
    return flat_event

def lambda_handler(event, context):
    # Initialize S3 client
    s3 = boto3.client('s3')
    
    try:
        DATA_LAKE_BUCKET = os.environ['DATA_LAKE_BUCKET']
        S3_PREFIX = os.environ.get('S3_PREFIX')
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

    # Generate unique filename using timestamp and UUID
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'event_{timestamp}_{str(uuid.uuid4())}.json'
    
    try:
        # Flatten the event JSON
        flat_event = flatten(event)
        
        # Convert flattened dict to JSON string
        json_data = json.dumps(flat_event)
        
        # Upload to S3
        try:
            s3.put_object(
                Bucket=DATA_LAKE_BUCKET,
                Key=f'{S3_PREFIX}/{file_name}',
                Body=json_data,
                ContentType='application/json'
            )
        except Exception as e:
            raise Exception(f"Error uploading to S3: {str(e)}")
        
        return {
            'statusCode': 200,
            'body': f'Event successfully stored in S3: {file_name}'
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f'Error processing event: {str(e)}'
        }