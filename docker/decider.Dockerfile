# Step 1: Strands Decider 2B behind the System One API (POST /v1/systemone), on CPU.
# Needs about 8 GB of RAM: on CPU the torso runs in fp32 (bf16 kernels are slower there).
FROM python:3.12-slim

RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir strands-decider==0.1.0

ENV HF_HOME=/models
EXPOSE 8001
CMD ["strands-decider", "serve", "StrandsAgents/strands-decider-2B-hobson-v19", \
     "--host", "0.0.0.0", "--port", "8001", "--device", "cpu"]
