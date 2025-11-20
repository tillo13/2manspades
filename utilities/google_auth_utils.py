"""
Simple Google OAuth2 authentication utility for Two Man Spades
Uses Google Secret Manager for credentials stored in twomanspades project
"""

import requests
from flask import session, redirect, url_for, request
from authlib.integrations.flask_client import OAuth
from functools import wraps
from google.cloud import secretmanager

def get_secret(secret_name, project_id="twomanspades"):
    """Get secret from Google Secret Manager"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

class SimpleGoogleAuth:
    def __init__(self, app):
        self.app = app
        self.oauth = OAuth(app)
        
        # Configure Google OAuth using Secret Manager
        self.google = self.oauth.register(
            name='google',
            client_id=get_secret('GOOGLE_CLIENT_ID'),
            client_secret=get_secret('GOOGLE_CLIENT_SECRET'),
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
    
    def login(self):
        """Start Google OAuth flow"""
        redirect_uri = url_for('auth_callback', _external=True)
        return self.google.authorize_redirect(redirect_uri)

    def handle_callback(self):
        """Handle OAuth callback and store user info in session"""
        try:
            token = self.google.authorize_access_token()
            if token:
                user_info = token.get('userinfo')
                if user_info:
                    # Store in session
                    session['user'] = {
                        'email': user_info.get('email'),
                        'name': user_info.get('name'),
                        'picture': user_info.get('picture'),
                        'google_id': user_info.get('sub')
                    }
                    
                    # Log to console for now (no database writes)
                    print(f"[AUTH] User logged in successfully:")
                    print(f"[AUTH]   Email: {user_info.get('email')}")
                    print(f"[AUTH]   Name: {user_info.get('name')}")
                    print(f"[AUTH]   Google ID: {user_info.get('sub')}")
                    
                    return True
        except Exception as e:
            print(f"[AUTH] Error during callback: {e}")
        return False
    
    def logout(self):
        """Clear session"""
        user = session.get('user')
        if user:
            print(f"[AUTH] User logged out: {user.get('email')}")
        session.pop('user', None)
    
    def get_current_user(self):
        """Get current user from session"""
        return session.get('user')
    
    def is_authenticated(self):
        """Check if user is logged in"""
        return 'user' in session

# Decorator for protecting routes (not used yet, but available for future)
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def welcome_message():
    """Generate welcome message for logged in user"""
    user = session.get('user')
    if user:
        return f"Welcome back, {user.get('name', 'Player')}!"
    return "Welcome, Guest!"