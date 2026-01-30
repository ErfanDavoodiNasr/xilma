FROM python:3.12-slim

# App lives here
WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy only what is needed to run
COPY xilma ./xilma
COPY bot.py ./bot.py

CMD ["python", "bot.py"]
