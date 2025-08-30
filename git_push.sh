#!/bin/bash

# TWO MAN SPADES PROJECT CONFIGURATION - CRITICAL SAFEGUARDS
EXPECTED_PROJECT="twomanspades"
SERVICE_NAME="default"

# Check if a commit message was provided
if [ -z "$1" ]; then
  echo "You must provide a commit message."
  exit 1
fi

# Initialize the git repository if not already done
if [ ! -d ".git" ]; then
  echo "Setting up git repository for the first time..."

  git init
  if [ ! -f "README.md" ]; then
    echo "# Two Man Spades" >> README.md
    git add README.md
    git commit -m "Add README.md for initial setup"
  fi

  git remote add origin https://github.com/tillo13/2manspades.git
  git branch -M main
  git push -u origin main
fi

# Add all changes to git
git add .

# Commit the changes with the provided message
git commit -m "$1"

# Push to GitHub
git push origin main

if [ $? -ne 0 ]; then
  echo ""
  echo "####################################"
  echo "# MERGE CONFLICT RESOLUTION STEPS: #"
  echo "####################################"
  echo ""
  echo "1. Fetch the latest changes from the remote repository:"
  echo "   git fetch origin"
  echo ""
  echo "2. Merge the changes from the remote branch into your local branch:"
  echo "   git merge origin/main"
  echo ""
  echo "3. If you encounter merge conflicts, open the conflicting files and resolve all conflicts manually."
  echo ""
  echo "4. Once resolved, stage the resolved files:"
  echo "   git add <filename>"
  echo ""
  echo "5. Finalize the merge with a commit:"
  echo "   git commit -m 'Resolve merge conflicts'"
  echo ""
  echo "6. Now push your changes again:"
  echo "   git push origin main"
  echo ""
  exit 1
fi

# CRITICAL SAFEGUARD: Verify we're deploying to the correct Google Cloud project
CURRENT_PROJECT=$(gcloud config get-value project)
echo ""
echo "=== GOOGLE CLOUD PROJECT VERIFICATION ==="
echo "Expected project: $EXPECTED_PROJECT"
echo "Current project:  $CURRENT_PROJECT"

if [ "$CURRENT_PROJECT" != "$EXPECTED_PROJECT" ]; then
  echo ""
  echo "❌ ERROR: Google Cloud project mismatch!"
  echo "Current project '$CURRENT_PROJECT' does not match expected project '$EXPECTED_PROJECT'"
  echo ""
  echo "Attempting to switch to correct project..."
  
  # Try to use an existing configuration first
  if gcloud config configurations list --format="value(name)" | grep -q "twomanspades-config"; then
    echo "Using existing twomanspades-config configuration"
    gcloud config configurations activate twomanspades-config
  else
    echo "Setting project directly to $EXPECTED_PROJECT"
    gcloud config set project $EXPECTED_PROJECT
  fi
  
  # Verify the switch was successful
  CURRENT_PROJECT=$(gcloud config get-value project)
  if [ "$CURRENT_PROJECT" != "$EXPECTED_PROJECT" ]; then
    echo ""
    echo "❌ CRITICAL ERROR: Failed to switch to $EXPECTED_PROJECT project!"
    echo "Deployment ABORTED to prevent deploying to wrong project."
    echo ""
    echo "Please manually set the project with one of these commands:"
    echo "  gcloud config configurations activate twomanspades-config"
    echo "  gcloud config set project $EXPECTED_PROJECT"
    echo ""
    echo "Then re-run this script."
    exit 1
  else
    echo "✅ Successfully switched to $EXPECTED_PROJECT project"
  fi
else
  echo "✅ Project verification passed - deploying to correct project"
fi

echo "=========================================="
echo ""

# Deploy to Google App Engine using the gcloud_deploy.py script
echo "Starting deployment to Google App Engine for $EXPECTED_PROJECT..."
python3 gcloud_deploy.py
DEPLOY_EXIT_CODE=$?

# Only proceed if deployment was successful
if [ $DEPLOY_EXIT_CODE -eq 0 ]; then
  echo ""
  echo "✅ Deployment to Google Cloud completed successfully!"
  echo "Visit https://$EXPECTED_PROJECT.appspot.com to see your Two Man Spades game."
  echo ""
  
  # Prompt to tail logs with a 10-second timeout
  read -t 10 -p "Would you like to tail logs now? (default is yes): " -r response

  response=$(echo "$response" | tr '[:upper:]' '[:lower:]')

  if [[ $response =~ ^(no|n)$ ]]; then
      echo "Not tailing the logs."
      echo ""
      echo "You can view logs anytime with: gcloud app logs tail -s $SERVICE_NAME --project $EXPECTED_PROJECT"
  else
      echo "Tailing the logs from the Google App Engine $SERVICE_NAME service..."
      echo "Press Ctrl+C to stop tailing logs."
      gcloud app logs tail -s $SERVICE_NAME --project $EXPECTED_PROJECT
  fi
else
  echo ""
  echo "❌ Deployment failed with exit code: $DEPLOY_EXIT_CODE"
  echo "Please check the error messages above."
  exit $DEPLOY_EXIT_CODE
fi