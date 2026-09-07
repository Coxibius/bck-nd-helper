import json
import pytest
from pathlib import Path
from bck_nd_hlpr.security_auditor import scan_security_risks
from bck_nd_hlpr.cli.formatters import get_security_report_string
from bck_nd_hlpr.er_parser import EREntity
from bck_nd_hlpr.core.sanitizer import REDACTION_MARKER, sanitize_text

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
    assert "Heroku Key" not in types_found
    assert "NPM Token" in types_found
    
    # Assert DB password in .env is detected
    assert any(r["type"] == "Database Password" for r in risks)
    serialized = json.dumps(risks)
    assert "my_db_super_secret_password" not in serialized
    assert REDACTION_MARKER in serialized


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


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        ("bearer=short-secret", "short-secret"),
        ("bearer: short-secret", "short-secret"),
        ('password: "correct horse battery staple"', "correct horse battery staple"),
        ("secret='value with spaces'", "value with spaces"),
        ("Authorization: Bearer abc.def.1234567890", "abc.def.1234567890"),
        ("sk-proj-abcdefghijklmnopqrstuvwxyz1234567890", "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"),
        ("sk-svcacct-abcdefghijklmnopqrstuvwxyz1234567890", "sk-svcacct-abcdefghijklmnopqrstuvwxyz1234567890"),
        ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"),
        ("sk-abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG", "sk-abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG"),
    ],
)
def test_context_sanitizer_redacts_modern_and_quoted_credentials(source, secret):
    sanitized = sanitize_text(source)

    assert secret not in sanitized
    assert REDACTION_MARKER in sanitized
    assert sanitize_text(sanitized) == sanitized


@pytest.mark.parametrize(
    "normal_text",
    [
        "The token budget is shared between product documents.",
        "Secret management remains outside this tool.",
        "Bearer authentication is supported by the API gateway.",
    ],
)
def test_context_sanitizer_preserves_normal_product_language(normal_text):
    assert sanitize_text(normal_text) == normal_text


def test_context_sanitizer_preserves_quotes_and_bounds_quoted_values():
    source = 'password: "correct horse battery staple"'
    sanitized = sanitize_text(source)

    assert sanitized == f'password: "{REDACTION_MARKER}"'
    oversized = 'password: "' + ("x" * 4097) + '"'
    oversized_sanitized = sanitize_text(oversized)
    assert oversized_sanitized == f'password: "{REDACTION_MARKER}"'
    assert len(oversized_sanitized) < len(oversized)


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        (
            "JWT=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        ),
        (
            "SG.abcdefghijklmnopqrstuv."
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO12",
            "SG.abcdefghijklmnopqrstuv."
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO12",
        ),
        (
            'TWILIO_AUTH_TOKEN="0123456789abcdef0123456789abcdef"',
            "0123456789abcdef0123456789abcdef",
        ),
                (
            "SK" + ("0123456789abcdef" * 2),
            "SK" + ("0123456789abcdef" * 2),
        ),
        (
            "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",
            "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",
        ),
        ("AKIA1234567890123456", "AKIA1234567890123456"),
        ("ghp_abcdefghijklmnopqrstuvwxyz1234567890", "ghp_abcdefghijklmnopqrstuvwxyz1234567890"),
        ("glpat-abcdefghijklmnopqrstuvwxyz123456", "glpat-abcdefghijklmnopqrstuvwxyz123456"),
                (
            "xoxb-" + "-".join(("123456789012", "123456789012", "a" * 24)),
            "xoxb-" + "-".join(("123456789012", "123456789012", "a" * 24)),
        ),
        (
            "sk_" + "live_" + ("a" * 24),
            "sk_" + "live_" + ("a" * 24),
        ),
        ("whsec_123456789012345678901234", "whsec_123456789012345678901234"),
        ("npm_abcdefghijklmnopqrstuvwxyz1234567890", "npm_abcdefghijklmnopqrstuvwxyz1234567890"),
        (
            "-----BEGIN PRIVATE KEY-----\nQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=\n"
            "-----END PRIVATE KEY-----",
            "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=",
        ),
        (
            "postgresql://app:correct-horse-battery-staple@db.example/app",
            "correct-horse-battery-staple",
        ),
                (
            "mailchimp=" + ("0123456789abcdef" * 2) + "-us1",
            ("0123456789abcdef" * 2) + "-us1",
        ),
    ],
)
def test_shared_credential_registry_redacts_high_confidence_formats(source, secret):
    sanitized = sanitize_text(source)

    assert secret not in sanitized
    assert REDACTION_MARKER in sanitized
    assert sanitize_text(sanitized) == sanitized


