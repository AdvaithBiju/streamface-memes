# StreamFace Memes backend for Render (see DEPLOY.md).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOST=0.0.0.0

# OpenCV needs libGL/glib. Anton is a free Impact look-alike for meme captions.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
ADD https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf /usr/share/fonts/truetype/anton/Anton-Regular.ttf
RUN chmod 644 /usr/share/fonts/truetype/anton/Anton-Regular.ttf

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Render sets PORT; the app reads it.
CMD ["python", "run.py"]
