# Start New Kumori-Enabled GCP Project

**Definitive guide for setting up a new GCP project that connects to the kumori-404602 database and secrets**

## Overview

This guide creates a new GCP project that:

- Uses **kumori-404602** as the database and secrets provider
- Connects cross-project to Cloud SQL instance `kumori-404602:us-central1:kumori`
- Accesses secrets stored in kumori-404602 Secret Manager
- Deploys to App Engine with proper permissions

---

## Prerequisites

- Google Cloud SDK installed and authenticated
- Access to kumori-404602 project (for granting permissions)
- Billing account with available quota

---

## PHASE 1: CREATE NEW PROJECT

### 1.1 Create Project

```bash
# Replace 'your-new-project' with your desired project name
export NEW_PROJECT="your-new-project"
export KUMORI_PROJECT="kumori-404602"
export SQL_INSTANCE="kumori"
export REGION="us-central1"

# Create the project
gcloud projects create $NEW_PROJECT --name="Your Project Name"

# Set as active project
gcloud config set project $NEW_PROJECT
```

### 1.2 Enable Billing

```bash
# List billing accounts
gcloud billing accounts list

# Link billing account (replace BILLING_ACCOUNT_ID)
gcloud billing projects link $NEW_PROJECT --billing-account=BILLING_ACCOUNT_ID
```

### 1.3 Enable Required APIs

```bash
# Enable core services
gcloud services enable appengine.googleapis.com --project=$NEW_PROJECT
gcloud services enable secretmanager.googleapis.com --project=$NEW_PROJECT
gcloud services enable cloudbuild.googleapis.com --project=$NEW_PROJECT

# CRITICAL: Enable Cloud SQL Admin API (prevents connection refused errors)
gcloud services enable sqladmin.googleapis.com --project=$NEW_PROJECT

# Verify APIs are enabled
gcloud services list --enabled --filter="name:(appengine|secretmanager|cloudbuild|sqladmin)" --project=$NEW_PROJECT
```

### 1.4 Initialize App Engine

```bash
# Create App Engine application
gcloud app create --region=us-central1 --project=$NEW_PROJECT
```

---

## PHASE 2: CONFIGURE CROSS-PROJECT ACCESS

### 2.1 Grant Secret Manager Access

```bash
# Switch to kumori project to grant permissions
gcloud config set project $KUMORI_PROJECT

# Get the new project's service account
NEW_PROJECT_SA="${NEW_PROJECT}@appspot.gserviceaccount.com"

# Grant Secret Manager access to ALL kumori secrets
gcloud projects add-iam-policy-binding $KUMORI_PROJECT \
    --member="serviceAccount:$NEW_PROJECT_SA" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet

echo "✅ Granted Secret Manager access to $NEW_PROJECT_SA"
```

### 2.2 Grant Cloud SQL Access

```bash
# Still in kumori project
# Grant Cloud SQL Client role
gcloud projects add-iam-policy-binding $KUMORI_PROJECT \
    --member="serviceAccount:$NEW_PROJECT_SA" \
    --role="roles/cloudsql.client" \
    --quiet

# Grant Cloud SQL Viewer role
gcloud projects add-iam-policy-binding $KUMORI_PROJECT \
    --member="serviceAccount:$NEW_PROJECT_SA" \
    --role="roles/cloudsql.viewer" \
    --quiet

echo "✅ Granted Cloud SQL access to $NEW_PROJECT_SA"
```

### 2.3 Verify Cloud SQL Instance

```bash
# Check that kumori Cloud SQL instance is running
gcloud sql instances describe $SQL_INSTANCE --project=$KUMORI_PROJECT --format="value(state)"

# Should return "RUNNABLE"
echo "✅ Cloud SQL instance verified"
```

---

## PHASE 3: PREPARE PROJECT FILES

### 3.1 Create app.yaml

```yaml
# Save as app.yaml
runtime: python312
instance_class: F1

entrypoint: gunicorn -b :$PORT main:app

automatic_scaling:
  min_instances: 0
  max_instances: 2

env_variables:
  GCP_PROJECT_ID: "YOUR_NEW_PROJECT"
  GAE_ENV: "standard"
  FLASK_ENV: "production"

# CRITICAL: Cross-project Cloud SQL configuration
beta_settings:
  cloud_sql_instances: "kumori-404602:us-central1:kumori"

handlers:
  - url: /static
    static_dir: static
    secure: always
  - url: /favicon\.ico
    static_files: static/favicon.ico
    upload: static/favicon\.ico
    secure: always
  - url: /.*
    script: auto
    secure: always
    redirect_http_response_code: 301
```