@pytest.mark.parametrize(
    "normal_text",
    [
        "token_count = 128",
        "JWT_ALGORITHM = HS256",
        "request_id = 123e4567-e89b-12d3-a456-426614174000",
        "checksum = 0123456789abcdef0123456789abcdef",
    ],
)
def test_shared_credential_registry_preserves_common_identifiers(normal_text):
    assert sanitize_text(normal_text) == normal_text


def test_security_findings_keep_metadata_but_never_secret_in_any_report(
    tmp_path,
    monkeypatch,
):
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    source = tmp_path / "app.py"
    original = f'github_token = "{secret}"\n'.encode("utf-8")
    source.write_bytes(original)

    risks = scan_security_risks(str(tmp_path))
    finding = next(risk for risk in risks if risk["type"] == "GitHub Token")

    assert finding["file"] == "app.py"
    assert finding["line"] == 1
    assert finding["severity"] == "CRITICAL"
    assert finding["category"] == "Secrets"
    assert finding["message"] == f"Match: {REDACTION_MARKER}"
    assert secret[:12] not in finding["message"]

    rich_report = get_security_report_string(risks, plain=False)
    plain_report = get_security_report_string(risks, plain=True)
    json_report = json.dumps(risks, ensure_ascii=False)
    monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
    from bck_nd_hlpr.cli import mcp_server as mcp_server_module
    mcp_report = mcp_server_module.audit_security()

    for report in (rich_report, plain_report, json_report, mcp_report):
        assert secret not in report
    assert REDACTION_MARKER in json_report
    assert source.read_bytes() == original


def test_direct_security_scan_uses_safe_indexer_once(tmp_path, monkeypatch):
    import bck_nd_hlpr.core.er_parser as er_parser_module
    import bck_nd_hlpr.core.security_auditor as security_module

    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    source = tmp_path / "app.py"
    source.write_text(f'github_token = "{secret}"\n', encoding="utf-8")
    real_indexer = security_module.FileSystemIndexer
    indexer_calls = []

    def tracked_indexer(*args, **kwargs):
        indexer_calls.append((args, kwargs))
        return real_indexer(*args, **kwargs)

    monkeypatch.setattr(security_module, "FileSystemIndexer", tracked_indexer)
    monkeypatch.setattr(er_parser_module, "parse_project_for_er", lambda *_args, **_kwargs: [])

    risks = security_module.scan_security_risks(str(tmp_path))

    assert len(indexer_calls) == 1
    assert any(risk["type"] == "GitHub Token" for risk in risks)
    assert secret not in json.dumps(risks)


def test_sensitive_exposure_scan_uses_safe_indexer(tmp_path, monkeypatch):
    import bck_nd_hlpr.core.security_auditor as security_module

    route = tmp_path / "routes.py"
    route.write_text("def show(user):\n    return jsonify(user)\n", encoding="utf-8")
    entity = EREntity("User")
    entity.columns.append(("password", "String"))
    real_indexer = security_module.FileSystemIndexer
    indexer_calls = []

    def tracked_indexer(*args, **kwargs):
        indexer_calls.append((args, kwargs))
        return real_indexer(*args, **kwargs)

    monkeypatch.setattr(security_module, "FileSystemIndexer", tracked_indexer)

    risks = security_module.scan_sensitive_exposures(str(tmp_path), [entity])

    assert len(indexer_calls) == 1
    assert any(risk["type"] == "Sensitive Data Exposure" for risk in risks)


