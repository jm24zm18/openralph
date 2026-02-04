docker run --gpus all \
  --shm-size 32g \
  -p 30000:30000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -v ~/tiktoken_encodings:/tiktoken_encodings \
  --env "HF_TOKEN=<your_hf_token>" \
  --env "TIKTOKEN_ENCODINGS_BASE=/tiktoken_encodings" \
  --ipc=host \
  lmsysorg/sglang:spark \
  python3 -m sglang.launch_server \
    --model-path openai/gpt-oss-120b \
    --host 0.0.0.0 \
    --port 30000 \
    --reasoning-parser gpt-oss \
    --tool-call-parser gpt-oss
