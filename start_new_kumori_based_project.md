# Start New Kumori-Enabled GCP Project

**Definitive guide for setting up a new GCP project that connects to the kumori-404602 database and secrets**

## 🎯 Overview

This guide creates a new GCP project that:

- Uses **kumori-404602** as the database and secrets provider
- Connects cross-project to Cloud SQL instance `kumori-404602:us-central1:kumori`
- Accesses secrets stored in kumori-404602 Secret Manager
- Deploys to App Engine with proper permissions

---

## 📋 Prerequisites

- Google Cloud SDK installed and authenticated
- Access to kumori-404602 project (for granting permissions)
- Billing account with available quota

---

## 🚀 PHASE 1: CREATE NEW PROJECT

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

# 🔑 CRITICAL: Enable Cloud SQL Admin API (prevents connection refused errors)
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

## 🔐 PHASE 2: CONFIGURE CROSS-PROJECT ACCESS

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

## 📁 PHASE 3: PREPARE PROJECT FILES

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

# 🔑 CRITICAL: Cross-project Cloud SQL configuration
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

## 💻 PHASE 4: CREATE UTILITIES

### 4.1 Create utilities/google_secret_utils.py

```python
# Save as utilities/google_secret_utils.py
from google.cloud import secretmanager

# Hardcode the kumori project ID
KUMORI_PROJECT_ID = "kumori-404602"

def get_secret_version(secret_id, project_id=KUMORI_PROJECT_ID, version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

def get_database_connection_config() -> dict:
    """
    Get all database connection configuration from Secret Manager

    Returns:
        Dictionary with database connection parameters
    """
    config = {}

    # Define your secret mappings (update these based on your actual secret names)
    config_mappings = {
        'host': 'YOUR_PROJECT_POSTGRES_HOST',
        'dbname': 'YOUR_PROJECT_POSTGRES_DB_NAME',
        'user': 'YOUR_PROJECT_POSTGRES_USERNAME',
        'password': 'YOUR_PROJECT_POSTGRES_PASSWORD',
        'connection_name': 'YOUR_PROJECT_POSTGRES_CONNECTION_NAME'
    }

    for key, secret_name in config_mappings.items():
        try:
            config[key] = get_secret_version(secret_name)
            print(f"✅ Retrieved {secret_name}")
        except Exception as e:
            print(f"❌ Failed to retrieve {secret_name}: {e}")
            config[key] = None

    return config
```

### 4.2 Create utilities/postgres_utils.py

```python
# Save as utilities/postgres_utils.py
import time
import psycopg2
import psycopg2.extras
import logging
import os
from .google_secret_utils import get_database_connection_config

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

def get_db_connection(max_retries=5, delay=2):
    logger.debug("Fetching database connection")
    retries = 0
    while retries < max_retries:
        try:
            # Fetching secrets from Google Secret Manager
            db_config = get_database_connection_config()

            dbname = db_config['dbname']
            user = db_config['user']
            password = db_config['password']
            port = db_config.get('port', '5432')
            connection_name = db_config.get('connection_name', '')

            # *** CROSS-PROJECT CONNECTION LOGIC ***
            is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')

            if is_gcp:
                # App Engine Standard - Use Unix socket for Cloud SQL
                if connection_name:
                    host = f"/cloudsql/{connection_name}"
                    logger.debug(f"🌐 App Engine: Using Cloud SQL socket: {host}")
                else:
                    logger.error("❌ No connection_name provided for App Engine deployment")
                    raise Exception("Missing Cloud SQL connection name for App Engine")
            else:
                # Local development: Use public IP address
                host = db_config['host']
                logger.debug(f"🏠 Local development: Using public IP: {host}")

            logger.debug(f"DB config: DB_NAME={dbname}, DB_USER={user}, HOST={host}, DB_PORT={port}")

            # Connect to database
            dsn = {
                'dbname': dbname,
                'user': user,
                'password': password,
                'host': host,
                'port': port,
                'connect_timeout': 10
            }
            connection = psycopg2.connect(**dsn)
            logger.debug("✅ Database connection established successfully")
            return connection
        except Exception as e:
            retries += 1
            logger.warning(f"Database connection failed. Retrying {retries}/{max_retries} in {delay} seconds. Error: {e}")
            time.sleep(delay)

    logger.error("Maximum retries reached. Could not establish a database connection.")
    raise Exception("Failed to connect to the database after multiple attempts.")

def test_connection():
    """Simple test function"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        logger.info(f"PostgreSQL version: {version[0]}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False
```

