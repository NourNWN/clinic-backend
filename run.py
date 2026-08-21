from app import create_app
from app import models  # يضمن تسجيل الجداول عند إضافتها لاحقاً

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
