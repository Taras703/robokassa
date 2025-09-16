import os
from typing import Optional

class Config:
    ROBOKASSA_MERCHANT_LOGIN: str = os.environ.get("ROBOKASSA_MERCHANT_LOGIN", "robo-demo")
    ROBOKASSA_PASSWORD1: str = os.environ.get("ROBOKASSA_PASSWORD1", "password1")
    ROBOKASSA_PASSWORD2: str = os.environ.get("ROBOKASSA_PASSWORD2", "password2")
    ROBOKASSA_TEST_MODE: bool = os.environ.get("ROBOKASSA_TEST_MODE", "1") == "1"
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me")
    DATABASE_URI: Optional[str] = os.environ.get("DATABASE_URI")