### 3.2 Create requirements.txt

```txt
# Save as requirements.txt
Flask==3.0.0
psycopg2-binary==2.9.9
google-cloud-secret-manager==2.18.1
python-dotenv==1.0.0
gunicorn==21.2.0
workos==1.6.0
PyPDF2==3.0.1
python-docx==0.8.11
flask-wtf==1.2.1
wtforms==3.1.1
fuzzywuzzy==0.18.0
python-Levenshtein==0.21.1
```

### 3.3 Create .gitignore

```bash
# Save as .gitignore
.env
*.env
__pycache__/
*.pyc
venv*/
env/
.vscode/
.idea/
.DS_Store
gather_files.py
*_project_structure.txt
```

### 3.4 Create .gcloudignore

```bash
# Save as .gcloudignore
.git/
.gitignore
*.md
.env
*.env
__pycache__/
*.pyc
venv*/
.vscode/
.idea/
gather_files.py
*_project_structure.txt
```

---

## PHASE 4: CREATE UTILITIES

### 4.1 Create utilities/postgres_utils.py

```python
# Save as utilities/postgres_utils.py
import psycopg2
import psycopg2.extras
import json
import os
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Any, Optional

def get_secret(secret_id: str, project_id: str = "kumori-404602") -> str:
    """Get secret from Google Secret Manager"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

def get_db_connection():
    """Create database connection using YOUR_PROJECT secrets"""
    is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
    
    if is_gcp:
        # Production - use secrets and Cloud SQL socket
        connection_name = get_secret('YOUR_PROJECT_POSTGRES_CONNECTION_NAME')
        host = f"/cloudsql/{connection_name}"
        dbname = get_secret('YOUR_PROJECT_POSTGRES_DB_NAME') 
        user = get_secret('YOUR_PROJECT_POSTGRES_USERNAME')
        password = get_secret('YOUR_PROJECT_POSTGRES_PASSWORD')
    else:
        # Local development - use environment variables or direct secrets
        try:
            # Try secrets first (in case you want to test with real DB locally)
            host = get_secret('YOUR_PROJECT_POSTGRES_IP')
            dbname = get_secret('YOUR_PROJECT_POSTGRES_DB_NAME')
            user = get_secret('YOUR_PROJECT_POSTGRES_USERNAME')
            password = get_secret('YOUR_PROJECT_POSTGRES_PASSWORD')
        except:
            # Fallback to env vars for local dev
            host = os.getenv('DB_HOST', 'localhost')
            dbname = os.getenv('DB_NAME', 'yourproject_dev')
            user = os.getenv('DB_USER', 'postgres') 
            password = os.getenv('DB_PASSWORD', 'password')
    
    return psycopg2.connect(
        host=host,
        database=dbname,
        user=user,
        password=password,
        connect_timeout=10
    )

def test_connection():
    """Test database connection"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"✅ PostgreSQL connection successful: {version[0]}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

# Add your specific CRUD functions here
def insert_game(game_data: Dict[str, Any]) -> bool:
    """Insert new game record with robust error handling"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Debug: print what we're trying to insert
        print(f"Attempting to insert game: {game_data.get('game_id')}")
        
        cur.execute("""
            INSERT INTO yourschema.games 
            (game_id, started_at, player_parity, computer_parity, first_leader, client_ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            game_data['game_id'],
            datetime.fromtimestamp(game_data['game_started_at']),
            game_data['player_parity'],
            game_data['computer_parity'], 
            game_data['first_leader'],
            game_data.get('client_info', {}).get('ip_address'),
            game_data.get('client_info', {}).get('user_agent')
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Game {game_data.get('game_id')} successfully inserted")
        return True
    except Exception as e:
        print(f"❌ Failed to insert game {game_data.get('game_id')}: {e}")
        # Try to close connection if it exists
        try:
            if 'conn' in locals():
                conn.close()
        except:
            pass
        return False

def log_game_event_to_db(game_id: str, event_type: str, event_data: Dict, **kwargs) -> bool:
    """Log game event to database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO yourschema.game_events 
            (game_id, event_type, event_data, hand_number, session_sequence, player, action_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            game_id,
            event_type,
            json.dumps(event_data),
            kwargs.get('hand_number'),
            kwargs.get('session_sequence'),
            kwargs.get('player'),
            kwargs.get('action_type')
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Failed to log event: {e}")
        return False
```

