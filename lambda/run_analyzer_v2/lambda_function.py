# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

from omics.cli.run_analyzer.__main__ import main as run_analyzer_main
import json
import os
import sys
import boto3
import logging 

def upload_file_to_s3(local_file_path, bucket_name, s3_file_path):
    """
    Uploads a local file to an S3 bucket.

    Args:
        local_file_path (str): The path to the local file to upload.
        bucket_name (str): The name of the S3 bucket to upload to.
        s3_file_path (str): The path to the file in S3.
    """
    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(local_file_path, bucket_name, s3_file_path)
        print(f"File '{local_file_path}' uploaded to '{bucket_name}/{s3_file_path}' successfully.")
    except Exception as e:
        print(f"Error uploading file: {e}")

def handler(event, context):
    BUCKET_NAME=os.environ['DATA_LAKE_BUCKET']
    PREFIX=os.environ['S3_PREFIX']

    VERBOSE_LOGGING = os.environ.get('VERBOSE_LOGGING', 'false').lower() == 'true'
    log_level = logging.DEBUG if VERBOSE_LOGGING else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger()
    logger.setLevel(log_level)

    try:
        region = os.environ['AWS_REGION']
    except KeyError:
        arn = context.invoked_function_arn
        region = arn.split(':')[3]
    logger.info(f"Lambda function running in region: {region}")
    try:
        run_id = event['detail']['runId']
    except:
        raise("Unable to get runID from event detail, exiting")
    
    output_file_name = f'{run_id}_run_analyzer_output.csv'
    output_file_location = f'/tmp/{output_file_name}'

    try:
        logger.info(f"Attempting to run run_analyzer for run ID: {run_id}")
        run_analyzer_main([run_id,'--region', region, '--out', output_file_location])
    except Exception as e:
        logger.error(f"run analyzer failed for run ID: {run_id}")
        raise e
    logger.info(f"Run analyzer ran successfully for run ID: {run_id}")

    try:
        logger.info(f"Attempting to upload run analyzer output for run ID: {run_id}")
        upload_file_to_s3(output_file_location, BUCKET_NAME, PREFIX + f'/{output_file_name}' )
    except Exception as e:
        logger.error(f"Upload of run analyzer output {output_file_location} failed")
        raise e
    logger.info(f"Run analyzer completed for run {run_id}, uploaded to s3://{BUCKET_NAME}/{PREFIX}/{output_file_name}")
    return {
        'statusCode': 200,
        'body': json.dumps(f'Run analyzer completed for run {run_id}, uploaded to s3://{BUCKET_NAME}/{PREFIX}/{output_file_name}')
    }

if __name__ == '__main__':
    event = sys.argv[1:]
    handler(event, None)