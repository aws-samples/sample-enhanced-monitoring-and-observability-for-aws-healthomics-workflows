# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT

from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration, 
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_lambda_python_alpha as lambda_python,
    aws_events as events,
    aws_events_targets as events_targets,    
    aws_sns as sns,
    aws_iam as iam,
    aws_glue as glue,
    aws_kms as kms,
    aws_ssm as ssm
)
import os
import platform
from constructs import Construct
import json
from cdk_nag import NagSuppressions
 
class omics_workflow_Stack(Stack):

    def __init__(self, scope: Construct, construct_id: str, config=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        aws_account = Stack.of(self).account
        aws_region = Stack.of(self).region

        # Prefix for all resource names
        APP_NAME = f"healthomics"
        
        # Disable IAM5 and L1 rules for this stack
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Wildcards are necessary for Lambda logs, HealthOmics resources, and pricing API"
                }
            ]
        )

        
        
        ################################################################################################
        #################################### Notification ##############################################
        
        # Create KMS key for SNS encryption
        sns_encryption_key = kms.Key(
            self,
            "SnsEncryptionKey",
            description="KMS key for SNS topic encryption",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # SNS Topic for failure notifications
        sns_topic = sns.Topic(self, f'{APP_NAME}_workflow_status_topic',
            display_name=f"{APP_NAME}_workflow_status_topic",
            topic_name=f"{APP_NAME}_workflow_status_topic",
            master_key=sns_encryption_key,  # Enable server-side encryption
            enforce_ssl=True  # Enforce SSL to address AwsSolutions-SNS3
        )

        # Create an EventBridge rule that sends SNS notification on failure
        rule_workflow_status_topic = events.Rule(
            self, f"{APP_NAME}_rule_workflow_run_failure_status_topic",
            rule_name=f"{APP_NAME}_rule_workflow_run_failure_status_topic",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"],
                detail={
                    "status": [
                        "FAILED"
                    ]
                }
            )
        )
        rule_workflow_status_topic.add_target(events_targets.SnsTopic(sns_topic))
        
        # Grant EventBridge permission to publish to the SNS topic
        sns_topic.grant_publish(iam.ServicePrincipal('events.amazonaws.com'))        

        ## DATALAKE
        # Create access logs bucket for the data lake bucket
        access_logs_bucket = s3.Bucket(
            self,
            "AccessLogsBucket",
            bucket_name=f"{APP_NAME}-access-logs-{aws_account}-{aws_region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )
        
        # Create Data Lake S3 bucket
        data_lake_bucket = s3.Bucket(
            self,
            "DataLakeBucket",
            bucket_name=f"{APP_NAME}-workflow-datalake-{aws_account}-{aws_region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=access_logs_bucket,
            server_access_logs_prefix="data-lake-access-logs/"
        )
        ##################################### Run Analyzer #############################################
        # Prefix for runmetrics from runanalyer
        METRICS_PREFIX = "run_analyzer_output"
 
        # Create dedicated Lambda role for run analyzer
        run_analyzer_role = iam.Role(
            self, f"{APP_NAME}-run-analyzer-lambda-role",
            role_name=f"{APP_NAME}-run-analyzer-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )
        
        # Add suppressions for run analyzer role
        NagSuppressions.add_resource_suppressions(
            run_analyzer_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Lambda logs and HealthOmics resources require wildcards",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/healthomics_run_analyzer_lambda_v2:*",
                        f"Resource::arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/omics/WorkflowLog:*",
                        f"Resource::arn:aws:omics:{aws_region}:{aws_account}:run/*",
                        f"Resource::arn:aws:omics:{aws_region}:{aws_account}:task/*",
                        "Resource::*",
                        f"Resource::{data_lake_bucket.bucket_arn}/run_analyzer_output/*"
                    ]
                }
            ],
            apply_to_children=True
        )
        
        # Add custom policy for Lambda basic execution 
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources=[
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/{APP_NAME}_run_analyzer_lambda_v2:*'
            ]
        ))

        # Add CloudWatch logs permissions for HealthOmics logs
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'logs:GetLogEvents',
                'logs:DescribeLogStreams'
            ],
            resources=[
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/omics/WorkflowLog:*'
            ]
        ))

        # Add pricing API permissions - Note: pricing API doesn't support resource-level permissions
        # We need to use '*' here as pricing API doesn't support resource-level permissions
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'pricing:GetProducts',
                'pricing:DescribeServices'
            ],
            resources=['*']
        ))

        # Add GetRun API permissions with specific resources
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'omics:GetRun',
                'omics:ListRuns'
            ],
            resources=[
                f'arn:aws:omics:{aws_region}:{aws_account}:run/*'
            ]
        ))
        
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'omics:ListRunTasks',
                'omics:GetRunTask'
            ],
            resources=[
                f'arn:aws:omics:{aws_region}:{aws_account}:task/*'
            ]
        ))

        # Add S3 permissions to the run analyzer role with specific prefix
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:GetBucketLocation'
            ],
            resources=[
                data_lake_bucket.bucket_arn
            ]
        ))
        
        run_analyzer_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:PutObject'
            ],
            resources=[
                f"{data_lake_bucket.bucket_arn}/{METRICS_PREFIX}/*"
            ]
        ))

        # Create the run analyzer Lambda function
        if platform.uname()[-1] == 'x86_64':
            lambda_architecture = lambda_.Architecture.X86_64
        elif platform.uname()[-1] == 'arm':
            lambda_architecture = lambda_.Architecture.ARM_64
        else:
            raise("Unsupported architecture to build run analyzer lambda docker")

        run_analyzer_lambda_v2 = lambda_.DockerImageFunction(
            self, f"{APP_NAME}_run_analyzer_lambda_v2",
            function_name=f"{APP_NAME}_run_analyzer_lambda_v2",
            code=lambda_.DockerImageCode.from_image_asset(directory='lambda/run_analyzer_v2'),
            role=run_analyzer_role,
            timeout=Duration.seconds(300),
            memory_size=128,
            architecture=lambda_architecture,
            environment={
                "DATA_LAKE_BUCKET": data_lake_bucket.bucket_name,
                "S3_PREFIX": METRICS_PREFIX,
                "LOG_LEVEL": "INFO"
            }
        )
        
        ssm.StringParameter(self, "RunAnalyzerFunction",
            parameter_name="/healthomics/lambda/run-analyzer-function",
            string_value=run_analyzer_lambda_v2.function_name
        )

        # Create EventBridge rule for run analyzer
        rule_run_analyzer = events.Rule(
            self, f"{APP_NAME}_rule_run_analyzer",
            rule_name=f"{APP_NAME}_rule_run_analyzer",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"],
                detail={
                    "status": [
                        "COMPLETED",
                        "FAILED",
                        "CANCELLED"
                    ]
                }
            )
        )
        rule_run_analyzer.add_target(events_targets.LambdaFunction(run_analyzer_lambda_v2))

        ##################################### Manifest Log ETL #########################################
        # Create dedicated Lambda role for manifest log lambda
        manifest_log_lambda_role = iam.Role(
            self, f"{APP_NAME}-manifest-log-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )
        
        # Add suppressions for manifest log lambda role
        NagSuppressions.add_resource_suppressions(
            manifest_log_lambda_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Lambda logs and S3 paths require wildcards",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/healthomics_manifest_log_lambda:*",
                        f"Resource::arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/omics/WorkflowLog:*",
                        f"Resource::{data_lake_bucket.bucket_arn}/manifest/*"
                    ]
                }
            ],
            apply_to_children=True
        )
        
        # Add custom policy for Lambda basic execution instead of using managed policy
        manifest_log_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources=[
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/{APP_NAME}_manifest_log_lambda:*'
            ]
        ))

        # Add CloudWatch logs permissions for HealthOmics logs
        manifest_log_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'logs:GetLogEvents',
                'logs:DescribeLogStreams'
            ],
            resources=[
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/omics/WorkflowLog:*'
            ]
        ))

        # Add S3 permissions to the manifest log lambda role with specific prefix
        manifest_log_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:GetBucketLocation'
            ],
            resources=[
                data_lake_bucket.bucket_arn
            ]
        ))
        
        manifest_log_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:PutObject'
            ],
            resources=[
                f"{data_lake_bucket.bucket_arn}/manifest/*"
            ]
        ))

        # Create the manifest log Lambda function with latest runtime
        manifest_log_lambda = lambda_.Function(
            self, f"{APP_NAME}_manifest_log_lambda",
            function_name=f"{APP_NAME}_manifest_log_lambda",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("lambda/manifest"),
            role=manifest_log_lambda_role,
            timeout=Duration.seconds(300),
            memory_size=128,
            environment={
                "DATA_LAKE_BUCKET": data_lake_bucket.bucket_name,
                "S3_PREFIX": "manifest",
                "LOG_LEVEL": "INFO"
            }
        )

        ssm.StringParameter(self, "ManifestLogFunction",
            parameter_name="/healthomics/lambda/manifest-log-function",
            string_value=manifest_log_lambda.function_name
        )

        # Create EventBridge rule for run analyzer
        rule_manifest = events.Rule(
            self, f"{APP_NAME}_rule_manifest",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"],
                detail={
                    "status": [
                        "COMPLETED",
                        "FAILED"
                    ]
                }
            )
        )
        rule_manifest.add_target(events_targets.LambdaFunction(manifest_log_lambda))

        ##################################### Workflow records ETL #########################################
        # Create dedicated Lambda role for workflow records lambda
        workflow_records_lambda_role = iam.Role(
            self, f"{APP_NAME}-workflow-records-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )
        
        
        # Add custom policy for Lambda basic execution instead of using managed policy
        workflow_records_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources=[
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/{APP_NAME}_workflow_records_lambda:*'
            ]
        ))

        # Add S3 permissions to the manifest log lambda role with specific prefix
        workflow_records_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:GetBucketLocation'
            ],
            resources=[
                data_lake_bucket.bucket_arn
            ]
        ))
        
        workflow_records_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:PutObject'
            ],
            resources=[
                f"{data_lake_bucket.bucket_arn}/workflow_records/*"
            ]
        ))

        workflow_records_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'omics:GetWorkflow',
                'omics:GetWorkflowVersion'
            ],
            resources=[
                f'arn:aws:omics:*:*:workflow/*'
            ]
        ))

        # Create the workflow records Lambda function with latest runtime
        workflow_records_lambda = lambda_python.PythonFunction(
            self, f"{APP_NAME}_workflow_records_lambda",
            function_name=f"{APP_NAME}_workflow_records_lambda",
            runtime=lambda_.Runtime.PYTHON_3_13,
            index="lambda_function.py",
            handler="lambda_handler",
            entry=os.path.join(os.path.dirname(__file__), "../lambda/workflow"),
            role=workflow_records_lambda_role,
            timeout=Duration.seconds(300),
            memory_size=128,
            environment={
                "DATA_LAKE_BUCKET": data_lake_bucket.bucket_name,
                "S3_PREFIX": "workflow_records",
                "LOG_LEVEL": "INFO"
            }
        )

        ssm.StringParameter(self, "WorkflowRecordsFunction",
            parameter_name="/healthomics/lambda/workflow-records-function",
            string_value=workflow_records_lambda.function_name
        )

        # Create EventBridge rule for run analyzer
        rule_workflow_created = events.Rule(
            self, f"{APP_NAME}_rule_workflow_created",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Workflow Status Change"],
                detail={
                    "status": [
                        "ACTIVE"
                    ]
                }
            )
        )
        rule_workflow_created.add_target(events_targets.LambdaFunction(workflow_records_lambda))
        

        ##################################### Run Status change Log ETL #########################################
        # Create dedicated Lambda role for run status change event lambda
        run_status_change_event_lambda_role = iam.Role(
            self, f"{APP_NAME}-run-status-change-event-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )
        
        # Add suppressions for run status change event lambda role
        NagSuppressions.add_resource_suppressions(
            run_status_change_event_lambda_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Lambda logs and S3 paths require wildcards",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/healthomics_run_status_change_event_lambda:*",
                        f"Resource::{data_lake_bucket.bucket_arn}/run_status_change_event/*"
                    ]
                }
            ],
            apply_to_children=True
        )
        
        # Add custom policy for Lambda basic execution instead of using managed policy
        run_status_change_event_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources=[
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/lambda/{APP_NAME}_run_status_change_event_lambda:*'
            ]
        ))

        # Add S3 permissions to the run status change event lambda role with specific prefix
        run_status_change_event_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:GetBucketLocation'
            ],
            resources=[
                data_lake_bucket.bucket_arn
            ]
        ))
        
        run_status_change_event_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:PutObject'
            ],
            resources=[
                f"{data_lake_bucket.bucket_arn}/run_status_change_event/*"
            ]
        ))

        # Create the run status change event Lambda function with latest runtime
        run_status_change_event_lambda = lambda_.Function(
            self, f"{APP_NAME}_run_status_change_event_lambda",
            function_name=f"{APP_NAME}_run_status_change_event_lambda",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset("lambda/run_event_processor"),
            role=run_status_change_event_lambda_role,
            timeout=Duration.seconds(300),
            memory_size=128,
            environment={
                "DATA_LAKE_BUCKET": data_lake_bucket.bucket_name,
                "S3_PREFIX": "run_status_change_event",
                "LOG_LEVEL": "INFO"
            }
        )

        ssm.StringParameter(self, "RunStatusChangeEventFunction",
            parameter_name="/healthomics/lambda/run-status-change-function",
            string_value=run_status_change_event_lambda.function_name
        )

        # Create EventBridge rule for run status change
        rule_run_status_change = events.Rule(
            self, f"{APP_NAME}_rule_run_status_change",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"]
            )
        )
        rule_run_status_change.add_target(events_targets.LambdaFunction(run_status_change_event_lambda))


        ###################### GLUE DB AND CRAWLERS ##########################
        # Create a glue table
        workflow_datalake_db = glue.CfnDatabase(
            self,
            "HealthOmicsMetricsDb",
            catalog_id=aws_account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=f"{APP_NAME}-workflow-datalake",
                description="Database for HealthOmics workflow metrics, status events, and manifest logs"
            )
        )

        # Create IAM role for the Manifest log crawler
        common_crawler_role = iam.Role(
            self, 
            "GlueCrawlerRole-HealthOmicsCommon",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com")
        )
        
        # Add suppressions for Glue crawler role
        NagSuppressions.add_resource_suppressions(
            common_crawler_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Glue tables and S3 paths require wildcards",
                    "appliesTo": [
                        f"Resource::arn:aws:glue:{aws_region}:{aws_account}:table/healthomics-workflow-datalake/*",
                        f"Resource::{data_lake_bucket.bucket_arn}/manifest/*",
                        f"Resource::{data_lake_bucket.bucket_arn}/run_analyzer_output/*",
                        f"Resource::{data_lake_bucket.bucket_arn}/run_status_change_event/*",
                        f"Resource::{data_lake_bucket.bucket_arn}/workflow_records/*"
                    ]
                }
            ],
            apply_to_children=True
        )

        # Add specific Glue permissions instead of using managed policy
        common_crawler_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "glue:CreateDatabase",
                "glue:GetDatabase",
                "glue:GetDatabases",
                "glue:UpdateDatabase",
                "glue:CreateTable",
                "glue:UpdateTable",
                "glue:GetTable",
                "glue:GetTables",
                "glue:GetPartition",
                "glue:GetPartitions",
                "glue:BatchCreatePartition",
                "glue:BatchGetPartition"
            ],
            resources=[
                f"arn:aws:glue:{aws_region}:{aws_account}:catalog",
                f"arn:aws:glue:{aws_region}:{aws_account}:database/{APP_NAME}-workflow-datalake",
                f"arn:aws:glue:{aws_region}:{aws_account}:table/{APP_NAME}-workflow-datalake/*"
            ]
        ))
        
        # Add S3 read permissions with specific actions
        common_crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:ListBucket"
                ],
                resources=[
                    data_lake_bucket.bucket_arn
                ]
            )
        )
        
        common_crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject"
                ],
                resources=[
                    f"{data_lake_bucket.bucket_arn}/{METRICS_PREFIX}/*",
                    f"{data_lake_bucket.bucket_arn}/manifest/*",
                    f"{data_lake_bucket.bucket_arn}/run_status_change_event/*"
                ]
            )
        )

        # Create KMS key for CloudWatch Logs encryption
        logs_encryption_key = kms.Key(
            self, 
            "GlueLogsEncryptionKey",
            description="KMS key for encrypting Glue CloudWatch Logs",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN
        )

        # Allow CloudWatch Logs to use the key
        logs_encryption_key.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*"],
                principals=[iam.ServicePrincipal("logs.amazonaws.com")],
                resources=["*"]
            )
        )

        # Create the Glue crawler
        healthomics_logs_crawler = glue.CfnCrawler(
            self,
            "HealthOmicsLogsDataLakeCrawler",
            name="healthomics-logs-datalake-crawler",
            role=common_crawler_role.role_arn,
            database_name=workflow_datalake_db.ref,
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{data_lake_bucket.bucket_name}/"
                    )
                ]
            ),
            schedule=glue.CfnCrawler.ScheduleProperty(
                schedule_expression="cron(0/15 * * * ? *)"  # Run every 15 mins
            ),
            schema_change_policy=glue.CfnCrawler.SchemaChangePolicyProperty(
                delete_behavior="LOG",
                update_behavior="UPDATE_IN_DATABASE"
            ),
            configuration=json.dumps({
                "Version": 1.0,
                "CreatePartitionIndex": True
            })
        )