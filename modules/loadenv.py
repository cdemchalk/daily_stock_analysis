import os
from dotenv import load_dotenv


def load_env(dotenv_path="/mnt/e/Financial/.env", required_keys=None, raise_on_missing=True):
    """
    Load environment variables from a .env file and verify required keys.

    Args:
        dotenv_path (str): Full path to the .env file.
        required_keys (list): List of environment variable keys that must be present.
        raise_on_missing (bool): If True, raises error if any required key is missing.

    Returns:
        dict: Dictionary of found key-value pairs (only for required_keys, if specified).
    """

    env_dir = os.path.dirname(dotenv_path)
    print(f"🔍 Checking for .env in: {env_dir}")

    try:
        files = os.listdir(env_dir)
        print("📁 Directory contents:")
        for f in files:
            print(" -", f)
    except FileNotFoundError:
        print(f"❌ Directory {env_dir} not found.")
        if raise_on_missing:
            raise FileNotFoundError(f"Directory {env_dir} not found.")
        return {}

    # Load the .env file
    env_found = load_dotenv(dotenv_path=dotenv_path)
    if not env_found:
        print("❌ .env file not found or failed to load.")
        if raise_on_missing:
            raise EnvironmentError(f".env file not found at: {dotenv_path}")
        return {}

    print("✅ .env file loaded successfully.")

    found_env = {}
    missing_keys = []

    if required_keys:
        print("🔎 Verifying required environment variables...")
        for key in required_keys:
            value = os.getenv(key)
            if value:
                found_env[key] = value
                print(f"  ✅ {key}: FOUND")
            else:
                missing_keys.append(key)
                print(f"  ❌ {key}: MISSING")

        if missing_keys and raise_on_missing:
            raise EnvironmentError(f"Missing required env vars: {', '.join(missing_keys)}")

    return found_env

