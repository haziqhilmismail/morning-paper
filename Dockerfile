# = upstream requirements.txt minus opencv/numpy (lead_image_avoid_faces is off), pytest and yt-dlp.
FROM python:3.12-slim
# python:slim has no tzdata, and TZ (from PAPER_TZ) is an IANA name.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "trafilatura>=1.12" "ebooklib>=0.18" "requests>=2.31" "Pillow>=10.1" "lxml>=5"
# --user 1000 has no passwd entry, and HOME=/ is not writable.
ENV HOME=/tmp
WORKDIR /app
