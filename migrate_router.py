#!/usr/bin/env python3
"""
Migrate api/router.py to use LLMClient.
"""
import re

# Read the file
with open('api/router.py', 'r') as f:
    content = f.read()

# Track changes
changes = []

# Replace all client.messages.create calls with client.complete
# Pattern 1: Classification calls (lines 218, 795, 1055) - use classifier_client
# Pattern 2: Synthesis calls (lines 1186, 1315) - use generator_client
# Pattern 3: Evaluation calls (line 845, 1203) - use classifier_client (Haiku)

# First, let's replace client references based on context
# Classification patterns
replacements = [
    # classify_entity_scope_handler (line 218)
    (
        r'(def classify_entity_scope_handler.*?\n.*?handler_name = "".*?\n\s+)response = client\.messages\.create\(',
        r'\1response = classifier_client.complete('
    ),
    # _call_haiku_for_dynamic_query (line 795)
    (
        r'(def _call_haiku_for_dynamic_query.*?\n.*?resp = )client\.messages\.create\(',
        r'\1classifier_client.complete('
    ),
    # Evaluation in route_and_synthesize (line 845)
    (
        r'(eval_resp = )client\.messages\.create\(',
        r'\1classifier_client.complete('
    ),
    # Intent classification (line 1055)
    (
        r'(intent_resp = )client\.messages\.create\(',
        r'\1classifier_client.complete('
    ),
    # Synthesis (line 1186)
    (
        r'(# ── 7\. Synthesize answer.*?\n\s+answer_resp = )client\.messages\.create\(',
        r'\1generator_client.complete(',
        re.DOTALL
    ),
    # Verification (line 1203)
    (
        r'(# ── 8\. Verify numbers.*?\n\s+verify_resp = )client\.messages\.create\(',
        r'\1classifier_client.complete(',
        re.DOTALL
    ),
    # Synthesis fallback (line 1315)
    (
        r'(answer_resp = )client\.messages\.create\(',
        r'\1generator_client.complete('
    ),
]

for pattern, replacement, *flags in replacements:
    flag = flags[0] if flags else 0
    content = re.sub(pattern, replacement, content, flags=flag)
    changes.append(f"Replaced client with appropriate LLMClient in pattern")

# Now replace model= and system= parameter order and response access patterns
# Replace model="..." with just system=...  (model comes from config now)
content = re.sub(r'model="[^"]+",\s*', '', content)
changes.append("Removed model parameters")

# Replace response.content[0].text with response.text
content = re.sub(r'response\.content\[0\]\.text', 'response.text', content)
content = re.sub(r'intent_resp\.content\[0\]\.text', 'intent_resp.text', content)
content = re.sub(r'answer_resp\.content\[0\]\.text', 'answer_resp.text', content)
content = re.sub(r'verify_resp\.content\[0\]\.text', 'verify_resp.text', content)
content = re.sub(r'eval_resp\.content\[0\]\.text', 'eval_resp.text', content)
content = re.sub(r'resp\.content\[0\]\.text', 'resp.text', content)
changes.append("Replaced .content[0].text with .text")

# Write back
with open('api/router.py', 'w') as f:
    f.write(content)

print("Migration complete!")
for change in changes:
    print(f"  - {change}")
