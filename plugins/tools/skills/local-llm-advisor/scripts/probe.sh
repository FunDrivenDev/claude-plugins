#!/usr/bin/env bash
# Snapshot of this machine for local-LLM sizing: hardware, GPU memory limits,
# disk, installed runtimes and models, servers already listening.
# Read-only. Every section prints something, even when a tool is missing.

section() { printf '\n## %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

section "OS"
uname -srm
[ "$(uname)" = Darwin ] && sw_vers 2>/dev/null

section "Hardware"
if [ "$(uname)" = Darwin ]; then
  system_profiler SPHardwareDataType 2>/dev/null \
    | grep -E "Model Name|Model Identifier|Chip|Total Number of Cores|Memory:"
  system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Total Number of Cores" | sed 's/^ */GPU /'
  echo "iogpu.wired_limit_mb: $(sysctl -n iogpu.wired_limit_mb 2>/dev/null) (0 = macOS default, about 2/3 to 3/4 of RAM usable by the GPU)"
  echo "power: $(pmset -g batt 2>/dev/null | sed -n 2p | sed 's/^ *//')"
else
  grep -m1 "model name" /proc/cpuinfo 2>/dev/null
  echo "cores: $(nproc 2>/dev/null)"
  free -g 2>/dev/null | sed -n 1,2p
  have nvidia-smi && nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
  have rocm-smi && rocm-smi --showmeminfo vram
fi

section "Memory pressure now"
if [ "$(uname)" = Darwin ]; then
  memory_pressure 2>/dev/null | tail -1
else
  free -h 2>/dev/null | sed -n 2p
fi

section "Disk (home volume)"
df -h "$HOME" | tail -1

section "Runtimes installed"
for bin in ollama lms llama-server llama-cli omlx mlx_lm.server vllm llmfit litellm opencode claude aider goose; do
  if have "$bin"; then
    ver=$("$bin" --version 2>/dev/null | head -1)
    printf '%-14s %s  %s\n' "$bin" "$(command -v "$bin")" "$ver"
  fi
done
[ -d "/Applications/LM Studio.app" ] && echo "LM Studio.app present"
[ -d "/Applications/Ollama.app" ] && echo "Ollama.app present"
[ -d "/Applications/oMLX.app" ] && echo "oMLX.app present"

section "Servers listening (common LLM ports)"
for port in 11434 1234 8080 8000 4000 10240; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "port $port: open"
  fi
done

section "Models already downloaded"
have ollama && ollama list 2>/dev/null
have lms && lms ls 2>/dev/null | head -40
for dir in "$HOME/.cache/huggingface/hub" "$HOME/.lmstudio/models" "$HOME/.cache/lm-studio/models"; do
  [ -d "$dir" ] && { echo "$dir:"; du -sh "$dir"/* 2>/dev/null | sort -rh | head -15; }
done

if have llmfit; then
  section "llmfit system"
  llmfit system 2>/dev/null | head -25
fi