---

## 🧪 PHASE 5: CREATE TEST APPLICATION

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
    <h1>🎉 New Kumori-Enabled Project</h1>
    <p>This project is connected to kumori-404602 database and secrets.</p>

    <h2>🧪 Connection Tests</h2>
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

## 🔑 PHASE 6: CONFIGURE SECRETS

### 6.1 Create Secrets in Kumori Project

```bash
# Switch to kumori project
gcloud config set project $KUMORI_PROJECT

# Create secrets for your new project (replace YOUR_PROJECT with actual name)
gcloud secrets create YOUR_PROJECT_POSTGRES_HOST --data-file=- <<< "YOUR_DB_HOST_IP"
gcloud secrets create YOUR_PROJECT_POSTGRES_DB_NAME --data-file=- <<< "YOUR_DB_NAME"
gcloud secrets create YOUR_PROJECT_POSTGRES_USERNAME --data-file=- <<< "YOUR_DB_USER"
gcloud secrets create YOUR_PROJECT_POSTGRES_PASSWORD --data-file=- <<< "YOUR_DB_PASSWORD"
gcloud secrets create YOUR_PROJECT_POSTGRES_CONNECTION_NAME --data-file=- <<< "kumori-404602:us-central1:kumori"

# Grant access to these specific secrets
for secret in YOUR_PROJECT_POSTGRES_HOST YOUR_PROJECT_POSTGRES_DB_NAME YOUR_PROJECT_POSTGRES_USERNAME YOUR_PROJECT_POSTGRES_PASSWORD YOUR_PROJECT_POSTGRES_CONNECTION_NAME; do
    gcloud secrets add-iam-policy-binding $secret \
        --member="serviceAccount:${NEW_PROJECT}@appspot.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet
    echo "✅ Granted access to $secret"
done
```

### 6.2 Update google_secret_utils.py

```bash
# Update the secret names in utilities/google_secret_utils.py
# Replace the config_mappings with your actual secret names
```

---

## 🚀 PHASE 7: DEPLOY AND TEST

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
echo "🌐 Your app is live at: https://${NEW_PROJECT}.appspot.com"
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

## ✅ VERIFICATION CHECKLIST

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
- [ ] utilities/google_secret_utils.py
- [ ] utilities/postgres_utils.py

### Database Connection ✓

- [ ] Secrets created in kumori-404602
- [ ] Connection string uses Unix socket format in App Engine
- [ ] Connection string uses public IP for local development

### Test Endpoints ✓

- [ ] `/` homepage loads
- [ ] `/health` returns 200
- [ ] `/test_db_connection` succeeds
- [ ] Logs show "Database connection established successfully"

---

## 🔧 TROUBLESHOOTING

### Common Issues:

**Connection Refused Error:**

```bash
# Enable Cloud SQL Admin API (most common fix)
gcloud services enable sqladmin.googleapis.com --project=$NEW_PROJECT
```

**Permission Denied:**

```bash
# Re-grant permissions
gcloud projects add-iam-policy-binding kumori-404602 \
    --member="serviceAccount:${NEW_PROJECT}@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

**Secret Not Found:**

```bash
# Verify secret exists and has correct name
gcloud secrets list --project=kumori-404602
```

**App Engine Service Account Missing:**

```bash
# Verify App Engine was properly initialized
gcloud app describe --project=$NEW_PROJECT
```

---

## 📚 FINAL NOTES

1. **Always enable Cloud SQL Admin API** - this is the #1 cause of connection failures
2. **Use consistent naming** - follow pattern: `PROJECTNAME_POSTGRES_*` for secrets
3. **Test locally first** - use `.env` file with public IP for local development
4. **Monitor logs** - use `gcloud app logs tail` to debug issues
5. **Keep secrets secure** - never commit credentials to version control

**🎉 Your new project should now be fully connected to kumori-404602!**
