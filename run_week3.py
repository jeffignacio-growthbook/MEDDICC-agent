#!/usr/bin/env python3
"""Run week-3 conversion with environment loaded."""
from dotenv import load_dotenv
load_dotenv()

import subprocess
import sys

result = subprocess.run(
    ['python3', 'scripts/analytics/forecast_analyses.py'],
    env=subprocess.os.environ.copy()
)
sys.exit(result.returncode)