def test_security_scan_with_file_list_never_walks_again(tmp_path, monkeypatch):
    import bck_nd_hlpr.core.er_parser as er_parser_module
    import bck_nd_hlpr.core.security_auditor as security_module

    source = tmp_path / "app.py"
    source.write_text(
        'github_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"\n',
        encoding="utf-8",
    )

    def forbidden_indexer(*_args, **_kwargs):
        raise AssertionError("FileSystemIndexer must not run for a supplied file list")

    monkeypatch.setattr(security_module, "FileSystemIndexer", forbidden_indexer)
    monkeypatch.setattr(er_parser_module, "parse_project_for_er", lambda *_args, **_kwargs: [])

    risks = security_module.scan_security_risks(
        str(tmp_path),
        file_list=[source],
    )

    assert any(risk["type"] == "GitHub Token" for risk in risks)


def test_simulated_reparse_entries_never_reach_security_outputs(
    tmp_path,
    monkeypatch,
):
    import bck_nd_hlpr.core.er_parser as er_parser_module
    import bck_nd_hlpr.core.security_auditor as security_module
    import bck_nd_hlpr.core.utils.indexer as indexer_module
    from bck_nd_hlpr.cli import mcp_server as mcp_server_module

    secret = "ghp_externalreparsecredential1234567890"
    linked_file = tmp_path / "linked.py"
    linked_file.write_text(f'github_token = "{secret}"\n', encoding="utf-8")
    linked_directory = tmp_path / "linked-directory"
    linked_directory.mkdir()
    (linked_directory / "nested.py").write_text(
        f'github_token = "{secret}"\n',
        encoding="utf-8",
    )
    safe_file = tmp_path / "safe.py"
    safe_file.write_text(
        'github_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"\n',
        encoding="utf-8",
    )
    unsafe_states = {
        (linked_file.lstat().st_dev, linked_file.lstat().st_ino),
        (linked_directory.lstat().st_dev, linked_directory.lstat().st_ino),
    }

    def simulated_reparse(path_stat):
        return (path_stat.st_dev, path_stat.st_ino) in unsafe_states

    monkeypatch.setattr(indexer_module, "_is_link_or_reparse", simulated_reparse)
    monkeypatch.setattr(er_parser_module, "parse_project_for_er", lambda *_args, **_kwargs: [])
    monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))

    risks = security_module.scan_security_risks(str(tmp_path))
    plain = get_security_report_string(risks, plain=True)
    serialized = json.dumps(risks, ensure_ascii=False)
    mcp_result = mcp_server_module.audit_security()

    assert any(risk["file"] == "safe.py" for risk in risks)
    for output in (serialized, plain, mcp_result):
        assert secret not in output
        assert "linked.py" not in output
        assert "linked-directory" not in output


def test_external_symlink_secret_never_reaches_security_outputs_when_supported(
    tmp_path,
    monkeypatch,
):
    from bck_nd_hlpr.cli import mcp_server as mcp_server_module

    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external.py"
    secret = "ghp_externalsymlinkcredential1234567890"
    external.write_text(f'github_token = "{secret}"\n', encoding="utf-8")
    linked = project / "linked.py"
    try:
        linked.symlink_to(external)
    except OSError:
        return
    monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))

    risks = scan_security_risks(str(project))
    plain = get_security_report_string(risks, plain=True)
    serialized = json.dumps(risks, ensure_ascii=False)
    mcp_result = mcp_server_module.audit_security()

    for output in (serialized, plain, mcp_result):
        assert secret not in output
        assert "linked.py" not in output
