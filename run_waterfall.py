#!/usr/bin/env python3
"""Run waterfall computation with environment loaded."""
from dotenv import load_dotenv
load_dotenv()

import subprocess
import sys

result = subprocess.run(
    ['python3', 'scripts/analytics/compute_waterfall.py'],
    env=subprocess.os.environ.copy()
)
sys.exit(result.returncode)
