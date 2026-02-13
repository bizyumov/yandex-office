# Yandex Cloud API Reference

Quick reference for common Yandex Cloud APIs and SDKs.

## Yandex Cloud CLI (yc)

### Cloud Functions

```bash
# Create function
yc serverless function create --name <name>

# Create version (deploy)
yc serverless function version create \
  --function-name <name> \
  --runtime python312 \
  --entrypoint handler.handler \
  --memory 256m \
  --execution-timeout 5m \
  --source-path function.zip

# List functions
yc serverless function list

# Get function details
yc serverless function get <id-or-name>

# View logs
yc serverless function logs <id> --follow

# Invoke function
yc serverless function invoke <id> --data '{"key":"value"}'

# Delete function
yc serverless function delete <name>
```

### Triggers

```bash
# Create timer (cron)
yc serverless trigger create timer \
  --name <name> \
  --cron-expression '0 5 * * ? *' \
  --invoke-function-id <function-id>

# List triggers
yc serverless trigger list

# Delete trigger
yc serverless trigger delete <name>
```

### Object Storage

```bash
# Create bucket
yc storage bucket create <bucket-name>

# List buckets
yc storage bucket list

# List objects
yc storage object list --bucket <bucket-name>

# Upload file
yc storage object put --bucket <bucket> --key <key> --file <path>

# Download file
yc storage object get --bucket <bucket> --key <key> --file <path>

# Delete object
yc storage object delete --bucket <bucket> --key <key>
```

### Service Accounts

```bash
# Create service account
yc iam service-account create --name <name>

# List service accounts
yc iam service-account list

# Create access key (for Object Storage)
yc iam access-key create --service-account-name <name>

# Grant role
yc resource-manager folder add-access-binding <folder-id> \
  --role storage.editor \
  --subject serviceAccount:<sa-id>
```

## Python SDK (boto3 for Object Storage)

```python
import boto3

# Initialize client
s3 = boto3.client(
    's3',
    endpoint_url='https://storage.yandexcloud.net',
    aws_access_key_id='<access-key>',
    aws_secret_access_key='<secret-key>',
    region_name='ru-central1'
)

# Upload file
s3.upload_file('local.txt', 'bucket-name', 'remote.txt')

# Upload bytes
s3.put_object(
    Bucket='bucket-name',
    Key='data.json',
    Body=b'{"key":"value"}'
)

# Download file
s3.download_file('bucket-name', 'remote.txt', 'local.txt')

# Download bytes
obj = s3.get_object(Bucket='bucket-name', Key='data.json')
data = obj['Body'].read()

# List objects
response = s3.list_objects_v2(Bucket='bucket-name')
for obj in response.get('Contents', []):
    print(obj['Key'])

# Delete object
s3.delete_object(Bucket='bucket-name', Key='file.txt')

# Check if object exists
try:
    s3.head_object(Bucket='bucket-name', Key='file.txt')
    exists = True
except s3.exceptions.ClientError:
    exists = False
```

## REST API (Cloud Functions)

### Invoke Function (HTTP)

```bash
curl -X POST \
  -H "Authorization: Bearer <IAM-token>" \
  -d '{"key":"value"}' \
  https://functions.yandexcloud.net/<function-id>
```

### Get Function Info

```bash
curl -H "Authorization: Bearer <IAM-token>" \
  https://serverless-functions.api.cloud.yandex.net/functions/v1/functions/<function-id>
```

## IAM Tokens

### Get IAM token (OAuth)

```bash
yc iam create-token
```

Token valid for 12 hours.

### Get IAM token (Service Account)

```bash
curl -X POST \
  -H "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token
```

From within Cloud Function (automatic).

## Environment Variables Access

In function code:

```python
import os

api_key = os.getenv('API_KEY')
debug = os.getenv('DEBUG', 'false') == 'true'
```

Set during deployment:

```bash
yc serverless function version create \
  --environment API_KEY=secret,DEBUG=true \
  ...
```

## Context Object

In Python functions:

```python
def handler(event, context):
    # context.request_id - unique request ID
    # context.function_name - function name
    # context.function_version - version ID
    # context.memory_limit_in_mb - memory limit
    # context.token - IAM token (if service account attached)
    
    print(f"Request ID: {context.request_id}")
    print(f"Memory: {context.memory_limit_in_mb} MB")
    
    return {'statusCode': 200}
```

## Event Object

### HTTP Trigger

```python
def handler(event, context):
    # event['httpMethod'] - GET, POST, etc.
    # event['headers'] - request headers
    # event['body'] - request body (string)
    # event['queryStringParameters'] - query params
    # event['requestContext'] - metadata
    
    method = event.get('httpMethod')
    body = event.get('body', '')
    
    return {
        'statusCode': 200,
        'body': 'Response',
        'headers': {'Content-Type': 'text/plain'}
    }
```

### Timer Trigger

```python
def handler(event, context):
    # event['messages'][0]['event_metadata']['created_at'] - trigger time
    
    return {'statusCode': 200}
```

### Object Storage Trigger

```python
def handler(event, context):
    # event['messages'][0]['details']['bucket_id'] - bucket name
    # event['messages'][0]['details']['object_id'] - object key
    
    bucket = event['messages'][0]['details']['bucket_id']
    key = event['messages'][0]['details']['object_id']
    
    print(f"New object: {bucket}/{key}")
    
    return {'statusCode': 200}
```

## Logging

```python
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    logger.info('Processing request')
    logger.warning('Warning message')
    logger.error('Error message')
    
    return {'statusCode': 200}
```

Logs appear in Cloud Logging automatically.

## Common Response Formats

### Success

```python
return {
    'statusCode': 200,
    'body': 'Success'
}
```

### JSON Response

```python
import json

return {
    'statusCode': 200,
    'headers': {'Content-Type': 'application/json'},
    'body': json.dumps({'result': 'data'})
}
```

### Error

```python
return {
    'statusCode': 500,
    'body': 'Internal error'
}
```

## Debugging Tips

### Test locally

```python
# test.py
from handler import handler

event = {'key': 'value'}
context = type('obj', (object,), {
    'request_id': 'test-123',
    'function_name': 'test-function',
    'memory_limit_in_mb': 128
})()

result = handler(event, context)
print(result)
```

### View logs

```bash
# Tail logs
yc serverless function logs <function-id> --follow

# Last 100 lines
yc serverless function logs <function-id> --lines 100

# Filter by level
yc serverless function logs <function-id> | grep ERROR
```

### Invoke with test data

```bash
echo '{"test": "data"}' > test.json
yc serverless function invoke <function-id> --data-file test.json
```

## Rate Limits

- **Invocations:** 1000 per second per function
- **Concurrent executions:** 10 (soft limit, can be increased)
- **Deployment:** 10 versions per minute

## Resource Limits

- **Code size:** 128 MB (zipped)
- **Memory:** 128 MB - 4 GB
- **Timeout:** 1s - 10 minutes
- **Temp storage:** 512 MB (`/tmp`)

## Regions & Zones

- **ru-central1-a** (Moscow) - default
- **ru-central1-b** (Moscow)
- **ru-central1-c** (Moscow)

Specify with `--zone` flag if needed.
