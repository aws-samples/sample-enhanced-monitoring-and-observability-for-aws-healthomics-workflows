# Monitoring and Observability with AWS HealthOmics

This project provides a comprehensive monitoring and observability solution for AWS HealthOmics workflows. It deploys a set of AWS resources that collect, process, and analyze metrics from HealthOmics workflow runs, enabling you to gain insights into resource utilization, performance, and costs.

## Project Overview

The solution automatically captures and processes:
- Workflow run status changes
- Task-level metrics and logs
- Resource utilization data
- Cost estimation information

Data is stored in a centralized S3 data lake and made available for analysis through AWS Glue tables, allowing you to monitor your HealthOmics workflows effectively using visual tools like dashboards on Amazon QuickSight.

## Prerequisites

Before deploying this solution, you need:

### AWS Account Requirements
- An active AWS account with permissions to create the required resources
- AWS HealthOmics service access enabled in your account
- Appropriate IAM permissions to deploy CloudFormation stacks and create resources

### Software Requirements
- **AWS CLI**: Version 2.0 or later
  - Installation: [AWS CLI Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
  - Configuration: Run `aws configure` with appropriate credentials

- **Python**: Version 3.10 or later
  - Installation: [Python Downloads](https://www.python.org/downloads/)
  - Verify with: `python --version`

- **Node.js**: Version 14.x or later (required for AWS CDK)
  - Installation: [Node.js Downloads](https://nodejs.org/)
  - Verify with: `node --version` and `npm --version`

- **AWS CDK**: Version 2.100.0 or later
  - Installation: `npm install -g aws-cdk`
  - Verify with: `cdk --version`

- **Docker**: Latest version (required for synthesizing some CDK assets)
  - Installation: [Docker Installation Guide](https://docs.docker.com/get-docker/)
  - Verify with: `docker --version`

## Deployment Guide

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/monitoring-and-observability-with-aws-healthomics.git
cd monitoring-and-observability-with-aws-healthomics
```

### Step 2: Set Up Python Virtual Environment

```bash
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For development dependencies
```

### Step 3: Configure AWS Credentials

Ensure your AWS credentials are properly configured:

```bash
aws configure
```

Enter your AWS Access Key ID, Secret Access Key, default region, and output format when prompted.

Alternatively, you can set environment variables:

```bash
# On macOS/Linux:
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=your_preferred_region

# On Windows:
set AWS_ACCESS_KEY_ID=your_access_key
set AWS_SECRET_ACCESS_KEY=your_secret_key
set AWS_DEFAULT_REGION=your_preferred_region
```

### Step 4: Bootstrap AWS CDK (if not already done)

```bash
cdk bootstrap aws://ACCOUNT-NUMBER/REGION
```

Replace `ACCOUNT-NUMBER` with your AWS account number and `REGION` with your preferred AWS region.

### Step 5: Deploy the Stack

```bash
cdk deploy
```

This will deploy all resources to your AWS account. Review the changes before confirming the deployment.

### Step 6: Verify Deployment

After deployment completes, verify that:

1. All Lambda functions have been created
2. EventBridge rules are active
3. The S3 data lake bucket has been created
4. The Glue database and crawler are set up

## Resources Created

This solution deploys the following AWS resources:

### Storage
- **S3 Buckets**:
  - Data lake bucket (`healthomics-workflow-datalake-{account}-{region}`) - Stores all workflow metrics, logs, and events
  - Access logs bucket (`healthomics-access-logs-{account}-{region}`) - Stores access logs for the data lake bucket

### Database and Analytics
- **AWS Glue Database**: `healthomics-workflow-datalake` - Catalogs data for querying
- **AWS Glue Crawler**: `healthomics-logs-datalake-crawler` - Automatically discovers and catalogs data schema

### Compute & Processing
- **Lambda Functions**:
  - `healthomics_run_analyzer_lambda_v2`: Analyzes workflow runs for resource utilization and cost using HealthOmics [Run Analyzer module](https://github.com/awslabs/aws-healthomics-tools?tab=readme-ov-file#healthomics-run-analyzer)
  - `healthomics_manifest_log_lambda`: Processes workflow manifest logs
  - `healthomics_run_status_change_event_lambda`: Captures and processes run status change events
  - `healthomics_workflow_records_lambda`: Captures creation of new workflows and workflow versions

### Event Management
- **EventBridge Rules**:
  - `healthomics_rule_run_analyzer`: Triggers run analyzer Lambda on workflow completion/failure/cancellation
  - `healthomics_rule_manifest`: Triggers manifest log Lambda on workflow completion/failure
  - `healthomics_rule_run_status_change`: Triggers event processor Lambda on any status change
  - `healthomics_rule_workflow_status_change`: Triggers workflow records Lambda on workflow status change to ACTIVE
  - `healthomics_rule_workflow_run_failure_status_topic`: Sends SNS notifications on workflow failures

### Notifications
- **SNS Topic**: `healthomics_workflow_status_topic` - For workflow failure notifications

### Security
- **KMS Keys**:
  - SNS encryption key - Encrypts SNS topic messages
  - Glue logs encryption key - Encrypts CloudWatch logs for Glue

### IAM Roles
- Run analyzer Lambda role
- Manifest log Lambda role
- Run status change event Lambda role
- Workflow status change event Lambda role
- Glue crawler role

### SSM Parameters
- Store lambda names as parameters in the parameter store so that the migration scripts can reference them later

## Using the Solution

### Set up Notifications

To receive workflow failure notifications:
1. Navigate to the SNS console
2. Find the `healthomics_workflow_status_topic` topic
3. Click "Create subscription"
4. Select "Email" as the protocol
5. Enter your email address
6. Confirm the subscription via the email you receive

### Data Collection Process

Once deployed, the solution automatically monitors your HealthOmics workflow runs:

1. **Event Capture**: All run status change events are captured and stored in the S3 data lake under `run_status_change_event/`
2. **Run Analysis**: When a workflow run completes, fails, or is cancelled, the run analyzer Lambda processes metrics and stores them in the S3 data lake under `run_analyzer_output/`
3. **Manifest Processing**: Workflow manifest logs are processed and stored in the data lake under `manifest/`
4. **Workflow Records**: Workflow records are stored in the datalake under `workflow_records/`
5. **Data Cataloging**: The Glue crawler runs every 15 minutes to update the data catalog (This can be configured)
6. **Failure Notifications**: Workflow failures trigger SNS notifications to subscribed endpoints

### Analyzing the Data

You can analyze the collected data using:

1. **Amazon Athena**:
   - Navigate to the Athena console
   - Select the `healthomics-workflow-datalake` database
   - Query the tables using SQL

2. **Amazon QuickSight**:
   - Connect QuickSight to the Glue data catalog
   - Create visualizations and dashboards
   - Set up scheduled reports

## Adding New Data Sources to the Data Lake

To extend the solution with new data sources:

1. **Create a new Lambda function**:
   - Follow the pattern of existing Lambda functions in the `lambda/` directory
   - Ensure it writes data to the data lake bucket with a unique prefix

2. **Update the CDK stack**:
   - Add the new Lambda function to `cdk/cdk_stack.py`
   - Create appropriate IAM permissions
   - Set up EventBridge rules to trigger the Lambda

3. **Update the Glue crawler configuration**:
   - Ensure the crawler has permissions to access the new data location
   - Add the new S3 path to the crawler's targets if needed

4. **Deploy the updated stack**:
   - Run `cdk deploy` to update the resources

5. **Verify data flow**:
   - Check that data is being written to the S3 bucket
   - Confirm the Glue crawler is creating tables for the new data

## Reprocessing Historical Runs

After the solution is deployed, we recommend migrating existing HealthOmics workflow and run information into the Datalake to get started.
We have scripts to load historic data in the [scripts dir](scripts/README.md)


## Required IAM Permissions

To deploy and use this solution, you need the following IAM permissions:

### Deployment Permissions
- CloudFormation: `cloudformation:*`
- IAM: `iam:CreateRole`, `iam:AttachRolePolicy`, etc.
- Lambda: `lambda:CreateFunction`, `lambda:AddPermission`, etc.
- S3: `s3:CreateBucket`, `s3:PutBucketPolicy`, etc.
- EventBridge: `events:PutRule`, `events:PutTargets`, etc.
- SNS: `sns:CreateTopic`, `sns:Subscribe`, etc.
- Glue: `glue:CreateDatabase`, `glue:CreateCrawler`, etc.
- KMS: `kms:CreateKey`, `kms:PutKeyPolicy`, etc.
- SSM: `ssm:PutParameter`

### Runtime Permissions
- HealthOmics: `omics:GetRun`, `omics:ListRuns`, `omics:GetRunTask`, `omics:ListRunTasks`, `omics:GetWorkflow`, `omics:GetWorkflowVersion`
- CloudWatch Logs: `logs:GetLogEvents`, `logs:DescribeLogStreams`
- S3: `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`
- Pricing API: `pricing:GetProducts`, `pricing:DescribeServices`

### Least Privilege Principle
The solution follows the principle of least privilege by:
- Creating dedicated IAM roles for each Lambda function
- Restricting S3 access to specific prefixes
- Using resource-level permissions where supported
- Implementing KMS encryption for sensitive data

## Security Considerations

This solution implements several security best practices:

1. **Data Encryption**:
   - S3 buckets use server-side encryption
   - SNS topics are encrypted with KMS
   - CloudWatch Logs are encrypted with KMS
   - Athena query results are encrypted with KMS

2. **Access Control**:
   - IAM roles follow the principle of least privilege
   - S3 bucket policies restrict access
   - Server access logging is enabled for the data lake bucket

3. **Network Security**:
   - SSL/TLS is enforced for all service communications
   - No public access to S3 buckets

4. **Monitoring and Auditing**:
   - CloudWatch Logs capture Lambda function activity
   - S3 access logs track data lake access

5. **Key Rotation**:
   - KMS keys have automatic rotation enabled
  
6. **Governance**:
   - Consider implementing Message Data Protection on any SNS topic that handles sensitive or regulated data. See https://docs.aws.amazon.com/sns/latest/dg/message-data-protection.html#why-use-message-data-protection
   - Specify an owner to review SNS Application-to-Person (A2P) messaging targets periodically. Verify that all mobile numbers and email domains are accurate and current. Remove or replace outdated targets

> **Note**: This solution processes and stores HealthOmics workflow metadata. Ensure that your usage complies with your organization's data governance policies and any applicable regulations.

## Troubleshooting

Common issues and their solutions:

1. **Lambda Function Timeouts**:
   - Increase the timeout value in the CDK stack
   - Check for inefficient code or API rate limiting

2. **Missing Permissions**:
   - Ensure your deployment role has all necessary permissions
   - Check CloudTrail for permission denied errors

3. **Glue Crawler Issues**:
   - Verify S3 bucket permissions
   - Ensure data format is consistent
   - Check CloudWatch Logs for crawler errors

4. **EventBridge Rule Not Triggering**:
   - Verify that the rule pattern matches the events
   - Check that the target Lambda function exists
   - Ensure the rule is enabled

5. **Reprocessing Script Failures**:
   - Verify AWS credentials have appropriate permissions
   - Check that SSM parameters exist
   - Increase Lambda timeout for large workflows

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT-0 License - see the LICENSE file for details.