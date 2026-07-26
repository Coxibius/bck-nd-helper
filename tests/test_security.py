import pytest
from pathlib import Path
from bck_nd_hlpr.security_auditor import scan_security_risks
from bck_nd_hlpr.cli.formatters import get_security_report_string
from bck_nd_hlpr.er_parser import EREntity

def test_hardcoded_secrets_detection(tmp_path):
    # Create files with real-looking secrets (fakes)
    source_file = tmp_path / "app.py"
    source_file.write_text("""
# This is a comment
aws_key = "AKIA1234567890123456"
aws_secret = "AWS_SECRET_ACCESS_KEY='abc/def/ghi/jkl/mno/pqr/stu/vwx/yz12345'"
gh_token = "ghp_abc123xyz789012345678901234567890123"
stripe_live = "sk_live_123456789012345678901234"
stripe_test = "sk_test_123456789012345678901234"
twilio_token = "twilio_auth = 1234567890abcdef1234567890abcdef"
sendgrid_key = "SG.abc123xyzabc123xyzab12.abc123xyzabc123xyzabc123xyzabc123xyzabc1234"
jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
mailchimp_key = "1234567890abcdef1234567890abcdef-us1"
slack_tok = "xoxb-1234567890-abcdefghij"
heroku_tok = "12345678-abcd-1234-abcd-1234567890ab"
npm_tok = "npm_abc123xyz789012345678901234567890123"
""", encoding="utf-8")

    # Add a .env file (unquoted secrets should work here)
    env_file = tmp_path / ".env"
    env_file.write_text("""
DB_PASSWORD=my_db_super_secret_password
""", encoding="utf-8")

    risks = scan_security_risks(str(tmp_path))
    
    # Assert secrets are detected
    types_found = [r['type'] for r in risks]
    
    assert "AWS Access Key" in types_found
    assert "GitHub Token" in types_found
    assert "Stripe Secret" in types_found
    assert "Stripe Test Key" in types_found
    assert "SendGrid Key" in types_found
    assert "JWT Hardcoded" in types_found
    assert "Slack Token" in types_found
    assert "Heroku Key" in types_found
    assert "NPM Token" in types_found
    
    # Assert DB password in .env is detected
    assert any("my_db_super_secret" in r['message'] for r in risks)


def test_false_positives_ignored(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text("""
# Comment line: password = "mysecret"
// Another comment: token = 'xyz'
password = password
var_pwd = pwd
dummy = "changeme"
api_val = "your_key_here"
tag_val = "<your_token_here>"
env_val = os.getenv("MY_KEY")
env_val2 = os.environ.get("MY_KEY")
too_short = "123"
""", encoding="utf-8")

    risks = scan_security_risks(str(tmp_path))
    
    # None of these should be reported as secrets
    # Filter out config files like .env if there were any, but there's none
    secrets = [r for r in risks if r['category'] == 'Secrets']
    assert len(secrets) == 0


def test_sensitive_data_tracker(tmp_path):
    # 1. Create a DB model containing sensitive field
    model_file = tmp_path / "models.py"
    model_file.write_text("""
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50))
    password = Column(String(100))
    credit_card = Column(String(20))
""", encoding="utf-8")

    # 2. Create router exposing the entity
    router_file = tmp_path / "routes.py"
    router_file.write_text("""
from flask import jsonify
from models import User

def get_user_profile(user_id):
    user = User.query.get(user_id)
    return jsonify(user)
""", encoding="utf-8")

    risks = scan_security_risks(str(tmp_path))
    
    sensitive_exposures = [r for r in risks if r['category'] == 'Sensitive Data']
    assert len(sensitive_exposures) > 0
    
    finding = sensitive_exposures[0]
    assert finding['type'] == 'Sensitive Data Exposure'
    assert finding['severity'] == 'HIGH'
    assert "User" in finding['message']
    assert "password" in finding['message']
    assert "credit_card" in finding['message']


def test_report_generation(tmp_path):
    risks = [
        {
            'file': 'app.py',
            'line': 10,
            'type': 'Hardcoded Credential',
            'severity': 'CRITICAL',
            'category': 'Secrets',
            'message': 'Match: password = "secret12345"'
        },
        {
            'file': 'models.py',
            'line': 25,
            'type': 'Sensitive Data Exposure',
            'severity': 'HIGH',
            'category': 'Sensitive Data',
            'message': 'Entity User exposed'
        }
    ]
    
    # Table report
    rich_report = get_security_report_string(risks, plain=False)
    assert "🚨 SECURITY AUDIT REPORT 🚨" in rich_report
    assert "Secrets" in rich_report
    assert "Sensitive Data" in rich_report
    assert "CRITICAL" in rich_report
    assert "HIGH" in rich_report
    
    # Plain report (grouped by file)
    plain_report = get_security_report_string(risks, plain=True)
    assert "File: app.py" in plain_report
    assert "File: models.py" in plain_report
    assert "[CRITICAL] Line 10: Hardcoded Credential" in plain_report
    assert "[HIGH] Line 25: Sensitive Data Exposure" in plain_report
    assert "Risk Score: CRITICAL" in plain_report
    assert "1 Critical · 1 High · 0 Warning" in plain_report
