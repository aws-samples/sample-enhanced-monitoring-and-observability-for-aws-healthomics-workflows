# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

import json
import boto3
import os
import logging
from jsonschema import validate
from jsonschema.exceptions import ValidationError

event_schema = {
  "$schema": "http://json-schema.org/draft-04/schema#",
  "type": "object",
  "properties": {
    "version": {
      "type": "string"
    },
    "id": {
      "type": "string"
    },
    "detail-type": {
      "type": "string"
    },
    "source": {
      "type": "string"
    },
    "account": {
      "type": "string"
    },
    "time": {
      "type": "string"
    },
    "region": {
      "type": "string"
    },
    "resources": {
      "type": "array",
      "items": [
        {
          "type": "string"
        }
      ]
    },
    "detail": {
      "type": "object",
      "properties": {
        "omicsVersion": {
          "type": "string"
        },
        "arn": {
          "type": "string"
        },
        "status": {
          "type": "string"
        },
        "workflowVersionName": {
          "type": "string"
        },
        "workflowUuid": {
          "type": "string"
        }
      },
      "required": [
        "omicsVersion",
        "arn",
        "status",
        "workflowUuid"
      ]
    }
  },
  "required": [
    "version",
    "id",
    "detail-type",
    "source",
    "account",
    "time",
    "region",
    "resources",
    "detail"
  ]
}

# Create function to validate event data against schema
def is_event_valid(event):
    try:
        validate(instance=event, schema=event_schema)
        return True
    except ValidationError as e:
        print(f"Validation error: {e}")
        return False

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
    
    try:
        logger.info(f"Validating event data against schema")
        if is_event_valid(event):
            logger.info(f"Event data is valid")
        else:
            raise Exception("Event data is invalid")
        workflow_versions = []

        # Get workflow details from event using HealthOmics get-workflow API
        logger.info(f"Getting workflow details from event")
        workflow_id = event['detail']['arn'].split('/')[-1]
        logger.info(f"Parent Workflow ID: {workflow_id}")
        healthomics = boto3.client('omics')
        workflow_details = healthomics.get_workflow(id=workflow_id)
        logger.debug(f"Workflow details: {workflow_details}")
        workflow_name = workflow_details['name']
        item = {}
        
        # Get workflow version details if present
        if 'workflowVersionName' in event['detail']:
            workflow_version_name = event['detail']['workflowVersionName'].split('/')[-1]
            logger.info(f"Workflow Version Name: {workflow_version_name}")
            workflow_version_details = healthomics.get_workflow_version(workflowId=workflow_id, versionName=workflow_version_name)
            logger.debug(f"Workflow version details: {workflow_version_details}")
            item = workflow_version_details
            item['name'] = workflow_name
            file_name = f'workflow_id_{workflow_id}_version_{workflow_version_name}.json'
        # treat this event as parent workflow creation event 
        else:
            logger.info(f"No workflow version details found, new parent workflow")
            item = workflow_details
            item['versionName'] = None
            if 'id' in item:
                del item['id']
            item['workflowId'] = workflow_id
            file_name = f'workflow_id_{workflow_id}.json'

        
        if 'ResponseMetadata' in item:
            del item['ResponseMetadata']
          
        item['parameterTemplate'] = json.dumps(item['parameterTemplate'], indent=4, sort_keys=True, default=str)

        # Upload to S3
        logging.info("Attempt to upload")
        try:
            s3.put_object(
                Bucket=DATA_LAKE_BUCKET,
                Key=f'{S3_PREFIX}/{file_name}',
                Body=json.dumps(item, default=str),
                ContentType='application/json'
            )
            logging.info("Upload successful")
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