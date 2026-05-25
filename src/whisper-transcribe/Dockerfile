FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Drop CUDA forward-compat: it is a Tesla/datacenter feature, unsupported on the
# consumer GeForce RTX 2060 in this host. With a host driver (535 -> CUDA 12.2)
# older than this 12.3 base image, the bundled libcuda.so.545 engages and cuInit()
# fails with error 804, so CUDA sees 0 devices and WhisperModel(cuda) hangs at
# startup. Removing it makes the container use the host driver via CUDA
# minor-version compatibility (12.3 app on a >=12.0 driver), which GeForce supports.
RUN apt-get update && apt-get purge -y cuda-compat-12-3 \
 && rm -rf /usr/local/cuda*/compat /usr/lib/x86_64-linux-gnu/libcuda.so* /var/lib/apt/lists/* \
 && ldconfig
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY main.py .
COPY test/ ./test/
ENV PYTHONUNBUFFERED=1 \
    WHISPER_MODEL=medium \
    WHISPER_DEVICE=cuda \
    WHISPER_COMPUTE_TYPE=float16 \
    ALLOWED_ROOT=/data/signal-capture
EXPOSE 8090
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
