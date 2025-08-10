# DailyRunner/main_function.py
import logging
import sys
import os

# Make sure we can import from the repo root
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import main  # your existing main.py

def main_function(timer) -> None:
    logging.info("Azure Function triggered.")
    main.run()