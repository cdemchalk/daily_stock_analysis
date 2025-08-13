import datetime
import logging
import azure.functions as func

def main(mytimer: func.TimerRequest) -> None:
    utc_ts = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()
    logging.info(f"Hello World! Function ran at {utc_ts}")