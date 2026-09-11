"""Shared high-confidence credential registry for detection and redaction."""

import re
from dataclasses import dataclass
from typing import Pattern, Tuple


REDACTION_MARKER = "***REDACTED***"
MAX_QUOTED_SECRET_CHARS = 4096  # Compatibility constant; matching is line-bounded.

_SENSITIVE_KEY_SOURCE = (
    r"password|passwd|pwd|secret|bearer|api[ _-]?key|token|"
    r"auth[ _-]?token|access[ _-]?token|client[ _-]?secret|"
    r"db[ _-]?(?:pass|password)|database[ _-]?password|postgres[ _-]?password|"
    r"mysql[ _-]?root[ _-]?password|database[ _-]?url|"
    r"connection[ _-]?string|conn[ _-]?str|"
    r"aws[ _-]?access[ _-]?key[ _-]?id|"
    r"aws[ _-]?secret[ _-]?access[ _-]?key|"
    r"twilio[ _-]?(?:auth[ _-]?token|api[ _-]?key)|"
    r"mailchimp[ _-]?(?:api[ _-]?key|key)"
)

KEY_VALUE_PATTERN = re.compile(
    rf"(?i)(?P<key_quote>['\"]?)\b(?P<key>{_SENSITIVE_KEY_SOURCE})\b"
    r"(?P=key_quote)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?:"
    r'\"(?P<double_value>[^\"\r\n]*)\"'
    r"|'(?P<single_value>[^'\r\n]*)'"
    r"|(?P<unquoted_value>[^\s,;'\"`}]+)"
    r")"
)

BEARER_PATTERN = re.compile(
    r"(?i)(?P<prefix>\bBearer\s+)"
    r"(?P<value>(?=[A-Za-z0-9._~+/=-]{8,}\b)"
    r"(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{8,})"
)

CONNECTION_URI_PATTERN = re.compile(
    r"(?i)(?P<prefix>\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|"
    r"redis|rediss|amqp|amqps|mssql|sqlserver)://[^\s/:@]+:)"
    r"(?P<value>[^\s/@]+)(?P<suffix>@)"
)

PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?P<label>(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY)-----"
    r".*?-----END (?P=label)-----",
    re.DOTALL,
)
PRIVATE_KEY_HEADER_PATTERN = re.compile(
    r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"
)


@dataclass(frozen=True)
class CredentialPattern:
    """One bounded raw credential shape and its public audit metadata."""

    name: str
    severity: str
    pattern: Pattern[str]


RAW_CREDENTIAL_PATTERNS: Tuple[CredentialPattern, ...] = (
    CredentialPattern(
        "OpenAI API Key",
        "CRITICAL",
        re.compile(
            r"(?<![A-Za-z0-9])sk-(?:proj|svcacct|ant)-"
            r"[A-Za-z0-9_-]{16,255}(?![A-Za-z0-9])"
        ),
    ),
    CredentialPattern(
        "OpenAI API Key",
        "CRITICAL",
        re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{32,255}(?![A-Za-z0-9])"),
    ),
    CredentialPattern(
        "AWS Access Key",
        "CRITICAL",
        re.compile(
            r"\b(?:AKIA|ASIA|A3T[A-Z0-9]|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)"
            r"[A-Z0-9]{16}\b"
        ),
    ),
    CredentialPattern(
        "GitHub Token",
        "CRITICAL",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,255}\b"),
    ),
    CredentialPattern(
        "GitHub Token",
        "CRITICAL",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b"),
    ),
    CredentialPattern(
        "GitLab Token",
        "CRITICAL",
        re.compile(r"\bglpat-[A-Za-z0-9_-]{20,255}\b"),
    ),
    CredentialPattern(
        "Slack Token",
        "HIGH",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b"),
    ),
    CredentialPattern(
        "Stripe Secret",
        "CRITICAL",
        re.compile(r"\bsk_live_[A-Za-z0-9]{16,255}\b"),
    ),
    CredentialPattern(
        "Stripe Test Key",
        "CRITICAL",
        re.compile(r"\bsk_test_[A-Za-z0-9]{16,255}\b"),
    ),
    CredentialPattern(
        "Stripe Restricted Key",
        "CRITICAL",
        re.compile(r"\brk_(?:live|test)_[A-Za-z0-9]{16,255}\b"),
    ),
    CredentialPattern(
        "Stripe Webhook Secret",
        "CRITICAL",
        re.compile(r"\bwhsec_[A-Za-z0-9]{16,255}\b"),
    ),
    CredentialPattern(
        "NPM Token",
        "HIGH",
        re.compile(r"\bnpm_[A-Za-z0-9]{20,255}\b"),
    ),
    CredentialPattern(
        "JWT Hardcoded",
        "CRITICAL",
        re.compile(
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,255}\."
            r"[A-Za-z0-9_-]{10,4096}\.[A-Za-z0-9_-]{10,1024}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialPattern(
        "SendGrid Key",
        "CRITICAL",
        re.compile(r"(?<![A-Za-z0-9_-])SG\.[A-Za-z0-9_-]{20,64}\.[A-Za-z0-9_-]{40,128}"),
    ),
    CredentialPattern(
        "Twilio API Key",
        "CRITICAL",
        re.compile(r"\bSK[0-9a-fA-F]{32}\b"),
    ),
    CredentialPattern(
        "Mailchimp Key",
        "CRITICAL",
        re.compile(r"\b[a-fA-F0-9]{32}-us[0-9]{1,2}\b"),
    ),
)


def credential_metadata_for_key(key: str) -> Tuple[str, str]:
    """Return stable audit metadata for a sensitive assignment key."""
    normalized = re.sub(r"[ _-]+", "_", key.casefold())
    if normalized in {
        "db_pass",
        "db_password",
        "database_password",
        "postgres_password",
        "mysql_root_password",
    }:
        return "Database Password", "HIGH"
    if normalized == "aws_secret_access_key":
        return "AWS Secret Key", "CRITICAL"
    if normalized in {"twilio_auth_token", "twilio_api_key"}:
        return "Twilio Auth Token", "CRITICAL"
    return "Hardcoded Credential", "CRITICAL"


__all__ = [
    "BEARER_PATTERN",
    "CONNECTION_URI_PATTERN",
    "CredentialPattern",
    "KEY_VALUE_PATTERN",
    "MAX_QUOTED_SECRET_CHARS",
    "PRIVATE_KEY_HEADER_PATTERN",
    "PRIVATE_KEY_PATTERN",
    "RAW_CREDENTIAL_PATTERNS",
    "REDACTION_MARKER",
    "credential_metadata_for_key",
]
