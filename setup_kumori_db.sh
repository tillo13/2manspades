#!/bin/bash

# Create NEW TWOMANSPADES_POSTGRES_* secrets 
# This creates brand new secrets for 2manspades, leaving KUMORI_POSTGRES_* untouched

SECRETS_PROJECT="kumori-404602"
SERVICE_ACCOUNT="twomanspades@appspot.gserviceaccount.com"

echo "Creating NEW TWOMANSPADES_POSTGRES_* secrets (keeping KUMORI_POSTGRES_* untouched)"
echo ""

# Based on your past conversations, the kumori secrets use these values:
# You can reuse the same database instance for 2manspades with a different schema

echo "Creating TWOMANSPADES_POSTGRES_IP secret..."
echo "Enter your PostgreSQL server IP (probably same as KUMORI):"
read -r POSTGRES_IP
echo "$POSTGRES_IP" | gcloud secrets create TWOMANSPADES_POSTGRES_IP --data-file=- --project=$SECRETS_PROJECT
echo "✅ Created TWOMANSPADES_POSTGRES_IP"
echo ""

echo "Creating TWOMANSPADES_POSTGRES_DB_NAME secret..."
echo "Enter database name (probably same as KUMORI):"
read -r DB_NAME  
echo "$DB_NAME" | gcloud secrets create TWOMANSPADES_POSTGRES_DB_NAME --data-file=- --project=$SECRETS_PROJECT
echo "✅ Created TWOMANSPADES_POSTGRES_DB_NAME"
echo ""

echo "Creating TWOMANSPADES_POSTGRES_USERNAME secret..."
echo "Enter PostgreSQL username (probably same as KUMORI):"
read -r DB_USERNAME
echo "$DB_USERNAME" | gcloud secrets create TWOMANSPADES_POSTGRES_USERNAME --data-file=- --project=$SECRETS_PROJECT
echo "✅ Created TWOMANSPADES_POSTGRES_USERNAME"
echo ""

echo "Creating TWOMANSPADES_POSTGRES_PASSWORD secret..."
echo "Enter PostgreSQL password (probably same as KUMORI):"
read -s -r DB_PASSWORD
echo "$DB_PASSWORD" | gcloud secrets create TWOMANSPADES_POSTGRES_PASSWORD --data-file=- --project=$SECRETS_PROJECT
echo "✅ Created TWOMANSPADES_POSTGRES_PASSWORD"
echo ""

echo "Creating TWOMANSPADES_POSTGRES_CONNECTION_NAME secret..."
echo "Enter connection name (format: kumori-404602:us-central1:kumori):"
read -r CONNECTION_NAME
echo "$CONNECTION_NAME" | gcloud secrets create TWOMANSPADES_POSTGRES_CONNECTION_NAME --data-file=- --project=$SECRETS_PROJECT
echo "✅ Created TWOMANSPADES_POSTGRES_CONNECTION_NAME"
echo ""

# Grant permissions to twomanspades service account
echo "Granting permissions to twomanspades service account..."

SECRETS=(
    "TWOMANSPADES_POSTGRES_IP"
    "TWOMANSPADES_POSTGRES_DB_NAME"
    "TWOMANSPADES_POSTGRES_USERNAME"
    "TWOMANSPADES_POSTGRES_PASSWORD"
    "TWOMANSPADES_POSTGRES_CONNECTION_NAME"
)

for secret in "${SECRETS[@]}"; do
    echo "Granting access to $secret..."
    gcloud secrets add-iam-policy-binding $secret \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/secretmanager.secretAccessor" \
        --project=$SECRETS_PROJECT
    
    if [ $? -eq 0 ]; then
        echo "  ✅ Granted access to $secret"
    else
        echo "  ❌ Failed to grant access to $secret"
    fi
done

echo ""
echo "✅ TWOMANSPADES database secrets setup complete!"
echo ""
echo "📋 Created NEW secrets (KUMORI secrets unchanged):"
echo "  - TWOMANSPADES_POSTGRES_IP: $POSTGRES_IP"
echo "  - TWOMANSPADES_POSTGRES_DB_NAME: $DB_NAME"  
echo "  - TWOMANSPADES_POSTGRES_USERNAME: $DB_USERNAME"
echo "  - TWOMANSPADES_POSTGRES_PASSWORD: [hidden]"
echo "  - TWOMANSPADES_POSTGRES_CONNECTION_NAME: $CONNECTION_NAME"
echo ""
echo "🚀 Next step: Create utilities/postgres_utils.py that references these TWOMANSPADES secrets"
echo ""
echo "Verify secrets were created:"
echo "gcloud secrets list --project=$SECRETS_PROJECT | grep TWOMANSPADES"