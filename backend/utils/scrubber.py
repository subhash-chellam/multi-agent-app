import re

def redact_pii(text: str) -> str:
    """
    Standardizes PII redaction for the entire ecosystem.
    Masks emails and phone numbers to ensure SOC2/GDPR compliance.
    """
    if not text:
        return ""

    # Email Pattern
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    
    # Phone Pattern (Broad support for international/domestic)
    phone_pattern = r'\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b'
    
    # Redaction
    text = re.sub(email_pattern, "[EMAIL_REDACTED]", text)
    text = re.sub(phone_pattern, "[PHONE_REDACTED]", text)
    
    return text