---

## PHASE 5: CREATE TEST APPLICATION

### 5.1 Create main.py

```python
# Save as main.py
from flask import Flask, render_template, jsonify
import logging
import os
from utilities.postgres_utils import get_db_connection, test_connection

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'change-this-secret-key'

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/test_db_connection')
def test_db_connection():
    """Test endpoint to verify database connectivity"""
    try:
        success = test_connection()
        if success:
            return jsonify({
                'status': 'success',
                'message': 'Database connection successful!',
                'project': os.environ.get('GCP_PROJECT_ID', 'unknown')
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': 'Database connection failed'
            }), 500
    except Exception as e:
        logger.error(f"Database test failed: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Database connection error: {str(e)}'
        }), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
```

### 5.2 Create templates/index.html

```html
<!-- Save as templates/index.html -->
<!DOCTYPE html>
<html>
  <head>
    <title>{{ project_name or 'New Kumori-Enabled Project' }}</title>
    <style>
      body {
        font-family: Arial, sans-serif;
        margin: 40px;
      }
      .status {
        padding: 20px;
        margin: 20px 0;
        border-radius: 5px;
      }
      .success {
        background-color: #d4edda;
        color: #155724;
      }
      .error {
        background-color: #f8d7da;
        color: #721c24;
      }
      button {
        padding: 10px 20px;
        margin: 10px;
      }
    </style>
  </head>
  <body>
    <h1>New Kumori-Enabled Project</h1>
    <p>This project is connected to kumori-404602 database and secrets.</p>

    <h2>Connection Tests</h2>
    <button onclick="testDatabase()">Test Database Connection</button>
    <button onclick="testHealth()">Test Health Endpoint</button>

    <div id="results"></div>

    <script>
      async function testDatabase() {
        const response = await fetch("/test_db_connection");
        const data = await response.json();
        showResult(data, response.ok);
      }

      async function testHealth() {
        const response = await fetch("/health");
        const data = await response.json();
        showResult(data, response.ok);
      }

      function showResult(data, success) {
        const div = document.getElementById("results");
        div.innerHTML = `
                <div class="status ${success ? "success" : "error"}">
                    <strong>Status:</strong> ${data.status}<br>
                    <strong>Message:</strong> ${
                      data.message || "No message"
                    }<br>
                    ${
                      data.project
                        ? `<strong>Project:</strong> ${data.project}`
                        : ""
                    }
                </div>
            `;
      }
    </script>
  </body>
</html>
```

---

## PHASE 6: CONFIGURE SECRETS

### 6.1 Create Secrets in Kumori Project

**CRITICAL: Use printf instead of echo to avoid newline issues that cause authentication failures**

```bash
# Switch to kumori project
gcloud config set project $KUMORI_PROJECT

# Create secrets using printf to avoid trailing newlines
# Replace YOUR_PROJECT with your actual project name and values
printf "YOUR_DB_HOST_IP" | gcloud secrets create YOUR_PROJECT_POSTGRES_IP --data-file=- --project=$KUMORI_PROJECT
printf "YOUR_DB_NAME" | gcloud secrets create YOUR_PROJECT_POSTGRES_DB_NAME --data-file=- --project=$KUMORI_PROJECT
printf "YOUR_DB_USER" | gcloud secrets create YOUR_PROJECT_POSTGRES_USERNAME --data-file=- --project=$KUMORI_PROJECT
printf "YOUR_DB_PASSWORD" | gcloud secrets create YOUR_PROJECT_POSTGRES_PASSWORD --data-file=- --project=$KUMORI_PROJECT
printf "kumori-404602:us-central1:kumori" | gcloud secrets create YOUR_PROJECT_POSTGRES_CONNECTION_NAME --data-file=- --project=$KUMORI_PROJECT

# Grant access to these specific secrets
for secret in YOUR_PROJECT_POSTGRES_IP YOUR_PROJECT_POSTGRES_DB_NAME YOUR_PROJECT_POSTGRES_USERNAME YOUR_PROJECT_POSTGRES_PASSWORD YOUR_PROJECT_POSTGRES_CONNECTION_NAME; do
    gcloud secrets add-iam-policy-binding $secret \
        --member="serviceAccount:${NEW_PROJECT}@appspot.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor" \
        --project=$KUMORI_PROJECT \
        --quiet
    echo "✅ Granted access to $secret"
done
```

