import logging
import os
import sys
from datetime import datetime

import azure.functions as func

# Make sure we can import your project modules
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
MODULE_DIR = os.path.join(BASE_DIR, "modules")
if MODULE_DIR not in sys.path:
    sys.path.append(MODULE_DIR)

# Import your orchestrator
import main1 as app  # rename if you use main.py instead

def main(mytimer: func.TimerRequest) -> None:
    when = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    logging.info("DailyRunner fired at %s", when)

    try:
        app.run()  # calls your end-to-end pipeline (email included)
        logging.info("DailyRunner completed OK.")
    except Exception as e:
        logging.exception("DailyRunner failed: %s", e)
        # Let the exception be logged; Functions will record failure in App Insights