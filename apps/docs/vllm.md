# vLLM Backend (Primary)

This project now serves Qwen3 Coder 30B through vLLM. The helper scripts in `scripts/` wrap the vLLM OpenAI-compatible server and align with the defaults captured in `models/vllm-qwen-setup.md`.

## Quickstart

1. **Install vLLM (host CUDA 12+)**

   ```bash
   pip install --upgrade vllm
   ```

2. **Export/model path and start vLLM**

   ```bash
   # MODEL_DIR should already contain the Qwen3 Coder 30B weights (AWQ or FP16)
   MODEL_DIR=/path/to/qwen3-coder-30b \
   bash scripts/serve_llm.sh
   ```

   Default flags:
   - Serves `qwen3-coder` on `0.0.0.0:8000`
   - Requires `Authorization: Bearer qwen-local`
   - Enables tool calling (`--enable-auto-tool-choice --tool-call-parser hermes`)

   Override via env vars (`PORT`, `API_KEY`, `MAX_LEN`, `QUANTIZATION`, etc.). See `scripts/serve_llm.sh` for the full list.

3. **Start the rest of the stack**

   ```bash
   ./start.sh   # launches vLLM (if not already running), Orchestrator, Gateway, optional tunnel
   ```

   `.env` defaults map both Solver/Thinking roles to the single vLLM endpoint:
   ```ini
   SOLVER_URL=http://127.0.0.1:8000/v1/chat/completions
   THINK_URL=http://127.0.0.1:8000/v1/chat/completions
   SOLVER_MODEL_ID=qwen3-coder
   THINK_MODEL_ID=qwen3-coder
   SOLVER_API_KEY=qwen-local
   THINK_API_KEY=qwen-local
   ```

4. **Validate**

   ```bash
   curl -s http://127.0.0.1:8000/v1/models -H "Authorization: Bearer qwen-local"
   curl -s http://127.0.0.1:8000/v1/chat/completions \
     -H "Authorization: Bearer qwen-local" \
     -H "Content-Type: application/json" \
     -d '{"model":"qwen3-coder","messages":[{"role":"user","content":"ping"}]}'
   bash ./server_health.sh
   ```

5. **Stop services**

   ```bash
   ./stop.sh          # stops Gateway/Orchestrator and calls scripts/stop_llm.sh
   scripts/stop_llm.sh  # standalone stop if only the model server is running
   ```

## Additional Notes

- `scripts/serve_llm.sh` writes logs to `./vllm.log` and the PID to `./vllm.pid`; adjust via `LOG_PATH` / `PID_PATH`.
- If you already run vLLM elsewhere, set `VLLM_START=0` before calling `start.sh` so the script won’t launch another instance.
- `server_health.sh` now targets the vLLM endpoint and verifies both model listing and chat output using the configured bearer token.
- Continue/OpenCode configs should point at `http://127.0.0.1:8000/v1` with the same API key (`qwen-local` by default).
