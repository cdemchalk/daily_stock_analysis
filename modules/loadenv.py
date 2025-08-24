import os
from dotenv import load_dotenv
import logging

def load_env(dotenv_path=None, required_keys=None, raise_on_missing=True):
    """
    Load environment variables from a .env file and verify required keys.
    """
    # Skip loading in Azure (env vars are in Function App Settings)
    if os.getenv("FUNCTIONS_WORKER_RUNTIME") == "python":
        logging.info("Running in Azure, skipping .env load")
        found_env = {key: os.getenv(key) for key in required_keys or [] if os.getenv(key)}
        missing_keys = [key for key in required_keys or [] if not os.getenv(key)]
        if missing_keys and raise_on_missing:
            raise EnvironmentError(f"Missing required env vars: {', '.join(missing_keys)}")
        return found_env

    # Default to project root .env (one level up from modules/)
    if dotenv_path is None:
        # Assume loadenv.py is in modules/, go up one directory
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    
    env_dir = os.path.dirname(dotenv_path)
    logging.info(f"Checking for .env in: {env_dir}")

    try:
        files = os.listdir(env_dir)
        logging.info("Directory contents: " + ", ".join(files))
    except FileNotFoundError:
        logging.error(f"Directory {env_dir} not found")
        if raise_on_missing:
            raise FileNotFoundError(f"Directory {env_dir} not found")
        return {}

    env_found = load_dotenv(dotenv_path=dotenv_path)
    if not env_found:
        logging.error(f".env file not found or failed to load at: {dotenv_path}")
        if raise_on_missing:
            raise EnvironmentError(f".env file not found at: {dotenv_path}")
        return {}

    logging.info(".env file loaded successfully")

    found_env = {}
    missing_keys = []

    if required_keys:
        logging.info("Verifying required environment variables...")
        for key in required_keys:
            value = os.getenv(key)
            if value:
                found_env[key] = value
                logging.info(f"  {key}: FOUND")
            else:
                missing_keys.append(key)
                logging.info(f"  {key}: MISSING")

        if missing_keys and raise_on_missing:
            raise EnvironmentError(f"Missing required env vars: {', '.join(missing_keys)}")

    return found_env