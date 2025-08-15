# DailyRunner/__init__.py
import logging, traceback
import azure.functions as func

try:
    from main1 import run  # expects /home/site/wwwroot/main1.py to define run()
except Exception as e:
    logging.error("Failed to import main1.run(): %s\n%s", e, traceback.format_exc())
    raise

def main(mytimer: func.TimerRequest) -> None:
    logging.info("DailyRunner triggered")
    try:
        run()
        logging.info("DailyRunner finished")
    except Exception as e:
        logging.error("DailyRunner runtime error: %s\n%s", e, traceback.format_exc())
        raise