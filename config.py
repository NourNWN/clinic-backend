import os
from dotenv import load_dotenv

load_dotenv()  # يقرأ ملف .env ويحمّله كمتغيرات بيئة


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
