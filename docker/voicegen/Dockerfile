FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
  && rm -rf /var/lib/apt/lists/*

# Coqui TTS supports py<3.12; we use py3.11 in this container.
RUN pip install --no-cache-dir --upgrade pip wheel
RUN pip install --no-cache-dir TTS==0.22.0 \
  && pip install --no-cache-dir "transformers<5" "tokenizers<0.20" torchcodec \
  && python -c "import transformers; print('transformers', transformers.__version__)"

WORKDIR /work

# Warm import
RUN python -c "from TTS.api import TTS; print('TTS import OK')"