### 6.2 Update postgres_utils.py Secret Names

Update the secret names in your `utilities/postgres_utils.py` to match what you created:

```python
# Replace YOUR_PROJECT_POSTGRES_* with your actual secret names
connection_name = get_secret('YOUR_PROJECT_POSTGRES_CONNECTION_NAME')
dbname = get_secret('YOUR_PROJECT_POSTGRES_DB_NAME')
# etc.
```

---

## PHASE 7: DEPLOY AND TEST

### 7.1 Create Directory Structure

```bash
# Create required directories
mkdir -p templates utilities static

# Switch back to your new project
gcloud config set project $NEW_PROJECT
```

### 7.2 Deploy Application

```bash
# Deploy to App Engine
gcloud app deploy app.yaml --project=$NEW_PROJECT

# Get the deployment URL
echo "Your app is live at: https://${NEW_PROJECT}.appspot.com"
```

### 7.3 Test Deployment

```bash
# Test the health endpoint
curl "https://${NEW_PROJECT}.appspot.com/health"

# Test the database connection
curl "https://${NEW_PROJECT}.appspot.com/test_db_connection"

# View logs
gcloud app logs tail --project=$NEW_PROJECT
```

---

## VERIFICATION CHECKLIST

### APIs Enabled ✓

- [ ] App Engine API
- [ ] Secret Manager API
- [ ] Cloud Build API
- [ ] **Cloud SQL Admin API** (critical!)

### Permissions Granted ✓

- [ ] Secret Manager Accessor role on kumori-404602
- [ ] Cloud SQL Client role on kumori-404602
- [ ] Cloud SQL Viewer role on kumori-404602

### Configuration Files ✓

- [ ] app.yaml with `beta_settings: cloud_sql_instances`
- [ ] requirements.txt with all dependencies
- [ ] .gitignore and .gcloudignore
- [ ] utilities/postgres_utils.py with robust error handling

### Database Connection ✓

- [ ] Secrets created in kumori-404602 using printf (no newlines)
- [ ] Connection string uses Unix socket format in App Engine
- [ ] Connection string uses public IP for local development
- [ ] Error handling shows actual database errors

### Test Endpoints ✓

- [ ] `/` homepage loads
- [ ] `/health` returns 200
- [ ] `/test_db_connection` succeeds
- [ ] Logs show "Database connection established successfully"

---

## TROUBLESHOOTING

### Common Issues:

**Connection Refused Error:**

```bash
# Enable Cloud SQL Admin API (most common fix)
gcloud services enable sqladmin.googleapis.com --project=$NEW_PROJECT
```

**Authentication Failed for User:**

```bash
# Secrets have newlines - recreate using printf
printf "correct_value" | gcloud secrets versions add SECRET_NAME --data-file=- --project=kumori-404602
```

**Permission Denied:**

```bash
# Re-grant permissions
gcloud projects add-iam-policy-binding kumori-404602 \
    --member="serviceAccount:${NEW_PROJECT}@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

**Foreign Key Constraint Violations:**

```bash
# Game insertion failed but logged success - check error handling
# Look for "Failed to insert game" vs "Game inserted to database" in logs
```

**Secret Not Found:**

```bash
# Verify secret exists and has correct name
gcloud secrets list --project=kumori-404602
```

---

## FINAL NOTES

1. **Always enable Cloud SQL Admin API** - this is the #1 cause of connection failures
2. **Use printf instead of echo** - trailing newlines cause authentication failures
3. **Use robust error handling** - database failures should be clearly logged
4. **Test locally first** - use direct IP connection to verify credentials
5. **Monitor logs carefully** - distinguish between actual success and misleading messages
6. **Keep secrets secure** - never commit credentials to version control

**Your new project should now be fully connected to kumori-404602 with proper error handling!**