#!/bin/bash
#
# Deploy a serverless function to Yandex Cloud Functions.
# Usage: ./deploy_function.sh <function-name> <path-to-code> [--dry-run]
#
# Environment:
#   SESSION_BUCKET   - S3 bucket name for session storage (optional)
#

set -e

FUNCTION_NAME="${1:?Usage: deploy_function.sh <function-name> <path-to-code> [--dry-run]}"
CODE_PATH="${2:-.}"
DRY_RUN=false
[[ "${3:-}" == "--dry-run" ]] && DRY_RUN=true

BUCKET="${SESSION_BUCKET:-}"

echo "Deploying function to Yandex Cloud"
echo "   Function: $FUNCTION_NAME"
echo "   Code path: $CODE_PATH"
echo "   Dry run: $DRY_RUN"
[ -n "$BUCKET" ] && echo "   Session bucket: $BUCKET"

# Check required files
if [ ! -f "$CODE_PATH/handler.py" ]; then
    echo "ERROR: handler.py not found in $CODE_PATH"
    exit 1
fi

if [ ! -f "$CODE_PATH/requirements.txt" ]; then
    echo "ERROR: requirements.txt not found in $CODE_PATH"
    exit 1
fi

if $DRY_RUN; then
    echo ""
    echo "Dry run validation:"
    echo "  handler.py: OK"
    echo "  requirements.txt: OK"
    echo "  Would deploy as: $FUNCTION_NAME (python312, 256m, 5m timeout)"
    [ -n "$BUCKET" ] && echo "  Would set SESSION_BUCKET=$BUCKET"
    echo "Dry run complete. No changes made."
    exit 0
fi

# Check yc CLI is installed
if ! command -v yc &> /dev/null; then
    echo "ERROR: Yandex Cloud CLI (yc) not found."
    echo "Install: https://cloud.yandex.com/docs/cli/quickstart"
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r "$CODE_PATH/requirements.txt" -t "$CODE_PATH/lib" -q

# Create deployment package
echo "Creating deployment package..."
cd "$CODE_PATH"
zip -r function.zip handler.py lib/ -q
cd -

# Check if function exists
if yc serverless function get "$FUNCTION_NAME" &> /dev/null; then
    echo "Updating existing function..."
else
    echo "Creating new function..."
    yc serverless function create --name "$FUNCTION_NAME"
fi

# Build environment flags
ENV_FLAGS=""
[ -n "$BUCKET" ] && ENV_FLAGS="--environment SESSION_BUCKET=$BUCKET"

# Deploy function version
echo "Deploying function version..."
yc serverless function version create \
  --function-name "$FUNCTION_NAME" \
  --runtime python312 \
  --entrypoint handler.handler \
  --memory 256m \
  --execution-timeout 5m \
  $ENV_FLAGS \
  --source-path "$CODE_PATH/function.zip"

# Get function ID
FUNCTION_ID=$(yc serverless function get "$FUNCTION_NAME" --format json | jq -r '.id')

echo "Function deployed: $FUNCTION_ID"

# Cleanup
rm -f "$CODE_PATH/function.zip"

echo ""
echo "Deployment complete!"
echo ""
echo "View logs:"
echo "   yc serverless function logs $FUNCTION_ID --follow"
echo ""
echo "Test invocation:"
echo "   yc serverless function invoke $FUNCTION_ID"
echo ""
echo "Remove deployment:"
echo "   yc serverless function delete $FUNCTION_NAME"
