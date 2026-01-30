FROM python:3.11-slim

WORKDIR /app

# Tmux 및 빌드 도구 설치 (psutil 컴파일용)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tmux gcc python3-dev tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
